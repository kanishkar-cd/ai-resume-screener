from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extracted_info import (
    ExtractedJobDescriptionModel,
    ExtractedResumeModel,
)
from app.schemas.extracted_info import (
    ExtractedJobDescriptionCreate,
    ExtractedResumeCreate,
)


class ExtractionRepository:
    """Async upsert and retrieval operations for Stage 3 entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_or_update_resume(
        self, data: ExtractedResumeCreate | dict[str, Any]
    ) -> ExtractedResumeModel:
        payload = ExtractedResumeCreate.model_validate(data).model_dump(mode="json")
        document_id = UUID(payload["document_id"])
        payload["document_id"] = document_id
        model = await self.get_resume_by_document_id(document_id)
        model = self._apply(model, ExtractedResumeModel, payload)
        await self.session.commit()
        await self.session.refresh(model)
        return model

    async def create_or_update_job_description(
        self, data: ExtractedJobDescriptionCreate | dict[str, Any]
    ) -> ExtractedJobDescriptionModel:
        payload = ExtractedJobDescriptionCreate.model_validate(data).model_dump(mode="json")
        document_id = UUID(payload["document_id"])
        payload["document_id"] = document_id
        model = await self.get_job_description_by_document_id(document_id)
        model = self._apply(model, ExtractedJobDescriptionModel, payload)
        await self.session.commit()
        await self.session.refresh(model)
        return model

    async def get_resume_by_document_id(
        self, document_id: UUID
    ) -> ExtractedResumeModel | None:
        return await self.session.scalar(
            select(ExtractedResumeModel).where(
                ExtractedResumeModel.document_id == document_id
            )
        )

    async def get_job_description_by_document_id(
        self, document_id: UUID
    ) -> ExtractedJobDescriptionModel | None:
        return await self.session.scalar(
            select(ExtractedJobDescriptionModel).where(
                ExtractedJobDescriptionModel.document_id == document_id
            )
        )

    def _apply(self, model: Any, model_type: type[Any], payload: dict[str, Any]) -> Any:
        if model is None:
            model = model_type(**payload)
            self.session.add(model)
            return model
        payload.pop("document_id", None)
        for field, value in payload.items():
            setattr(model, field, value)
        return model
