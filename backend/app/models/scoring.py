import enum
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.ranking import CandidateRankingModel


class RecommendationLevelEnum(str, enum.Enum):
    SHORTLIST = "SHORTLIST"
    REVIEW = "REVIEW"
    CONSIDER = "CONSIDER"
    REJECT = "REJECT"

    # Backward compatibility mappings for DB persistence
    STRONG_MATCH = "SHORTLIST"
    RECOMMENDED = "REVIEW"
    NEEDS_REVIEW = "CONSIDER"
    NOT_RECOMMENDED = "REJECT"


def _score_column() -> Mapped[Decimal]:
    return mapped_column(Numeric(5, 2), nullable=False)


class CandidateScoreModel(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "candidate_scores"
    __table_args__ = (
        Index("ix_candidate_scores_document_id", "document_id"),
        Index("ix_candidate_scores_project_id", "project_id"),
        Index("ix_candidate_scores_recommendation", "recommendation"),
    )

    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    skills_score: Mapped[Decimal] = _score_column()
    experience_score: Mapped[Decimal] = _score_column()
    projects_score: Mapped[Decimal] = _score_column()
    education_score: Mapped[Decimal] = _score_column()
    certifications_score: Mapped[Decimal] = _score_column()
    languages_score: Mapped[Decimal] = _score_column()
    component_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    weighted_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_total_score: Mapped[Decimal] = _score_column()
    weighted_total_score: Mapped[Decimal] = _score_column()
    penalty_total: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"), server_default="0")
    bonus_total: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"), server_default="0")
    final_score: Mapped[Decimal] = _score_column()
    confidence: Mapped[Decimal] = _score_column()
    recommendation: Mapped[RecommendationLevelEnum] = mapped_column(
        Enum(
            RecommendationLevelEnum,
            name="recommendation_level_enum",
            values_callable=lambda _: ["STRONG_MATCH", "RECOMMENDED", "NEEDS_REVIEW", "NOT_RECOMMENDED"],
        ),
        nullable=False,
    )
    is_knocked_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


    knockout_reason: Mapped[str | None] = mapped_column(Text)
    penalty_summary: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    bonus_summary: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    weight_config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ranking: Mapped["CandidateRankingModel | None"] = relationship(
        back_populates="score", cascade="all, delete-orphan", uselist=False
    )
