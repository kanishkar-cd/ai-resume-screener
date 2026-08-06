from enum import Enum
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentType(str, Enum):
    RESUME = "RESUME"
    JOB_DESCRIPTION = "JOB_DESCRIPTION"


class ProcessingStage(str, Enum):
    UPLOAD = "UPLOAD"
    INGESTION = "INGESTION"
    PARSING = "PARSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProcessingStatus(str, Enum):
    UPLOADED = "UPLOADED"
    PARSING_PENDING = "PARSING_PENDING"
    PARSED = "PARSED"
    FAILED = "FAILED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class DocumentCreate(BaseModel):
    project_id: UUID
    document_type: DocumentType
    original_filename: str = Field(max_length=255)
    stored_filename: str = Field(max_length=255)
    file_path: str = Field(max_length=512)
    file_size_bytes: int = Field(gt=0)
    mime_type: str = Field(max_length=128)
    file_hash: str = Field(min_length=64, max_length=64)
    processing_stage: ProcessingStage = ProcessingStage.INGESTION
    processing_status: ProcessingStatus = ProcessingStatus.UPLOADED
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class DocumentUploadRead(BaseModel):
    document_id: UUID
    project_id: UUID
    document_type: DocumentType
    filename: str
    processing_stage: ProcessingStage
    processing_status: ProcessingStatus
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "document_id": "550e8400-e29b-41d4-a716-446655440000",
                "project_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                "document_type": "RESUME",
                "filename": "senior_python_resume.pdf",
                "processing_stage": "INGESTION",
                "processing_status": "UPLOADED",
            }
        },
    )


class DocumentUploadResponse(BaseModel):
    data: DocumentUploadRead


class DocumentRead(BaseModel):
    id: UUID
    project_id: UUID
    document_type: DocumentType
    original_filename: str
    file_size_bytes: int
    mime_type: str
    file_hash: str
    processing_stage: ProcessingStage
    processing_status: ProcessingStatus
    error_message: str | None = None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "project_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                "document_type": "RESUME",
                "original_filename": "senior_python_resume.pdf",
                "file_size_bytes": 1048576,
                "mime_type": "application/pdf",
                "file_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "processing_stage": "INGESTION",
                "processing_status": "UPLOADED",
                "error_message": None,
                "metadata_json": {},
                "created_at": "2026-08-06T12:00:00Z",
                "updated_at": "2026-08-06T12:00:00Z",
            }
        },
    )


class DocumentPaginatedResponse(BaseModel):
    items: list[DocumentRead]
    total: int
    page: int
    page_size: int
    total_pages: int


class DocumentResponse(BaseModel):
    data: DocumentRead


class DocumentListResponse(BaseModel):
    data: DocumentPaginatedResponse


class FailedUploadItem(BaseModel):
    original_filename: str
    error_code: str
    message: str


class BatchResumeUploadRead(BaseModel):
    project_id: UUID
    total_received: int
    successful_count: int
    failed_count: int
    successful_uploads: list[DocumentUploadRead]
    failed_uploads: list[FailedUploadItem]


class BatchResumeUploadResponse(BaseModel):
    data: BatchResumeUploadRead
