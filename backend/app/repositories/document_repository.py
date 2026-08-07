from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import (
    DocumentModel,
    DocumentTypeEnum,
    ProcessingStageEnum,
    ProcessingStatusEnum,
)
from app.schemas.document import (
    DocumentCreate,
    DocumentType,
    ProcessingStatus,
    SortOrder,
    ProcessingStage,
)


class DocumentRepository:
    """Async persistence operations for project documents."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, document: DocumentCreate) -> DocumentModel:
        values = document.model_dump()
        values["document_type"] = DocumentTypeEnum(values["document_type"])
        values["processing_stage"] = ProcessingStageEnum(values["processing_stage"])
        values["processing_status"] = ProcessingStatusEnum(
            values["processing_status"]
        )
        model = DocumentModel(**values)
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return model

    async def get_by_hash(self, file_hash: str) -> DocumentModel | None:
        statement = select(DocumentModel).where(
            DocumentModel.file_hash == file_hash,
            DocumentModel.deleted_at.is_(None),
        )
        return await self.session.scalar(statement)

    async def get_job_description_by_project(
        self, project_id: UUID
    ) -> DocumentModel | None:
        return await self.session.scalar(
            select(DocumentModel)
            .where(
                DocumentModel.project_id == project_id,
                DocumentModel.document_type == DocumentTypeEnum.JOB_DESCRIPTION,
                DocumentModel.deleted_at.is_(None),
            )
            .order_by(DocumentModel.created_at.desc())
        )

    async def list_resumes_by_project(
        self,
        project_id: UUID,
        page: int,
        page_size: int,
        *,
        status: ProcessingStatus | None = None,
        search: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[DocumentModel], int]:
        return await self.list_documents(
            DocumentType.RESUME,
            status,
            page,
            page_size,
            project_id=project_id,
            search=search,
            sort_order=sort_order,
        )

    async def soft_delete_project_job_description(
        self, project_id: UUID
    ) -> DocumentModel | None:
        document = await self.get_job_description_by_project(project_id)
        if document is None:
            return None
        document.deleted_at = datetime.now(UTC)
        await self.session.commit()
        return document

    async def restore_document(self, document_id: UUID) -> DocumentModel | None:
        document = await self.session.get(DocumentModel, document_id)
        if document is None:
            return None
        document.deleted_at = None
        await self.session.commit()
        await self.session.refresh(document)
        return document

    async def get_document(self, document_id: UUID) -> DocumentModel | None:
        statement = select(DocumentModel).where(
            DocumentModel.id == document_id,
            DocumentModel.deleted_at.is_(None),
        )
        return await self.session.scalar(statement)

    async def get_by_id(self, document_id: UUID) -> DocumentModel | None:
        """Backward-compatible active document lookup."""
        return await self.get_document(document_id)

    async def download_document(self, document_id: UUID) -> DocumentModel | None:
        """Return active metadata needed to resolve a physical download."""
        return await self.get_document(document_id)

    async def list_documents(
        self,
        document_type: DocumentType | None,
        status: ProcessingStatus | None,
        page: int,
        page_size: int,
        *,
        project_id: UUID | None = None,
        search: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[DocumentModel], int]:
        filters = [DocumentModel.deleted_at.is_(None)]
        if project_id is not None:
            filters.append(DocumentModel.project_id == project_id)
        if document_type is not None:
            filters.append(
                DocumentModel.document_type == DocumentTypeEnum(document_type.value)
            )
        if status is not None:
            filters.append(
                DocumentModel.processing_status
                == ProcessingStatusEnum(status.value)
            )
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            filters.append(
                DocumentModel.original_filename.ilike(f"%{escaped}%", escape="\\")
            )
        total = await self.session.scalar(
            select(func.count()).select_from(DocumentModel).where(*filters)
        )
        order_column = (
            DocumentModel.created_at.asc()
            if sort_order == SortOrder.ASC
            else DocumentModel.created_at.desc()
        )
        result = await self.session.scalars(
            select(DocumentModel)
            .where(*filters)
            .order_by(order_column)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.all()), int(total or 0)

    async def update_status(
        self,
        document_id: UUID,
        status: ProcessingStatus,
        metadata: dict[str, object],
    ) -> DocumentModel | None:
        document = await self.get_document(document_id)
        if document is None:
            return None
        document.processing_status = ProcessingStatusEnum(status.value)
        document.metadata_json = metadata
        await self.session.commit()
        await self.session.refresh(document)
        return document

    async def update_processing(
        self,
        document_id: UUID,
        stage: ProcessingStage,
        status: ProcessingStatus,
        error_message: str | None = None,
    ) -> DocumentModel | None:
        """Persist Stage 2 processing state for an active document."""
        document = await self.get_document(document_id)
        if document is None:
            return None
        document.processing_stage = ProcessingStageEnum(stage.value)
        document.processing_status = ProcessingStatusEnum(status.value)
        document.error_message = error_message
        await self.session.commit()
        await self.session.refresh(document)
        return document

    async def delete_document(
        self, document_id: UUID, *, commit: bool = True
    ) -> DocumentModel | None:
        """Mark an active document deleted, optionally leaving commit to its service."""
        document = await self.get_document(document_id)
        if document is None:
            return None
        document.deleted_at = datetime.now(UTC)
        if commit:
            await self.session.commit()
        else:
            await self.session.flush()
        return document

    async def soft_delete(self, document_id: UUID) -> bool:
        """Backward-compatible soft-delete helper."""
        return await self.delete_document(document_id) is not None
