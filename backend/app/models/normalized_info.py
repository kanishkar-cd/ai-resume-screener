from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.document import DocumentModel
    from app.models.extracted_info import ExtractedResumeModel


def _json_list() -> Mapped[list[Any]]:
    return mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))


def _json_dict() -> Mapped[dict[str, Any]]:
    return mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))


class NormalizedResumeModel(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "normalized_resumes"
    __table_args__ = (
        Index("ix_normalized_resumes_document_id", "document_id"),
        Index("ix_normalized_resumes_extracted_resume_id", "extracted_resume_id"),
        Index("ix_normalized_resumes_skills_gin", "skills", postgresql_using="gin"),
        Index("ix_normalized_resumes_job_titles_gin", "job_titles", postgresql_using="gin"),
    )

    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False)
    extracted_resume_id: Mapped[UUID] = mapped_column(ForeignKey("extracted_resumes.id", ondelete="CASCADE"), unique=True, nullable=False)
    skills: Mapped[list[Any]] = _json_list()
    education: Mapped[list[Any]] = _json_list()
    companies: Mapped[list[Any]] = _json_list()
    job_titles: Mapped[list[Any]] = _json_list()
    experience: Mapped[list[Any]] = _json_list()
    projects: Mapped[list[Any]] = _json_list()
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    locations: Mapped[list[Any]] = _json_list()
    languages: Mapped[list[Any]] = _json_list()
    certifications: Mapped[list[Any]] = _json_list()
    normalization_metadata: Mapped[dict[str, Any]] = _json_dict()
    ruleset_version: Mapped[str] = mapped_column(String(32), nullable=False)
    document: Mapped["DocumentModel"] = relationship(back_populates="normalized_resume")
    extracted_resume: Mapped["ExtractedResumeModel"] = relationship(back_populates="normalized_resume")

