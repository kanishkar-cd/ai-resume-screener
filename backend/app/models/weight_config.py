from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.project import ProjectModel


def _json_list() -> Mapped[list[Any]]:
    return mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))


class ProjectWeightConfigModel(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "project_weight_configs"
    __table_args__ = (
        CheckConstraint(
            "skills_weight + experience_weight + projects_weight + education_weight + certifications_weight + languages_weight = 100.00",
            name="ck_total_weights",
        ),
        Index("ix_project_weight_configs_project_id", "project_id"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True)
    skills_weight: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("40.00"), server_default="40.00")
    experience_weight: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("25.00"), server_default="25.00")
    projects_weight: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("15.00"), server_default="15.00")
    education_weight: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("10.00"), server_default="10.00")
    certifications_weight: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("5.00"), server_default="5.00")
    languages_weight: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("5.00"), server_default="5.00")
    passing_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("70.00"), server_default="70.00")
    min_experience_years: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=Decimal("0.0"), server_default="0.0")
    required_degree: Mapped[str | None] = mapped_column(String(255))
    required_certifications: Mapped[list[Any]] = _json_list()
    mandatory_skills: Mapped[list[Any]] = _json_list()
    preferred_skills: Mapped[list[Any]] = _json_list()
    knockout_rules: Mapped[list[Any]] = _json_list()
    custom_keywords: Mapped[list[Any]] = _json_list()
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    project: Mapped["ProjectModel"] = relationship(back_populates="weight_config")
