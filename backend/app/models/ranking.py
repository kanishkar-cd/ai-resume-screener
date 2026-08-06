from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin
from app.models.scoring import RecommendationLevelEnum

if TYPE_CHECKING:
    from app.models.document import DocumentModel
    from app.models.project import ProjectModel
    from app.models.scoring import CandidateScoreModel


class CandidateRankingModel(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "candidate_rankings"
    __table_args__ = (
        UniqueConstraint("project_id", "rank_position", name="uq_project_rank_position"),
        Index("ix_candidate_rankings_project_rank", "project_id", "rank_position"),
        Index("ix_candidate_rankings_document_id", "document_id"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False)
    candidate_score_id: Mapped[UUID] = mapped_column(ForeignKey("candidate_scores.id", ondelete="CASCADE"), unique=True, nullable=False)
    rank_position: Mapped[int] = mapped_column(Integer, nullable=False)
    percentile: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    final_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    recommendation: Mapped[RecommendationLevelEnum] = mapped_column(Enum(RecommendationLevelEnum, name="recommendation_level_enum", create_type=False), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    previous_rank: Mapped[int | None] = mapped_column(Integer)
    rank_change: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    project: Mapped["ProjectModel"] = relationship(back_populates="rankings")
    document: Mapped["DocumentModel"] = relationship(back_populates="ranking")
    score: Mapped["CandidateScoreModel"] = relationship(back_populates="ranking")
