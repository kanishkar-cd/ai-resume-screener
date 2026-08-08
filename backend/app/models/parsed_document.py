from uuid import UUID

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin


class ParsedDocumentModel(UUIDMixin, TimestampMixin, Base):
    """Persisted text extraction result for one uploaded document."""

    __tablename__ = "parsed_documents"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_parsed_documents_document_id"),
        Index("ix_parsed_documents_document_id", "document_id"),
        Index("ix_parsed_documents_created_at", "created_at"),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_engine: Mapped[str] = mapped_column(String(32), nullable=False)
    parsing_duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
