from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.document import DocumentModel


class ParsedDocumentModel(UUIDMixin, TimestampMixin, Base):
    """Normalized text and deterministic parsing metadata for one document."""

    __tablename__ = "parsed_documents"
    __table_args__ = (
        Index("ix_parsed_documents_document_id", "document_id"),
        Index("ix_parsed_documents_language", "language"),
        Index("ix_parsed_documents_parser_engine", "parser_engine"),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    parser_engine: Mapped[str] = mapped_column(String(64), nullable=False)
    parsing_duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    parsing_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    document: Mapped["DocumentModel"] = relationship(
        back_populates="parsed_document"
    )
