import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin


class DocumentTypeEnum(str, enum.Enum):
    RESUME = "RESUME"
    JOB_DESCRIPTION = "JOB_DESCRIPTION"


class ProcessingStageEnum(str, enum.Enum):
    UPLOAD = "UPLOAD"


class ProcessingStatusEnum(str, enum.Enum):
    UPLOADED = "UPLOADED"
    PARSING_PENDING = "PARSING_PENDING"
    PARSED = "PARSED"
    FAILED = "FAILED"


class DocumentModel(UUIDMixin, TimestampMixin, Base):
    """Metadata for a project-owned document stored on disk."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_project_id", "project_id"),
        Index("ix_documents_document_type", "document_type"),
        Index("ix_documents_processing_status", "processing_status"),
        Index("ix_documents_file_hash", "file_hash"),
        Index("ix_documents_created_at", text("created_at DESC")),
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
        default=ProcessingStageEnum.UPLOAD,
        server_default=ProcessingStageEnum.UPLOAD.value,
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
