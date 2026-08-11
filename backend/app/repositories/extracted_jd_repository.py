from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extracted_job_description import ExtractedJDModel
from app.schemas.extracted_jd import ExtractedJDCreate


class ExtractedJDRepository:
    """Async persistence for JD extraction results."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_document_id(self, document_id: UUID) -> ExtractedJDModel | None:
        statement = select(ExtractedJDModel).where(
            ExtractedJDModel.document_id == document_id
        )
        return await self.session.scalar(statement)

    async def upsert(
        self,
        payload: ExtractedJDCreate,
        *,
        commit: bool = True,
        refresh: bool = True,
    ) -> ExtractedJDModel:
        existing = await self.get_by_document_id(payload.document_id)
        data = payload.model_dump()
        document_id = data.pop("document_id")

        if existing is None:
            model = ExtractedJDModel(document_id=document_id, **data)
            self.session.add(model)
        else:
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
