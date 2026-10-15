import asyncio
import math
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID

import structlog
from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.exceptions import (
    AppException,
    ConflictException,
    InternalServerException,
)
from app.models.document import (
    DocumentModel,
    DocumentTypeEnum,
    ProcessingStageEnum,
    ProcessingStatusEnum,
)
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.document import (
    BatchResumeUploadRead,
    DocumentCreate,
    DocumentPaginatedResponse,
    DocumentRead,
    DocumentType,
    DocumentUploadRead,
    FailedUploadItem,
    ProcessingStage,
    ProcessingStatus,
    ResumeRetryRead,
    SortOrder,
)
from app.services.project_service import ProjectNotFoundException
from app.services.redis_service import RedisService
from app.services.storage_service import StorageService
from app.utils.file_validation import validate_batch, validate_file

logger = structlog.get_logger(__name__)


class DuplicateDocumentException(ConflictException):
    error_code = "DUPLICATE_DOCUMENT"
    default_message = "This document has already been uploaded."


class DocumentNotFoundException(AppException):
    status_code = 404
    error_code = "DOCUMENT_NOT_FOUND"
    default_message = "The requested document was not found."


class DocumentBelongsToAnotherProjectException(AppException):
    status_code = 400
    error_code = "DOCUMENT_PROJECT_MISMATCH"
    default_message = "The document does not belong to the specified project."


class DocumentFileMissingException(AppException):
    status_code = 404
    error_code = "DOCUMENT_FILE_MISSING"
    default_message = "The stored document file could not be found."


class DocumentRetryInProgressException(ConflictException):
    error_code = "DOCUMENT_RETRY_IN_PROGRESS"
    default_message = "Document retry is already in progress."


class DocumentNotRetryableException(ConflictException):
    error_code = "DOCUMENT_NOT_RETRYABLE"
    default_message = "Only failed or incomplete documents can be retried."


_active_retries: set[UUID] = set()
_retry_lock = asyncio.Lock()


@dataclass(frozen=True, slots=True)
class DocumentDownload:
    path: Path
    filename: str
    mime_type: str


class DocumentService:
    def __init__(
        self,
        repository: DocumentRepository,
        project_repository: ProjectRepository,
        storage: StorageService,
        redis: RedisService | None = None,
    ) -> None:
        self.repository = repository
        self.project_repository = project_repository
        self.storage = storage
        self.redis = redis or RedisService()


    async def upload_document(
        self,
        project_id: UUID,
        document_type: DocumentType,
        file: UploadFile,
        *,
        verify_project: bool = True,
        commit: bool = True,
    ) -> DocumentUploadRead:
        started_at = perf_counter()
        if verify_project:
            try:
                project = await self.project_repository.get_by_id(project_id)
            except SQLAlchemyError as exc:
                raise InternalServerException("Unable to verify project ownership.") from exc
            if project is None:
                raise ProjectNotFoundException()

        original_filename, extension = await validate_file(file)
        subfolder = (
            "resumes"
            if document_type == DocumentType.RESUME
            else "job_descriptions"
        )
        stored_filename, file_path, size, file_hash = await self.storage.save_file(
            file, project_id, subfolder, extension
        )

        try:
            if commit:
                if await self.repository.get_by_hash(project_id, file_hash, document_type) is not None:
                    raise DuplicateDocumentException()
                document = await self.repository.create(
                    DocumentCreate(
                        project_id=project_id,
                        document_type=document_type,
                        original_filename=original_filename,
                        stored_filename=stored_filename,
                        file_path=file_path,
                        file_size_bytes=size,
                        mime_type=file.content_type or "application/octet-stream",
                        file_hash=file_hash,
                    )
                )
            else:
                # Batch mode: isolate this file's insert in a SAVEPOINT so one bad
                # file (e.g. a rare concurrent-upload hash race) rolls back only
                # its own work, not documents already flushed earlier in the same
                # batch -- while still deferring the expensive physical COMMIT to
                # a single round trip at the end of the whole batch.
                async with self.repository.session.begin_nested():
                    if await self.repository.get_by_hash(project_id, file_hash, document_type) is not None:
                        raise DuplicateDocumentException()
                    document = await self.repository.create(
                        DocumentCreate(
                            project_id=project_id,
                            document_type=document_type,
                            original_filename=original_filename,
                            stored_filename=stored_filename,
                            file_path=file_path,
                            file_size_bytes=size,
                            mime_type=file.content_type or "application/octet-stream",
                            file_hash=file_hash,
                        ),
                        commit=False,
                        refresh=False,
                    )
        except DuplicateDocumentException:
            self.storage.delete_file(file_path)
            raise
        except IntegrityError as exc:
            if commit:
                await self.repository.session.rollback()
            self.storage.delete_file(file_path)
            raise DuplicateDocumentException() from exc
        except SQLAlchemyError as exc:
            if commit:
                await self.repository.session.rollback()
            self.storage.delete_file(file_path)
            raise InternalServerException("Unable to persist document metadata.") from exc

        logger.info(
            "document_uploaded_successfully",
            document_id=str(document.id),
            project_id=str(project_id),
            document_type=document_type.value,
            original_filename=original_filename,
            file_size_bytes=size,
            file_hash=file_hash,
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
        )
        return DocumentUploadRead(
            document_id=document.id,
            project_id=document.project_id,
            document_type=document.document_type.value,
            filename=document.original_filename,
            processing_stage=document.processing_stage.value,
            processing_status=document.processing_status.value,
        )

    @staticmethod
    def _upload_read(document: DocumentModel) -> DocumentUploadRead:
        return DocumentUploadRead(
            document_id=document.id,
            project_id=document.project_id,
            document_type=document.document_type.value,
            filename=document.original_filename,
            processing_stage=document.processing_stage.value,
            processing_status=document.processing_status.value,
        )

    async def upload_job_description(
        self, project_id: UUID, file: UploadFile
    ) -> DocumentUploadRead:
        """Upload a Job Description and replace the prior active one."""
        t_upload_start = perf_counter()

        t0 = perf_counter()
        await self._verify_project(project_id)
        t_verify = (perf_counter() - t0) * 1000
        logger.info("[UPLOAD_SUB_TIMING] Project verify DB query", duration_ms=round(t_verify, 2))

        t0 = perf_counter()
        original_filename, extension = await validate_file(file)
        t_val = (perf_counter() - t0) * 1000

        t0 = perf_counter()
        stored_filename, file_path, size, file_hash = await self.storage.save_file(
            file, project_id, "job_description", extension
        )
        t_save = (perf_counter() - t0) * 1000
        logger.info(
            "[UPLOAD_SUB_TIMING] File I/O validate and save to disk",
            validate_ms=round(t_val, 2),
            file_save_ms=round(t_save, 2),
            file_size_bytes=size,
        )

        existing = None
        try:
            t0 = perf_counter()
            duplicate = await self.repository.get_by_hash(
                project_id, file_hash, DocumentType.JOB_DESCRIPTION
            )
            t_hash = (perf_counter() - t0) * 1000
            logger.info("[UPLOAD_SUB_TIMING] Duplicate check DB query", duration_ms=round(t_hash, 2))

            if duplicate is not None:
                self.storage.delete_file(file_path)
                raise DuplicateDocumentException()

            t0 = perf_counter()
            existing = await self.repository.soft_delete_project_job_description(
                project_id
            )
            t_soft_del = (perf_counter() - t0) * 1000
            logger.info("[UPLOAD_SUB_TIMING] Soft-delete prior JD DB query & commit", duration_ms=round(t_soft_del, 2))

            t0 = perf_counter()
            document = await self.repository.create(
                DocumentCreate(
                    project_id=project_id,
                    document_type=DocumentType.JOB_DESCRIPTION,
                    original_filename=original_filename,
                    stored_filename=stored_filename,
                    file_path=file_path,
                    file_size_bytes=size,
                    mime_type=file.content_type or "application/octet-stream",
                    file_hash=file_hash,
                )
            )
            t_create = (perf_counter() - t0) * 1000
            logger.info("[UPLOAD_SUB_TIMING] Document create DB insert & commit", duration_ms=round(t_create, 2))
        except DuplicateDocumentException:
            raise
        except (IntegrityError, SQLAlchemyError) as exc:
            await self.repository.session.rollback()
            self.storage.delete_file(file_path)
            if existing is not None:
                await self.repository.restore_document(existing.id)
            raise InternalServerException(
                "Unable to replace project Job Description."
            ) from exc

        t_total_upload = (perf_counter() - t_upload_start) * 1000
        logger.info(
            "[UPLOAD_SUB_SUMMARY] upload_job_description complete breakdown",
            total_ms=round(t_total_upload, 2),
            verify_project_ms=round(t_verify, 2),
            file_validate_ms=round(t_val, 2),
            file_save_disk_ms=round(t_save, 2),
            duplicate_check_ms=round(t_hash, 2),
            soft_delete_prior_ms=round(t_soft_del, 2),
            document_create_ms=round(t_create, 2),
        )

        if existing is not None:
            try:
                self.storage.delete_file(existing.file_path)
            except Exception:
                logger.exception(
                    "replaced_job_description_file_cleanup_failed",
                    document_id=str(existing.id),
                    project_id=str(project_id),
                )
        return self._upload_read(document)

    async def get_job_description(self, project_id: UUID) -> DocumentRead:
        await self._verify_project(project_id)
        try:
            document = await self.repository.get_job_description_by_project(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException(
                "Unable to retrieve project Job Description."
            ) from exc
        if document is None:
            raise DocumentNotFoundException("Project Job Description was not found.")
        return DocumentRead.model_validate(document)

    async def upload_resume_batch(
        self, project_id: UUID, files: list[UploadFile]
    ) -> BatchResumeUploadRead:
        await self._verify_project(project_id)
        await validate_batch(files)
        successful: list[DocumentUploadRead] = []
        failed: list[FailedUploadItem] = []
        for file in files:
            try:
                successful.append(
                    await self.upload_document(
                        project_id, DocumentType.RESUME, file, verify_project=False, commit=False
                    )
                )
            except AppException as exc:
                failed.append(
                    FailedUploadItem(
                        original_filename=Path(file.filename or "unknown").name,
                        error_code=exc.error_code,
                        message=exc.message,
                    )
                )
            except Exception:
                logger.exception(
                    "resume_batch_item_failed",
                    project_id=str(project_id),
                    original_filename=Path(file.filename or "unknown").name,
                )
                failed.append(
                    FailedUploadItem(
                        original_filename=Path(file.filename or "unknown").name,
                        error_code="SYSTEM_ERROR",
                        message="The resume could not be uploaded.",
                    )
                )
        if successful:
            t0 = perf_counter()
            await self.repository.session.commit()
            logger.info(
                "[DB_DOCUMENT_TIMING] upload_resume_batch() single batched commit",
                successful_count=len(successful),
                commit_ms=round((perf_counter() - t0) * 1000, 2),
            )
        return BatchResumeUploadRead(
            project_id=project_id,
            total_received=len(files),
            successful_count=len(successful),
            failed_count=len(failed),
            successful_uploads=successful,
            failed_uploads=failed,
        )

    async def list_project_resumes(
        self,
        project_id: UUID,
        processing_status: ProcessingStatus | None,
        search: str | None,
        page: int,
        page_size: int,
        sort_order: SortOrder,
    ) -> DocumentPaginatedResponse:
        try:
            documents, total = await self.repository.list_resumes_by_project(
                project_id,
                page,
                page_size,
                status=processing_status,
                search=search.strip() if search else None,
                sort_order=sort_order,
            )
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to list project resumes.") from exc
        return DocumentPaginatedResponse(
            items=[DocumentRead.model_validate(document) for document in documents],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size),
        )

    async def _verify_project(self, project_id: UUID) -> None:
        try:
            project = await self.project_repository.get_by_id(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to verify project.") from exc
        if project is None:
            raise ProjectNotFoundException()

    async def list_documents(
        self,
        project_id: UUID | None,
        document_type: DocumentType | None,
        processing_status: ProcessingStatus | None,
        search: str | None,
        page: int,
        page_size: int,
        sort_order: SortOrder,
    ) -> DocumentPaginatedResponse:
        if project_id is not None:
            await self._verify_project(project_id)
        normalized_search = search.strip() if search else None
        try:
            documents, total = await self.repository.list_documents(
                document_type,
                processing_status,
                page,
                page_size,
                project_id=project_id,
                search=normalized_search,
                sort_order=sort_order,
            )
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to list documents.") from exc
        return DocumentPaginatedResponse(
            items=[DocumentRead.model_validate(document) for document in documents],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size),
        )

    async def get_document(self, document_id: UUID) -> DocumentRead:
        try:
            document = await self.repository.get_document(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve document.") from exc
        if document is None or document.deleted_at is not None:
            raise DocumentNotFoundException()
        return DocumentRead.model_validate(document)

    async def download_document(self, document_id: UUID) -> DocumentDownload:
        try:
            document = await self.repository.download_document(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve document.") from exc
        if document is None or document.deleted_at is not None:
            raise DocumentNotFoundException()
        path = self.storage.resolve_file(document.file_path)
        if path is None:
            raise DocumentFileMissingException()
        return DocumentDownload(
            path=path,
            filename=document.original_filename,
            mime_type=document.mime_type,
        )

    async def delete_document(self, document_id: UUID) -> None:
        try:
            document = await self.repository.get_document(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve document.") from exc
        if document is None or document.deleted_at is not None:
            raise DocumentNotFoundException()
        if self.storage.resolve_file(document.file_path) is None:
            raise DocumentFileMissingException()

        try:
            deleted = await self.repository.delete_document(document_id, commit=False)
            if deleted is None:
                raise DocumentNotFoundException()
            if not self.storage.delete_file(document.file_path):
                raise DocumentFileMissingException()
            await self.repository.session.commit()
        except (DocumentNotFoundException, DocumentFileMissingException):
            await self.repository.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.repository.session.rollback()
            raise InternalServerException("Unable to delete document.") from exc
        except Exception:
            await self.repository.session.rollback()
            raise

        logger.info(
            "document_deleted_successfully",
            document_id=str(document_id),
            project_id=str(document.project_id),
        )

    async def delete_resume(self, project_id: UUID, document_id: UUID) -> None:
        """Validate ownership, cascade-delete pipeline data, and remove physical file for a resume."""
        await self._verify_project(project_id)

        try:
            document = await self.repository.get_by_id(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve document.") from exc

        if document is None or document.deleted_at is not None:
            raise DocumentNotFoundException("The requested resume was not found.")

        if document.project_id != project_id:
            raise DocumentBelongsToAnotherProjectException()

        if document.document_type != DocumentTypeEnum.RESUME:
            raise DocumentNotFoundException("The requested document is not a resume.")

        if document_id in _active_retries:
            raise DocumentRetryInProgressException("Cannot delete resume while retry is in progress.")

        try:
            await self.repository.cleanup_pipeline_data(document_id, DocumentType.RESUME)
            deleted = await self.repository.delete_document(document_id, commit=False)
            if deleted is None:
                raise DocumentNotFoundException()
            await self.repository.session.commit()
        except (DocumentNotFoundException, DocumentBelongsToAnotherProjectException):
            await self.repository.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.repository.session.rollback()
            raise InternalServerException("Unable to delete resume records.") from exc
        except Exception:
            await self.repository.session.rollback()
            raise

        try:
            self.storage.delete_file(document.file_path)
        except Exception:
            logger.exception(
                "resume_file_cleanup_failed",
                document_id=str(document_id),
                project_id=str(project_id),
            )

        logger.info(
            "resume_deleted_successfully",
            document_id=str(document_id),
            project_id=str(project_id),
        )

    async def delete_job_description(self, project_id: UUID) -> None:
        """Validate ownership, cascade-delete pipeline data, and remove physical file for active Job Description."""
        await self._verify_project(project_id)

        try:
            document = await self.repository.get_job_description_by_project(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve project Job Description.") from exc

        if document is None:
            raise DocumentNotFoundException("Project Job Description was not found.")

        try:
            await self.repository.cleanup_pipeline_data(document.id, DocumentType.JOB_DESCRIPTION)
            deleted = await self.repository.delete_document(document.id, commit=False)
            if deleted is None:
                raise DocumentNotFoundException()
            await self.repository.session.commit()
        except DocumentNotFoundException:
            await self.repository.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.repository.session.rollback()
            raise InternalServerException("Unable to delete Job Description records.") from exc
        except Exception:
            await self.repository.session.rollback()
            raise

        try:
            self.storage.delete_file(document.file_path)
        except Exception:
            logger.exception(
                "job_description_file_cleanup_failed",
                document_id=str(document.id),
                project_id=str(project_id),
            )

        logger.info(
            "job_description_deleted_successfully",
            document_id=str(document.id),
            project_id=str(project_id),
        )

    async def retry_resume(
        self,
        project_id: UUID,
        document_id: UUID,
        *,
        parsing_service: Any = None,
        extraction_service: Any = None,
        normalization_service: Any = None,
    ) -> ResumeRetryRead:
        """Validate ownership, clear stale pipeline data, and safely rerun parsing -> extraction -> normalization."""
        await self._verify_project(project_id)

        try:
            document = await self.repository.get_by_id(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve document.") from exc

        if document is None or document.deleted_at is not None:
            raise DocumentNotFoundException("The requested resume was not found.")

        if document.project_id != project_id:
            raise DocumentBelongsToAnotherProjectException()

        if document.document_type != DocumentTypeEnum.RESUME:
            raise DocumentNotFoundException("The requested document is not a resume.")

        doc_status = getattr(document, "processing_status", None)
        status_val = getattr(doc_status, "value", str(doc_status)) if doc_status is not None else None
        doc_stage = getattr(document, "processing_stage", None)
        stage_val = getattr(doc_stage, "value", str(doc_stage)) if doc_stage is not None else None

        if status_val == "COMPLETED" and stage_val == "COMPLETED":
            raise DocumentNotRetryableException()

        async with _retry_lock:
            if document_id in _active_retries or status_val == "IN_PROGRESS":
                raise DocumentRetryInProgressException()
            _active_retries.add(document_id)

        try:
            # 1. Clean up downstream records from previous failed/partial attempts
            await self.repository.cleanup_pipeline_data(document_id, DocumentType.RESUME)

            # 2. Reset processing status and clear error
            document.error_message = None
            document.processing_stage = ProcessingStageEnum.PARSING
            document.processing_status = ProcessingStatusEnum.IN_PROGRESS
            await self.repository.session.commit()

            # 3. Instantiate pipeline services if not injected
            if parsing_service is None:
                from app.repositories.parsed_document_repository import ParsedDocumentRepository
                from app.services.parsing_service import ParsingService
                parsing_service = ParsingService(
                    self.repository,
                    ParsedDocumentRepository(self.repository.session),
                    self.storage,
                )

            if extraction_service is None:
                from app.repositories.extraction_repository import ExtractionRepository
                from app.repositories.parsed_document_repository import ParsedDocumentRepository
                from app.services.extraction_service import ExtractionService
                extraction_service = ExtractionService(
                    self.repository,
                    ParsedDocumentRepository(self.repository.session),
                    ExtractionRepository(self.repository.session),
                )

            if normalization_service is None:
                from app.repositories.extraction_repository import ExtractionRepository
                from app.repositories.normalization_repository import NormalizationRepository
                from app.services.normalization_service import NormalizationService
                normalization_service = NormalizationService(
                    self.repository,
                    ExtractionRepository(self.repository.session),
                    NormalizationRepository(self.repository.session),
                )

            # 4. Sequentially execute stages: Parsing -> Extraction -> Normalization
            await parsing_service.parse_document(document_id, force=True)
            await extraction_service.extract_document_data(document_id, force=True)
            await normalization_service.normalize_document_data(document_id, force=True)

            try:
                await self.repository.session.refresh(document)
            except Exception:
                pass

            logger.info(
                "resume_retried_successfully",
                document_id=str(document_id),
                project_id=str(project_id),
                stage=str(getattr(document, "processing_stage", None)),
                status=str(getattr(document, "processing_status", None)),
            )

            stage_out = (
                ProcessingStage(document.processing_stage.value)
                if hasattr(document.processing_stage, "value")
                else ProcessingStage(str(document.processing_stage))
            )
            status_out = (
                ProcessingStatus(document.processing_status.value)
                if hasattr(document.processing_status, "value")
                else ProcessingStatus(str(document.processing_status))
            )

            return ResumeRetryRead(
                document_id=document.id,
                project_id=document.project_id,
                document_type=DocumentType.RESUME,
                filename=document.original_filename,
                processing_stage=stage_out,
                processing_status=status_out,
                message="Resume retried and processed successfully.",
            )
        finally:
            async with _retry_lock:
                _active_retries.discard(document_id)

