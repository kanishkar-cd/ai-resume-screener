from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.document import DocumentModel
    from app.models.normalized_info import (
        NormalizedJobDescriptionModel,
        NormalizedResumeModel,
    )


def _json_list() -> Mapped[list[Any]]:
    return mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )


def _json_dict() -> Mapped[dict[str, Any]]:
    return mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class ExtractedResumeModel(UUIDMixin, TimestampMixin, Base):
    """Rule-based structured entities extracted from one resume."""

    __tablename__ = "extracted_resumes"
    __table_args__ = (
        Index("ix_extracted_resumes_document_id", "document_id"),
        Index("ix_extracted_resumes_email", "email"),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    candidate_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    designation: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    skills: Mapped[list[Any]] = _json_list()
    education: Mapped[list[Any]] = _json_list()
    experience: Mapped[list[Any]] = _json_list()
    projects: Mapped[list[Any]] = _json_list()
    certifications: Mapped[list[Any]] = _json_list()
    companies: Mapped[list[Any]] = _json_list()
    languages: Mapped[list[Any]] = _json_list()
    raw_metadata: Mapped[dict[str, Any]] = _json_dict()
    confidence_scores: Mapped[dict[str, Any]] = _json_dict()
    document: Mapped["DocumentModel"] = relationship(back_populates="extracted_resume")
    normalized_resume: Mapped["NormalizedResumeModel | None"] = relationship(
        back_populates="extracted_resume", cascade="all, delete-orphan", uselist=False
    )


class ExtractedJobDescriptionModel(UUIDMixin, TimestampMixin, Base):
    """Rule-based structured entities extracted from one job description."""

    __tablename__ = "extracted_job_descriptions"
    __table_args__ = (
        Index("ix_extracted_job_descriptions_document_id", "document_id"),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    domain: Mapped[str | None] = mapped_column(String(255))
    skills: Mapped[list[Any]] = _json_list()
    responsibilities: Mapped[list[Any]] = _json_list()
    education: Mapped[list[Any]] = _json_list()
    experience: Mapped[list[Any]] = _json_list()
    certifications: Mapped[list[Any]] = _json_list()
    keywords: Mapped[list[Any]] = _json_list()
    raw_metadata: Mapped[dict[str, Any]] = _json_dict()
    confidence_scores: Mapped[dict[str, Any]] = _json_dict()
    document: Mapped["DocumentModel"] = relationship(
        back_populates="extracted_job_description"
    )
    normalized_job_description: Mapped[
        "NormalizedJobDescriptionModel | None"
    ] = relationship(
        back_populates="extracted_job_description",
        cascade="all, delete-orphan",
        uselist=False,
    )
