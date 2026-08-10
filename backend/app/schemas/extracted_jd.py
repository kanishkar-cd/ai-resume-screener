from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.document import ProcessingStage, ProcessingStatus, DocumentType


class ExtractedJDCreate(BaseModel):
    """Internal DTO for persisting a JD extraction result."""
    document_id: UUID
    domain: str | None = None
    skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    confidence_scores: dict[str, float] = Field(default_factory=dict)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractedJDRead(BaseModel):
    """API response shape for a persisted JD extraction."""
    id: UUID
    document_id: UUID
    domain: str | None
    skills: list[str]
    responsibilities: list[str]
    education: list[str]
    experience: list[str]
    certifications: list[str]
    keywords: list[str]
    confidence_scores: dict[str, float]
    raw_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ExtractedJDResponse(BaseModel):
    data: ExtractedJDRead


class JDExtractResult(BaseModel):
    """POST /documents/{id}/extract response body."""
    document_id: UUID
    document_type: DocumentType
    processing_stage: ProcessingStage
    processing_status: ProcessingStatus
    message: str


class JDExtractResponse(BaseModel):
    data: JDExtractResult
