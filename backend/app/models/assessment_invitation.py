from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.document import DocumentModel
    from app.models.project import ProjectModel


class CandidateAssessmentModel(UUIDMixin, TimestampMixin, Base):
    """Persisted technical assessment invitation and evaluation record for CD-Recruit."""

    __tablename__ = "candidate_assessments"
    __table_args__ = (
        Index("ix_candidate_assessments_project_id", "project_id"),
        Index("ix_candidate_assessments_document_id", "document_id"),
        Index("ix_candidate_assessments_requisition_ref", "requisition_ref"),
        Index("ix_candidate_assessments_ext_candidate_ref", "external_candidate_ref"),
        Index("ix_candidate_assessments_idempotency_key", "idempotency_key"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    requisition_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    drive_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_candidate_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    experience_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)

    assessment_link: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="not_started", server_default="not_started"
    )
    score_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="not_graded", server_default="not_graded"
    )
    composite_score_band: Mapped[str | None] = mapped_column(String(50), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(50), nullable=True)

    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["ProjectModel"] = relationship("ProjectModel")
    document: Mapped["DocumentModel"] = relationship("DocumentModel")
