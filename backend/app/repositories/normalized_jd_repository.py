from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.normalized_job_description import NormalizedJDModel
from app.schemas.normalized_jd import NormalizedJDCreate


class NormalizedJDRepository:
    """Async persistence for JD normalization results."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_document_id(self, document_id: UUID) -> NormalizedJDModel | None:
        statement = select(NormalizedJDModel).where(
            NormalizedJDModel.document_id == document_id
        )
        return await self.session.scalar(statement)

    async def upsert(
        self,
        payload: NormalizedJDCreate,
        *,
        commit: bool = True,
        refresh: bool = True,
    ) -> NormalizedJDModel:
        existing = await self.get_by_document_id(payload.document_id)

        # Serialize nested Pydantic models to plain dicts for JSONB
        data = payload.model_dump()
        document_id = data.pop("document_id")
        extracted_id = data.pop("extracted_job_description_id")

        if existing is None:
            model = NormalizedJDModel(
                document_id=document_id,
                extracted_job_description_id=extracted_id,
                **data,
            )
            self.session.add(model)
        else:
            existing.extracted_job_description_id = extracted_id
            for key, value in data.items():
                setattr(existing, key, value)
            model = existing

        if commit:
            await self.session.commit()
        else:
            await self.session.flush()
        if refresh:
            await self.session.refresh(model)
        return model
