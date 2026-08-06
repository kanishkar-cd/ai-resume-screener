import math
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from uuid import UUID

import structlog
from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.exceptions import (
    AppException,
    ConflictException,
    InternalServerException,
)
from app.models.document import DocumentModel
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
    ProcessingStatus,
    SortOrder,
)
from app.services.project_service import ProjectNotFoundException
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


class DocumentFileMissingException(AppException):
    status_code = 404
    error_code = "DOCUMENT_FILE_MISSING"
    default_message = "The stored document file could not be found."


@dataclass(frozen=True, slots=True)
class DocumentDownload:
    path: Path
    filename: str
    mime_type: str


class DocumentService:
    """Coordinate validation, project ownership, storage, and persistence."""

    def __init__(
        self,
        repository: DocumentRepository,
        project_repository: ProjectRepository,
        storage: StorageService,
    ) -> None:
        self.repository = repository
        self.project_repository = project_repository
        self.storage = storage

    async def upload_document(
        self,
        project_id: UUID,
        document_type: DocumentType,
        file: UploadFile,
    ) -> DocumentUploadRead:
        started_at = perf_counter()
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
            if await self.repository.get_by_hash(file_hash) is not None:
                self.storage.delete_file(file_path)
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
        except DuplicateDocumentException:
            raise
        except IntegrityError as exc:
            await self.repository.session.rollback()
            self.storage.delete_file(file_path)
            raise DuplicateDocumentException() from exc
        except SQLAlchemyError as exc:
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
        await self._verify_project(project_id)
        original_filename, extension = await validate_file(file)
        stored_filename, file_path, size, file_hash = await self.storage.save_file(
            file, project_id, "job_description", extension
        )
        existing = None
        try:
            duplicate = await self.repository.get_by_hash(file_hash)
            if duplicate is not None:
                self.storage.delete_file(file_path)
                raise DuplicateDocumentException()
            existing = await self.repository.soft_delete_project_job_description(
                project_id
            )
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
                    await self.upload_document(project_id, DocumentType.RESUME, file)
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
        await self._verify_project(project_id)
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
        if document is None:
            raise DocumentNotFoundException()
        await self._verify_project(document.project_id)
        return DocumentRead.model_validate(document)

    async def download_document(self, document_id: UUID) -> DocumentDownload:
        try:
            document = await self.repository.download_document(document_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve document.") from exc
        if document is None:
            raise DocumentNotFoundException()
        await self._verify_project(document.project_id)
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
        if document is None:
            raise DocumentNotFoundException()
        await self._verify_project(document.project_id)
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
