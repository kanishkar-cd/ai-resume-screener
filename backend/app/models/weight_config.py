from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.project import ProjectModel


# Authoritative single source of truth for default project passing threshold
DEFAULT_PASSING_SCORE: float = 60.0


class WeightConfigModel(UUIDMixin, TimestampMixin, Base):
    """Recruiter weight and screening threshold configuration persisted in PostgreSQL."""

    __tablename__ = "weight_configs"
    __table_args__ = (
        Index("ix_weight_configs_project_id", "project_id"),
        Index("ix_weight_configs_created_at", text("created_at DESC")),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    weights: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    passing_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=DEFAULT_PASSING_SCORE, server_default=str(DEFAULT_PASSING_SCORE)
    )
    min_experience_years: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    required_degree: Mapped[str | None] = mapped_column(String(255), nullable=True)
    required_certifications: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    mandatory_skills: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    preferred_skills: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    knockout_rules: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    custom_keywords: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    project: Mapped["ProjectModel"] = relationship(back_populates="weight_config")
