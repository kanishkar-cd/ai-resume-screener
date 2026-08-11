from asyncio import to_thread
from time import perf_counter
from uuid import UUID

import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import (
    AppException,
    ConflictException,
    InternalServerException,
)
from app.repositories.document_repository import DocumentRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.schemas.document import ProcessingStage, ProcessingStatus
from app.schemas.parsed_document import (
    DocumentParseRead,
    ParsedDocumentCreate,
    ParsedDocumentRead,
    ParserEngine,
)
from app.services.document_service import (
    DocumentFileMissingException,
    DocumentNotFoundException,
)
from app.services.parsers import parse_document_file
from app.services.parsers.base import text_metrics
from app.services.storage_service import StorageService
from app.models.document import DocumentTypeEnum
from app.services.affinda_service import AffindaService
from app.services.parsers.base import ParseOutput

logger = structlog.get_logger(__name__)

PARSEABLE_STATUSES = {
    ProcessingStatus.UPLOADED,
    ProcessingStatus.FAILED,
    ProcessingStatus.PARSED,
}


class DocumentNotParseableException(ConflictException):
    error_code = "DOCUMENT_NOT_PARSEABLE"
    default_message = "Document cannot be parsed in its current processing status."


class ParsedDocumentNotFoundException(AppException):
    status_code = 404
    error_code = "PARSED_DOCUMENT_NOT_FOUND"
    default_message = "No parsed result was found for this document."


class DocumentParseFailedException(AppException):
    status_code = 422
    error_code = "DOCUMENT_PARSE_FAILED"
    default_message = "Document parsing failed."


class ParsingService:
    """Parse uploaded documents and persist extracted text plus metrics."""

    def __init__(
        self,
        document_repository: DocumentRepository,
        parsed_repository: ParsedDocumentRepository,
        storage: StorageService,
        affinda_service: AffindaService | None = None,
    ) -> None:
        self.document_repository = document_repository
        self.parsed_repository = parsed_repository
        self.storage = storage
        self.affinda_service = affinda_service or AffindaService()

    async def parse_document(self, document_id: UUID) -> DocumentParseRead:
        document = await self._load_document(document_id)
        logger.info(
            "[DOCUMENT] processing started",
            document_id=str(document.id),
            filename=document.original_filename,
            document_type=document.document_type.value,
        )
        logger.info(
            "[AFFINDA] configuration checked",
            document_id=str(document.id),
            configured=self.affinda_service.configured,
            document_type=document.document_type.value,
        )
        current_status = ProcessingStatus(document.processing_status.value)
        if current_status == ProcessingStatus.PARSING_PENDING:
            raise DocumentNotParseableException(
                "Document parsing is already in progress."
            )
        if current_status not in PARSEABLE_STATUSES:
            raise DocumentNotParseableException()

        path = self.storage.resolve_file(document.file_path)
        if path is None:
            raise DocumentFileMissingException()

        metadata = dict(document.metadata_json or {})

        await self._set_status(
            document_id,
            ProcessingStatus.PARSING_PENDING,
            {
                **metadata,
                "parse_error": None,
            },
            document=document,
            refresh=False,
        )

        started_at = perf_counter()
        try:
            affinda_payload = await self._try_affinda(document, path)
            if affinda_payload is not None:
                raw_text = affinda_payload["data"].get("rawText")
                if not isinstance(raw_text, str) or not raw_text.strip():
                    logger.warning(
                        "affinda_raw_text_missing_fallback",
                        document_id=str(document.id),
                    )
                    affinda_payload = None
                else:
                    parsed = ParseOutput(
                        raw_text=raw_text,
                        page_count=None,
                        parser_engine=ParserEngine.PLAIN_TEXT,
                        original_parser="AFFINDA",
                    )
            if affinda_payload is None:
                logger.info(
                    "[FALLBACK] local parser started",
                    document_id=str(document.id),
                    reason="affinda_unavailable_or_unsuccessful",
                )
                parsed = await to_thread(parse_document_file, path, document.mime_type)
                logger.info(
                    "[FALLBACK] local parser completed",
                    document_id=str(document.id),
                    parser_engine=parsed.parser_engine.value,
                    provider_selected="local",
                )
            duration_ms = (perf_counter() - started_at) * 1000
            if not parsed.raw_text or not parsed.raw_text.strip():
                raise DocumentParseFailedException(
                    details={"reason": "Document parsing produced empty text."}
                )

            word_count, character_count = text_metrics(parsed.raw_text)
            await self.parsed_repository.upsert(
                ParsedDocumentCreate(
                    document_id=document_id,
                    raw_text=parsed.raw_text,
                    normalized_text=parsed.raw_text,
                    page_count=parsed.page_count,
                    word_count=word_count,
                    character_count=character_count,
                    parser_engine=parsed.parser_engine,
                    parsing_duration_ms=round(duration_ms, 3),
                ),
                commit=False,
                refresh=False,
            )
            updated = await self._set_status(
                document_id,
                ProcessingStatus.PARSED,
                {
                    **metadata,
                    "parse_error": None,
                    "parser_engine": parsed.parser_engine.value,
                    "original_parser": parsed.original_parser or parsed.parser_engine.value,
                    "ocr_fallback_used": parsed.ocr_fallback_used,
                    "ocr_engine": parsed.ocr_engine,
                    "document_intelligence_provider": "affinda" if affinda_payload else "local",
                    "affinda_payload": self._persistable_affinda_payload(
                        affinda_payload
                    ),
                },
                refresh=False,
                document=document,
            )
        except AppException:
            await self.document_repository.session.rollback()
            await self._mark_failed(document_id, metadata, "Parse rejected.")
            raise
        except Exception as exc:
            await self.document_repository.session.rollback()
            await self._mark_failed(
                document_id,
                metadata,
                str(exc) or "Unexpected parse failure.",
            )
            logger.exception(
                "document_parse_failed",
                document_id=str(document_id),
                error_type=type(exc).__name__,
            )
            raise DocumentParseFailedException(
                details={"reason": str(exc) or type(exc).__name__}
            ) from exc

        logger.info(
            "document_parsed_successfully",
            document_id=str(document_id),
            parser_engine=parsed.parser_engine.value,
            duration_ms=round(duration_ms, 3),
            provider_selected="affinda" if affinda_payload else "local",
        )
        return DocumentParseRead(
            document_id=document_id,
            processing_status=ProcessingStatus(updated.processing_status.value),
            processing_stage=ProcessingStage(updated.processing_stage.value),
            message="Document parsed successfully.",
        )

    async def _try_affinda(self, document, path):
        if not self.affinda_service.configured:
            logger.info(
                "[FALLBACK] Affinda skipped",
                document_id=str(document.id),
                configured=False,
                provider_selected="local",
            )
            return None
        try:
            if document.document_type == DocumentTypeEnum.RESUME:
                response = await self.affinda_service.parse_resume(
                    path, document.original_filename, document.mime_type
                )
            elif document.document_type == DocumentTypeEnum.JOB_DESCRIPTION:
                response = await self.affinda_service.parse_job_description(
                    path, document.original_filename, document.mime_type
                )
            else:
                return None
            return {
                "data": response["data"],
                "meta": {"identifier": (response.get("meta") or {}).get("identifier")},
            }
        except Exception as exc:
            logger.warning(
                "[FALLBACK] Affinda failed; local parser selected",
                document_id=str(document.id),
                error_type=type(exc).__name__,
                sanitized_message=str(exc),
                provider_selected="local",
            )
        return None

    @staticmethod
    def _persistable_affinda_payload(payload):
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        return {
            "data": {key: value for key, value in data.items() if key != "rawText"},
            "meta": payload.get("meta") or {},
        }

    async def get_parsed_document(self, document_id: UUID) -> ParsedDocumentRead:
        await self._load_document(document_id)
        try:
            parsed = await self.parsed_repository.get_by_document_id(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException(
                "Unable to retrieve parsed document."
            ) from exc
        if parsed is None:
            raise ParsedDocumentNotFoundException()
        return ParsedDocumentRead(
            id=parsed.id,
            document_id=parsed.document_id,
            raw_text=parsed.raw_text,
            page_count=parsed.page_count,
            word_count=parsed.word_count,
            character_count=parsed.character_count,
            parser_engine=ParserEngine(parsed.parser_engine),
            parsing_duration_ms=parsed.parsing_duration_ms,
            created_at=parsed.created_at,
            updated_at=parsed.updated_at,
        )

    async def _load_document(self, document_id: UUID):
        try:
            document = await self.document_repository.get_document(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve document.") from exc
        if document is None:
            raise DocumentNotFoundException()
        return document

    async def _set_status(
        self,
        document_id: UUID,
        status: ProcessingStatus,
        metadata: dict[str, object],
        *,
        commit: bool = True,
        refresh: bool = True,
        document=None,
    ):
        try:
            updated = await self.document_repository.update_status(
                document_id, status, metadata, commit=commit, refresh=refresh,
                document=document,
            )
        except SQLAlchemyError as exc:
            raise InternalServerException(
                "Unable to update document processing status."
            ) from exc
        if updated is None:
            raise DocumentNotFoundException()
        return updated

    async def _mark_failed(
        self,
        document_id: UUID,
        metadata: dict[str, object] | None,
        reason: str,
    ) -> None:
        try:
            await self._set_status(
                document_id,
                ProcessingStatus.FAILED,
                {**(metadata or {}), "parse_error": reason},
            )
        except Exception:
            logger.exception(
                "document_parse_failure_status_update_failed",
                document_id=str(document_id),
            )
