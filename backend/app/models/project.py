import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.ranking import CandidateRankingModel
    from app.models.weight_config import WeightConfigModel


class ProjectStatusEnum(str, enum.Enum):
    """Database values representing a project's lifecycle state."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class ProjectModel(UUIDMixin, TimestampMixin, Base):
    """Hiring campaign project persisted in PostgreSQL."""

    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_status", "status"),
        Index("ix_projects_target_role", "target_role"),
        Index("ix_projects_created_at", text("created_at DESC")),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_role: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[ProjectStatusEnum] = mapped_column(
        Enum(ProjectStatusEnum, name="project_status_enum"),
        nullable=False,
        default=ProjectStatusEnum.DRAFT,
        server_default=ProjectStatusEnum.DRAFT.value,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rankings: Mapped[list["CandidateRankingModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    weight_config: Mapped["WeightConfigModel | None"] = relationship(
        "WeightConfigModel", back_populates="project", cascade="all, delete-orphan", uselist=False
    )
