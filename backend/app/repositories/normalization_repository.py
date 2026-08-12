from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.models.normalized_info import NormalizedResumeModel
from app.models.normalized_job_description import NormalizedJDModel
from app.schemas.normalized_info import NormalizedJobDescriptionCreate, NormalizedResumeCreate


class NormalizationRepository:
    """Persistence-only operations for canonical Stage 4 data."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_or_update_resume(self, data: NormalizedResumeCreate | dict[str, Any], *, commit: bool = True, refresh: bool = True) -> NormalizedResumeModel:
        payload = NormalizedResumeCreate.model_validate(data).model_dump(mode="json")
        payload["document_id"] = UUID(payload["document_id"])
        payload["extracted_resume_id"] = UUID(payload["extracted_resume_id"])
        model = await self.get_resume_by_document_id(payload["document_id"])
        model = self._apply(model, NormalizedResumeModel, payload)
        try:
            if commit:
                await self.session.commit()
            else:
                await self.session.flush()
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        if refresh:
            await self.session.refresh(model)
        return model

    async def create_or_update_job_description(self, data: NormalizedJobDescriptionCreate | dict[str, Any], *, commit: bool = True, refresh: bool = True) -> NormalizedJDModel:
        payload = NormalizedJobDescriptionCreate.model_validate(data).model_dump(mode="json")
        payload["document_id"] = UUID(payload["document_id"])
        payload["extracted_job_description_id"] = UUID(payload["extracted_job_description_id"])
        model = await self.get_job_description_by_document_id(payload["document_id"])
        model = self._apply(model, NormalizedJDModel, payload)
        try:
            if commit:
                await self.session.commit()
            else:
                await self.session.flush()
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        if refresh:
            await self.session.refresh(model)
        return model

    async def get_resume_by_document_id(self, document_id: UUID) -> NormalizedResumeModel | None:
        return await self.session.scalar(select(NormalizedResumeModel).where(NormalizedResumeModel.document_id == document_id))

    async def get_resumes_by_document_ids(self, document_ids: list[UUID]) -> list[NormalizedResumeModel]:
        if not document_ids:
            return []
        result = await self.session.scalars(select(NormalizedResumeModel).where(NormalizedResumeModel.document_id.in_(document_ids)))
        return list(result.all())

    async def get_job_description_by_document_id(self, document_id: UUID) -> NormalizedJDModel | None:
        return await self.session.scalar(select(NormalizedJDModel).where(NormalizedJDModel.document_id == document_id))

    async def delete_resume_by_document_id(self, document_id: UUID) -> bool:
        result = await self.session.execute(delete(NormalizedResumeModel).where(NormalizedResumeModel.document_id == document_id))
        await self.session.commit()
        return bool(result.rowcount)

    async def delete_job_description_by_document_id(self, document_id: UUID) -> bool:
        result = await self.session.execute(delete(NormalizedJDModel).where(NormalizedJDModel.document_id == document_id))
        await self.session.commit()
        return bool(result.rowcount)

    def _apply(self, model: Any, model_type: type[Any], payload: dict[str, Any]) -> Any:
        if model is None:
            model = model_type(**payload)
            self.session.add(model)
            return model
        payload.pop("document_id", None)
        for field, value in payload.items():
            setattr(model, field, value)
        return model
