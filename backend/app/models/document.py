import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.parsed_document import ParsedDocumentModel


class DocumentTypeEnum(str, enum.Enum):
    RESUME = "RESUME"
    JOB_DESCRIPTION = "JOB_DESCRIPTION"


class ProcessingStageEnum(str, enum.Enum):
    UPLOAD = "UPLOAD"
    INGESTION = "INGESTION"
    PARSING = "PARSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProcessingStatusEnum(str, enum.Enum):
    UPLOADED = "UPLOADED"
    PARSING_PENDING = "PARSING_PENDING"
    PARSED = "PARSED"
    FAILED = "FAILED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class DocumentModel(UUIDMixin, TimestampMixin, Base):
    """Metadata for a project-owned document stored on disk."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_project_id", "project_id"),
        Index("ix_documents_document_type", "document_type"),
        Index("ix_documents_processing_status", "processing_status"),
        Index("ix_documents_file_hash", "file_hash"),
        Index("ix_documents_created_at", text("created_at DESC")),
        Index(
            "uq_project_active_job_description",
            "project_id",
            unique=True,
            postgresql_where=text(
                "document_type = 'JOB_DESCRIPTION' AND deleted_at IS NULL"
            ),
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    document_type: Mapped[DocumentTypeEnum] = mapped_column(
        Enum(DocumentTypeEnum, name="document_type_enum"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_stage: Mapped[ProcessingStageEnum] = mapped_column(
        Enum(ProcessingStageEnum, name="processing_stage_enum"),
        nullable=False,
        default=ProcessingStageEnum.INGESTION,
        server_default=ProcessingStageEnum.INGESTION.value,
    )
    processing_status: Mapped[ProcessingStatusEnum] = mapped_column(
        Enum(ProcessingStatusEnum, name="processing_status_enum"),
        nullable=False,
        default=ProcessingStatusEnum.UPLOADED,
        server_default=ProcessingStatusEnum.UPLOADED.value,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_document: Mapped["ParsedDocumentModel | None"] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        uselist=False,
    )
