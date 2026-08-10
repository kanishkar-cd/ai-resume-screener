from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.document import DocumentModel
    from app.models.extracted_job_description import ExtractedJDModel


class NormalizedJDModel(UUIDMixin, TimestampMixin, Base):
    """Canonicalized, normalized requirement set for a Job Description."""

    __tablename__ = "normalized_job_descriptions"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_normalized_jds_document_id"),
        Index("ix_normalized_jds_document_id", "document_id"),
        Index("ix_normalized_jds_created_at", text("created_at DESC")),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    extracted_job_description_id: Mapped[UUID] = mapped_column(
        ForeignKey("extracted_job_descriptions.id", ondelete="CASCADE"), nullable=False
    )
    skills: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    degree_requirements: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    experience_requirements: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    keywords: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    normalization_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    ruleset_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="1.0", server_default=text("'1.0'")
    )
    document: Mapped["DocumentModel"] = relationship(
        back_populates="normalized_job_description"
    )
    extracted_job_description: Mapped["ExtractedJDModel"] = relationship(
        back_populates="normalized_job_description"
    )

