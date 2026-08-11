from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.parsed_document import ParsedDocumentModel
from app.schemas.parsed_document import ParsedDocumentCreate


class ParsedDocumentRepository:
    """Async persistence for document parse results."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_document_id(
        self, document_id: UUID
    ) -> ParsedDocumentModel | None:
        statement = select(ParsedDocumentModel).where(
            ParsedDocumentModel.document_id == document_id
        )
        return await self.session.scalar(statement)

    async def upsert(
        self, payload: ParsedDocumentCreate, *, commit: bool = True, refresh: bool = True
    ) -> ParsedDocumentModel:
        existing = await self.get_by_document_id(payload.document_id)
        if existing is None:
            model = ParsedDocumentModel(
                document_id=payload.document_id,
                raw_text=payload.raw_text,
                normalized_text=payload.normalized_text,
                page_count=payload.page_count,
                word_count=payload.word_count,
                character_count=payload.character_count,
                parser_engine=payload.parser_engine.value,
                parsing_duration_ms=payload.parsing_duration_ms,
            )
            self.session.add(model)
        else:
            existing.raw_text = payload.raw_text
            existing.normalized_text = payload.normalized_text
            existing.page_count = payload.page_count
            existing.word_count = payload.word_count
            existing.character_count = payload.character_count
            existing.parser_engine = payload.parser_engine.value
            existing.parsing_duration_ms = payload.parsing_duration_ms
            model = existing

        if commit:
            await self.session.commit()
            if refresh:
                await self.session.refresh(model)
        else:
            await self.session.flush()
            if refresh:
                await self.session.refresh(model)
        return model

    async def create(self, payload: ParsedDocumentCreate) -> ParsedDocumentModel:
        """Backward-compatible create that upserts by document_id."""
        return await self.upsert(payload)

    async def create_or_update(
        self, payload: ParsedDocumentCreate, *, commit: bool = True
    ) -> ParsedDocumentModel:
        """Backward-compatible alias for upsert."""
        return await self.upsert(payload, commit=commit)

    async def delete_by_document_id(
        self, document_id: UUID, *, commit: bool = True
    ) -> bool:
        model = await self.get_by_document_id(document_id)
        if model is None:
            return False
        await self.session.delete(model)
        if commit:
            await self.session.commit()
        else:
            await self.session.flush()
        return True
