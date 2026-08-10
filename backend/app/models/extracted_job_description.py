from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.document import DocumentModel
    from app.models.normalized_job_description import NormalizedJDModel


class ExtractedJDModel(UUIDMixin, TimestampMixin, Base):
    """Structured field extraction result for a Job Description document."""

    __tablename__ = "extracted_job_descriptions"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_extracted_jds_document_id"),
        Index("ix_extracted_jds_document_id", "document_id"),
        Index("ix_extracted_jds_created_at", text("created_at DESC")),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    skills: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    responsibilities: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    education: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    experience: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    certifications: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    keywords: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    confidence_scores: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    document: Mapped["DocumentModel"] = relationship(
        back_populates="extracted_job_description"
    )
    normalized_job_description: Mapped[
        "NormalizedJDModel | None"
    ] = relationship(
        back_populates="extracted_job_description",
        cascade="all, delete-orphan",
        uselist=False,
    )

