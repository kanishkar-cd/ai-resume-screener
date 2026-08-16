from uuid import UUID
from time import perf_counter

import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppException, InternalServerException
from app.models.document import DocumentModel, DocumentTypeEnum
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.parsed_document_repository import ParsedDocumentRepository
from app.schemas.document import DocumentType, ProcessingStage, ProcessingStatus
from app.schemas.extracted_info import (
    ExtractDocumentResponse,
    ExtractedJobDescriptionCreate,
    ExtractedJobDescriptionRead,
    ExtractedResumeCreate,
    ExtractedResumeRead,
)
from app.services.document_service import DocumentNotFoundException
from app.services.extractors import JobDescriptionExtractor, ResumeExtractor
from app.services.extractors.ai_resume_extractor import AIResumeExtractor
from app.services.extractors.resume_merge import merge_resume_extractions
from app.services.affinda_mapper import map_affinda_resume
from app.services.affinda_service import AffindaError, AffindaService
from app.services.storage_service import StorageService

logger = structlog.get_logger(__name__)


class ParsedTextNotFoundException(AppException):
    status_code = 400
    error_code = "PARSED_TEXT_NOT_FOUND"
    default_message = "The document must be parsed before information extraction."


class ExtractionFailedException(AppException):
    status_code = 500
    error_code = "EXTRACTION_FAILED"
    default_message = "Information extraction failed."


class ExtractedDataNotFoundException(AppException):
    status_code = 404
    error_code = "EXTRACTED_DATA_NOT_FOUND"
    default_message = "No extracted data exists for this document."


class ExtractionService:
    """Coordinate deterministic Stage 3 extraction and persistence."""

    def __init__(
        self,
        document_repository: DocumentRepository,
        parsed_repository: ParsedDocumentRepository,
        extraction_repository: ExtractionRepository,
        ai_resume_extractor: AIResumeExtractor | None = None,
        affinda_service: AffindaService | None = None,
        storage: StorageService | None = None,
    ) -> None:
        self.document_repository = document_repository
        self.parsed_repository = parsed_repository
        self.extraction_repository = extraction_repository
        self.ai_resume_extractor = ai_resume_extractor or AIResumeExtractor()
        self.affinda_service = affinda_service or AffindaService()
        self.storage = storage or StorageService()

    async def extract_document_data(self, document_id: UUID) -> ExtractDocumentResponse:
        total_started = perf_counter()
        document = await self._get_document(document_id)
        try:
            parsed = await self.parsed_repository.get_by_document_id(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve parsed text.") from exc
        if parsed is None or not parsed.normalized_text.strip():
            raise ParsedTextNotFoundException()

        try:
            await self.document_repository.update_processing(
                document_id, ProcessingStage.EXTRACTION, ProcessingStatus.IN_PROGRESS,
                document=document, refresh=False,
            )
            extraction_started = perf_counter()
            ai_duration_ms = 0.0
            if document.document_type == DocumentTypeEnum.RESUME:
                extracted = await self._affinda_resume(document, parsed.normalized_text)
                if extracted is None:
                    deterministic = ResumeExtractor().extract(parsed.normalized_text)
                    ai_extracted = None
                    try:
                        ai_started = perf_counter()
                        ai_extracted = await self.ai_resume_extractor.extract(parsed.normalized_text)
                        ai_duration_ms = (perf_counter() - ai_started) * 1000
                    except Exception as exc:
                        ai_duration_ms = (perf_counter() - ai_started) * 1000
                        logger.warning(
                            "ai_resume_extraction_skipped",
                            document_id=str(document_id),
                            error_type=type(exc).__name__,
                        )
                    extracted = merge_resume_extractions(deterministic, ai_extracted)
                else:
                    deterministic = ResumeExtractor().extract(parsed.normalized_text)
                    from app.services.extractors.resume_merge import merge_resume_extractions
                    extracted = merge_resume_extractions(deterministic, extracted)
                await self.extraction_repository.create_or_update_resume(
                    ExtractedResumeCreate(document_id=document_id, **extracted),
                    commit=False, refresh=False,
                )
            else:
                extracted = JobDescriptionExtractor().extract(parsed.normalized_text)
                await self.extraction_repository.create_or_update_job_description(
                    ExtractedJobDescriptionCreate(document_id=document_id, **extracted),
                    commit=False, refresh=False,
                )
            await self.document_repository.update_processing(
                document_id, ProcessingStage.COMPLETED, ProcessingStatus.COMPLETED,
                document=document, refresh=False,
            )
            extraction_duration_ms = (perf_counter() - extraction_started) * 1000
        except AppException as exc:
            await self._mark_failed(document_id, exc.message)
            raise
        except Exception as exc:
            await self._mark_failed(document_id, "Information extraction failed.")
            raise ExtractionFailedException() from exc

        logger.info(
            "document_information_extracted", document_id=str(document_id),
            ai_duration_ms=round(ai_duration_ms, 2),
            extraction_and_persistence_ms=round(extraction_duration_ms, 2),
            duration_ms=round((perf_counter() - total_started) * 1000, 2),
        )
        return ExtractDocumentResponse(
            document_id=document_id,
            document_type=DocumentType(document.document_type.value),
            processing_stage=ProcessingStage.COMPLETED,
            message="Information extracted successfully.",
        )

    async def _affinda_resume(
        self, document: DocumentModel, source_text: str | None = None
    ) -> dict | None:
        if not self.affinda_service.configured:
            return None
        try:
            payload = (getattr(document, "metadata_json", None) or {}).get(
                "affinda_payload"
            )
            if not isinstance(payload, dict):
                file_path = getattr(document, "file_path", None)
                path = self.storage.resolve_file(file_path) if file_path else None
                if path is None:
                    raise AffindaError("Stored document is unavailable.")
                payload = await self.affinda_service.parse_resume(
                    path, document.original_filename, document.mime_type
                )
            meta = payload.get("meta") or {}
            extracted, _ = map_affinda_resume(
                payload["data"], meta.get("identifier"), source_text
            )
            logger.info(
                "affinda_resume_succeeded",
                document_id=str(getattr(document, "id", "unknown")),
            )
            return extracted
        except Exception as exc:
            logger.warning(
                "affinda_resume_fallback",
                document_id=str(getattr(document, "id", "unknown")),
                error_type=type(exc).__name__,
            )
            return None

    async def get_extracted_data(
        self, document_id: UUID
    ) -> ExtractedResumeRead | ExtractedJobDescriptionRead:
        document = await self._get_document(document_id)
        try:
            if document.document_type == DocumentTypeEnum.RESUME:
                model = await self.extraction_repository.get_resume_by_document_id(document_id)
                if model is None:
                    raise ExtractedDataNotFoundException()
                return ExtractedResumeRead.model_validate(model)
            model = await self.extraction_repository.get_job_description_by_document_id(document_id)
            if model is None:
                raise ExtractedDataNotFoundException()
            return ExtractedJobDescriptionRead.model_validate(model)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve extracted data.") from exc

    async def _get_document(self, document_id: UUID) -> DocumentModel:
        try:
            document = await self.document_repository.get_document(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve document.") from exc
        if document is None:
            raise DocumentNotFoundException()
        return document

    async def _mark_failed(self, document_id: UUID, message: str) -> None:
        try:
            await self.document_repository.session.rollback()
        except Exception:
            pass
        try:
            await self.document_repository.update_processing(
                document_id, ProcessingStage.FAILED, ProcessingStatus.FAILED,
                error_message=message[:2000],
            )
        except SQLAlchemyError:
            logger.exception("extraction_failed_status_update_failed", document_id=str(document_id))
