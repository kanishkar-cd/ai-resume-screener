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
        metadata: dict[str, object] | None = None,
        *,
        commit: bool = True,
    ) -> DocumentModel | None:
        document = await self.get_document(document_id)
        if document is None:
            return None
        document.processing_status = ProcessingStatusEnum(status.value)
        if metadata is not None:
            document.metadata_json = metadata
        if commit:
            await self.session.commit()
            await self.session.refresh(document)
        else:
            await self.session.flush()
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
