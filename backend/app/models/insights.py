from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin


def _json_list() -> Mapped[list[Any]]:
    return mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))


class CandidateInsightModel(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "candidate_insights"
    __table_args__ = (
        Index("ix_candidate_insights_document_id", "document_id"),
        Index("ix_candidate_insights_project_id", "project_id"),
    )

    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    strengths: Mapped[list[Any]] = _json_list()
    weaknesses: Mapped[list[Any]] = _json_list()
    matched_skills: Mapped[list[Any]] = _json_list()
    missing_skills: Mapped[list[Any]] = _json_list()
    score_explanation: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    improvement_suggestions: Mapped[list[Any]] = _json_list()
