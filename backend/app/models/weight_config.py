from typing import Any
from uuid import UUID

from sqlalchemy import Float, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin


class WeightConfigModel(UUIDMixin, TimestampMixin, Base):
    """Scoring weights and criteria configuration persisted per project."""

    __tablename__ = "weight_configs"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_weight_configs_project_id"),
        Index("ix_weight_configs_project_id", "project_id"),
        Index("ix_weight_configs_created_at", text("created_at DESC")),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    weights: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    passing_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=60.0, server_default=text("60.0")
    )
    min_experience_years: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default=text("0.0")
    )
    required_degree: Mapped[str | None] = mapped_column(String(255), nullable=True)
    required_certifications: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    mandatory_skills: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    preferred_skills: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    knockout_rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    custom_keywords: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
