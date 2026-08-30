from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.document import DocumentType, ProcessingStage


class EducationItem(BaseModel):
    degree: str | None = None
    institution: str | None = None
    year: str | None = None
    field_of_study: str | None = None


class ExperienceItem(BaseModel):
    company: str | None = None
    title: str | None = None
    designation: str | None = None
    employment_type: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    duration: str | None = None
    is_current: bool = False
    description: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    location: str | None = None


class ProjectItem(BaseModel):
    name: str | None = None
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    summary: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)
    details: str | None = None


class ConfidenceMixin(BaseModel):
    confidence_scores: dict[str, float] = Field(default_factory=dict)

    @field_validator("confidence_scores")
    @classmethod
    def validate_confidence_scores(cls, value: dict[str, float]) -> dict[str, float]:
        if any(score < 0 or score > 1 for score in value.values()):
            raise ValueError("confidence scores must be between 0 and 1")
        return value


class ExtractedResumeCreate(ConfidenceMixin):
    document_id: UUID
    candidate_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    designation: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    skills: list[str] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractedResumeRead(ExtractedResumeCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ExtractedJobDescriptionCreate(ConfidenceMixin):
    document_id: UUID
    domain: str | None = Field(default=None, max_length=255)
    skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractedJobDescriptionRead(ExtractedJobDescriptionCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ExtractDocumentResponse(BaseModel):
    document_id: UUID
    document_type: DocumentType
    processing_stage: ProcessingStage
    message: str


class ExtractResponseEnvelope(BaseModel):
    data: ExtractDocumentResponse


class ExtractedDocumentResponse(BaseModel):
    data: ExtractedResumeRead | ExtractedJobDescriptionRead
