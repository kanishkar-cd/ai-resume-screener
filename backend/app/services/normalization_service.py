from uuid import UUID
from time import perf_counter

import structlog
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppException, InternalServerException
from app.models.document import DocumentModel, DocumentTypeEnum
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.normalization_repository import NormalizationRepository
from app.schemas.document import DocumentType, ProcessingStage, ProcessingStatus
from app.schemas.normalized_info import (
    NormalizeDocumentResponse, NormalizedJobDescriptionCreate,
    NormalizedJobDescriptionRead, NormalizedResumeCreate, NormalizedResumeRead,
)
from app.services.document_service import DocumentNotFoundException
from app.services.normalizers import JobDescriptionNormalizer, ResumeNormalizer
from app.services.pipeline.canonical_dictionaries import RULESET_VERSION

logger = structlog.get_logger(__name__)


class ExtractedDataNotFoundException(AppException):
    status_code = 400
    error_code = "EXTRACTED_DATA_NOT_FOUND"
    default_message = "The document must be extracted before normalization."


class NormalizedDataNotFoundException(AppException):
    status_code = 404
    error_code = "NORMALIZED_DATA_NOT_FOUND"
    default_message = "No normalized data exists for this document."


class UnsupportedNormalizationTypeException(AppException):
    status_code = 422
    error_code = "UNSUPPORTED_NORMALIZATION_TYPE"
    default_message = "The document type cannot be normalized."


class NormalizationValidationException(AppException):
    status_code = 422
    error_code = "NORMALIZATION_VALIDATION_FAILED"
    default_message = "Canonical data failed validation."


class NormalizationFailedException(AppException):
    status_code = 500
    error_code = "NORMALIZATION_FAILED"
    default_message = "Document data normalization failed."


class NormalizationService:
    def __init__(self, documents: DocumentRepository, extractions: ExtractionRepository, normalizations: NormalizationRepository) -> None:
        self.documents = documents
        self.extractions = extractions
        self.normalizations = normalizations

    async def normalize_document_data(self, document_id: UUID) -> NormalizeDocumentResponse:
        started_at = perf_counter()
        document = await self._get_document(document_id)
        extracted = await self._get_extracted(document)
        try:
            await self.documents.update_processing(
                document_id, ProcessingStage.NORMALIZATION, ProcessingStatus.IN_PROGRESS,
                document=document, refresh=False,
            )
            if document.document_type == DocumentTypeEnum.RESUME:
                values = ResumeNormalizer().normalize(extracted)
                await self.normalizations.create_or_update_resume(
                    NormalizedResumeCreate(document_id=document_id, extracted_resume_id=extracted.id, **values),
                    commit=False, refresh=False,
                )
            elif document.document_type == DocumentTypeEnum.JOB_DESCRIPTION:
                values = JobDescriptionNormalizer().normalize(extracted)
                await self.normalizations.create_or_update_job_description(
                    NormalizedJobDescriptionCreate(document_id=document_id, extracted_job_description_id=extracted.id, **values),
                    commit=False, refresh=False,
                )
            else:
                raise UnsupportedNormalizationTypeException()
            await self.documents.update_processing(
                document_id, ProcessingStage.COMPLETED, ProcessingStatus.COMPLETED,
                document=document, refresh=False,
            )
        except ValidationError as exc:
            await self._mark_failed(document_id, "Canonical data failed validation.")
            raise NormalizationValidationException(details={"errors": exc.errors(include_url=False)}) from exc
        except AppException as exc:
            await self._mark_failed(document_id, exc.message)
            raise
        except Exception as exc:
            await self._mark_failed(document_id, "Document data normalization failed.")
            raise NormalizationFailedException() from exc
        logger.info(
            "document_data_normalized", document_id=str(document_id),
            ruleset_version=RULESET_VERSION,
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
        )
        return NormalizeDocumentResponse(
            document_id=document_id, document_type=DocumentType(document.document_type.value),
            processing_stage=ProcessingStage.COMPLETED, ruleset_version=RULESET_VERSION,
            message="Document data normalized successfully.",
        )

    async def get_normalized_data(self, document_id: UUID) -> NormalizedResumeRead | NormalizedJobDescriptionRead:
        document = await self._get_document(document_id)
        try:
            if document.document_type == DocumentTypeEnum.RESUME:
                model = await self.normalizations.get_resume_by_document_id(document_id)
                if model is None: raise NormalizedDataNotFoundException()
                return NormalizedResumeRead.model_validate(model)
            if document.document_type == DocumentTypeEnum.JOB_DESCRIPTION:
                model = await self.normalizations.get_job_description_by_document_id(document_id)
                if model is None: raise NormalizedDataNotFoundException()
                return NormalizedJobDescriptionRead.model_validate(model)
            raise UnsupportedNormalizationTypeException()
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve normalized data.") from exc

    async def _get_document(self, document_id: UUID) -> DocumentModel:
        try:
            document = await self.documents.get_document(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve document.") from exc
        if document is None: raise DocumentNotFoundException()
        return document

    async def _get_extracted(self, document: DocumentModel):
        try:
            if document.document_type == DocumentTypeEnum.RESUME:
                extracted = await self.extractions.get_resume_by_document_id(document.id)
            elif document.document_type == DocumentTypeEnum.JOB_DESCRIPTION:
                extracted = await self.extractions.get_job_description_by_document_id(document.id)
            else:
                raise UnsupportedNormalizationTypeException()
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve extracted data.") from exc
        if extracted is None: raise ExtractedDataNotFoundException()
        return extracted

    async def _mark_failed(self, document_id: UUID, message: str) -> None:
        try:
            await self.documents.update_processing(document_id, ProcessingStage.FAILED, ProcessingStatus.FAILED, error_message=message[:2000])
        except SQLAlchemyError:
            logger.exception("normalization_failed_status_update_failed", document_id=str(document_id))
