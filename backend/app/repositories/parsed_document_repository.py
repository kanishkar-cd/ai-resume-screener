from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.parsed_document import ParsedDocumentModel
from app.schemas.parsed_document import ParsedDocumentCreate


class ParsedDocumentRepository:
    """Async persistence operations for normalized document text."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_or_update(
        self, parsed_data: ParsedDocumentCreate
    ) -> ParsedDocumentModel:
        model = await self.get_by_document_id(parsed_data.document_id)
        values = parsed_data.model_dump()
        values["parser_engine"] = values["parser_engine"].value
        if model is None:
            model = ParsedDocumentModel(**values)
            self.session.add(model)
        else:
            values.pop("document_id")
            for field, value in values.items():
                setattr(model, field, value)
        await self.session.commit()
        await self.session.refresh(model)
        return model

    async def get_by_document_id(
        self, document_id: UUID
    ) -> ParsedDocumentModel | None:
        return await self.session.scalar(
            select(ParsedDocumentModel).where(
                ParsedDocumentModel.document_id == document_id
            )
        )

    async def delete_by_document_id(self, document_id: UUID) -> bool:
        result = await self.session.execute(
            delete(ParsedDocumentModel).where(
                ParsedDocumentModel.document_id == document_id
            )
        )
        await self.session.commit()
        return bool(result.rowcount)
