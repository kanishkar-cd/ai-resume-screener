import asyncio
from pathlib import Path
from time import perf_counter
from uuid import UUID

import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppException, InternalServerException
from app.db.session import AsyncSessionLocal
from app.models.document import DocumentModel
from app.models.parsed_document import ParsedDocumentModel
from app.repositories.document_repository import DocumentRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.schemas.document import ProcessingStage, ProcessingStatus
from app.schemas.parsed_document import (
    ParsedDocumentCreate,
    ParsedDocumentRead,
    ParseDocumentResponse,
)
from app.services.document_service import (
    DocumentFileMissingException,
    DocumentNotFoundException,
)
from app.services.parsers.base_parser import (
    BaseParser,
    DocumentParsingException,
    UnsupportedFormatException,
)
from app.services.parsers.docx_parser import DocxParser
from app.services.parsers.pdf_parser import PDFParser
from app.services.parsers.txt_parser import TxtParser
from app.services.pipeline.normalization_pipeline import normalize_text
from app.services.storage_service import StorageService

logger = structlog.get_logger(__name__)


class ParsedDocumentNotFoundException(AppException):
    status_code = 404
    error_code = "PARSED_DOCUMENT_NOT_FOUND"
    default_message = "The document has not been parsed."


class ParserFactory:
    """Select the deterministic parser registered for a document MIME type."""

    _parsers: dict[str, type[BaseParser]] = {
        "application/pdf": PDFParser,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocxParser,
        "text/plain": TxtParser,
    }

    @classmethod
    def create(cls, mime_type: str) -> BaseParser:
        parser_class = cls._parsers.get(mime_type)
        if parser_class is None:
            raise UnsupportedFormatException()
        return parser_class()


class ParsingService:
    """Idempotent document parsing use case, independent of task transport."""

    def __init__(
        self,
        document_repository: DocumentRepository,
        parsed_repository: ParsedDocumentRepository,
        storage: StorageService,
    ) -> None:
        self.document_repository = document_repository
        self.parsed_repository = parsed_repository
        self.storage = storage

    async def prepare_parsing(
        self, document_id: UUID
    ) -> tuple[ParseDocumentResponse, bool]:
        document = await self._get_document(document_id)
        existing = await self._get_existing_parsed(document_id)
        if existing is not None:
            return (
                ParseDocumentResponse(
                    document_id=document_id,
                    status=ProcessingStatus.COMPLETED,
                    processing_stage=ProcessingStage.COMPLETED,
                    message="Document was already parsed.",
                ),
                False,
            )
        try:
            ParserFactory.create(document.mime_type)
            if self.storage.resolve_file(document.file_path) is None:
                raise DocumentFileMissingException()
        except AppException as exc:
            await self._mark_failed(document_id, exc.message)
            raise
        await self.document_repository.update_processing(
            document_id,
            ProcessingStage.PARSING,
            ProcessingStatus.IN_PROGRESS,
        )
        return (
            ParseDocumentResponse(
                document_id=document_id,
                status=ProcessingStatus.IN_PROGRESS,
                processing_stage=ProcessingStage.PARSING,
                message="Document parsing accepted.",
            ),
            True,
        )

    async def parse_document(self, document_id: UUID) -> ParseDocumentResponse:
        document = await self._get_document(document_id)
        existing = await self._get_existing_parsed(document_id)
        if existing is not None:
            return ParseDocumentResponse(
                document_id=document_id,
                status=ProcessingStatus.COMPLETED,
                processing_stage=ProcessingStage.COMPLETED,
                message="Document was already parsed.",
            )

        try:
            parser = ParserFactory.create(document.mime_type)
            file_path = self.storage.resolve_file(document.file_path)
            if file_path is None:
                raise DocumentFileMissingException()
            await self.document_repository.update_processing(
                document_id,
                ProcessingStage.PARSING,
                ProcessingStatus.IN_PROGRESS,
            )
            started_at = perf_counter()
            extracted = await asyncio.to_thread(parser.parse, file_path)
            normalized = normalize_text(extracted.raw_text)
            duration_ms = (perf_counter() - started_at) * 1000
            await self.parsed_repository.create_or_update(
                ParsedDocumentCreate(
                    document_id=document_id,
                    raw_text=extracted.raw_text,
                    normalized_text=normalized.normalized_text,
                    page_count=extracted.page_count,
                    word_count=normalized.word_count,
                    character_count=normalized.character_count,
                    language=normalized.language,
                    parser_engine=extracted.parser_engine,
                    parsing_duration_ms=duration_ms,
                    parsing_metadata=extracted.metadata,
                )
            )
            await self.document_repository.update_processing(
                document_id,
                ProcessingStage.COMPLETED,
                ProcessingStatus.COMPLETED,
            )
        except AppException as exc:
            await self._mark_failed(document_id, exc.message)
            raise
        except Exception as exc:
            await self._mark_failed(document_id, "Document parsing failed.")
            raise DocumentParsingException() from exc

        logger.info(
            "document_parsed_successfully",
            document_id=str(document_id),
            parser_engine=extracted.parser_engine.value,
            parsing_duration_ms=round(duration_ms, 2),
        )
        return ParseDocumentResponse(
            document_id=document_id,
            status=ProcessingStatus.COMPLETED,
            processing_stage=ProcessingStage.COMPLETED,
            message="Document parsed successfully.",
        )

    async def get_parsed_document(self, document_id: UUID) -> ParsedDocumentRead:
        await self._get_document(document_id)
        try:
            parsed = await self.parsed_repository.get_by_document_id(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve parsed document.") from exc
        if parsed is None:
            raise ParsedDocumentNotFoundException()
        return ParsedDocumentRead.model_validate(parsed)

    async def _get_document(self, document_id: UUID) -> DocumentModel:
        try:
            document = await self.document_repository.get_document(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve document.") from exc
        if document is None:
            raise DocumentNotFoundException()
        return document

    async def _get_existing_parsed(
        self, document_id: UUID
    ) -> ParsedDocumentModel | None:
        try:
            return await self.parsed_repository.get_by_document_id(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve parsed document.") from exc

    async def _mark_failed(self, document_id: UUID, message: str) -> None:
        try:
            await self.document_repository.update_processing(
                document_id,
                ProcessingStage.FAILED,
                ProcessingStatus.FAILED,
                error_message=message[:2000],
            )
        except SQLAlchemyError:
            logger.exception(
                "document_failed_status_update_failed", document_id=str(document_id)
            )


async def run_parsing_task(document_id: UUID) -> None:
    """Execute parsing in an independent session for BackgroundTasks/workers."""
    async with AsyncSessionLocal() as session:
        service = ParsingService(
            DocumentRepository(session),
            ParsedDocumentRepository(session),
            StorageService(),
        )
        try:
            await service.parse_document(document_id)
        except Exception:
            logger.exception("background_document_parsing_failed", document_id=str(document_id))
