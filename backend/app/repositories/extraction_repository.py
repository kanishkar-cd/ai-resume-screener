from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extracted_info import ExtractedResumeModel
from app.models.extracted_job_description import ExtractedJDModel
from app.schemas.extracted_info import (
    ExtractedJobDescriptionCreate,
    ExtractedResumeCreate,
)


class ExtractionRepository:
    """Async upsert and retrieval operations for Stage 3 entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_or_update_resume(
        self, data: ExtractedResumeCreate | dict[str, Any], *, commit: bool = True, refresh: bool = True
    ) -> ExtractedResumeModel:
        payload = ExtractedResumeCreate.model_validate(data).model_dump(mode="json")
        document_id = UUID(payload["document_id"])
        payload["document_id"] = document_id
        model = await self.get_resume_by_document_id(document_id)
        model = self._apply(model, ExtractedResumeModel, payload)
        if commit:
            await self.session.commit()
        else:
            await self.session.flush()
        if refresh:
            await self.session.refresh(model)
        return model

    async def create_or_update_job_description(
        self, data: ExtractedJobDescriptionCreate | dict[str, Any], *, commit: bool = True, refresh: bool = True
    ) -> ExtractedJDModel:
        payload = ExtractedJobDescriptionCreate.model_validate(data).model_dump(mode="json")
        document_id = UUID(payload["document_id"])
        payload["document_id"] = document_id
        model = await self.get_job_description_by_document_id(document_id)
        model = self._apply(model, ExtractedJDModel, payload)
        if commit:
            await self.session.commit()
        else:
            await self.session.flush()
        if refresh:
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
    ) -> ExtractedJDModel | None:
        return await self.session.scalar(
            select(ExtractedJDModel).where(
                ExtractedJDModel.document_id == document_id
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
