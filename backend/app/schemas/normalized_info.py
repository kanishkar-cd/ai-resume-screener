from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.document import DocumentType, ProcessingStage


class CanonicalEducationItem(BaseModel):
    degree: str | None = None
    field_of_study: str | None = None
    institution: str | None = None
    graduation_date: str | None = None


class CanonicalExperienceItem(BaseModel):
    company: str | None = None
    job_title: str | None = None
    employment_type: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    is_current: bool = False
    duration_months: int | None = Field(default=None, ge=0)
    duration_display: str | None = None
    description: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    location: str | None = None


class CanonicalLocation(BaseModel):
    city: str | None = None
    region: str | None = None
    country: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    display_name: str


class CanonicalExperienceRequirement(BaseModel):
    minimum_months: int | None = Field(default=None, ge=0)
    maximum_months: int | None = Field(default=None, ge=0)
    display_value: str


class NormalizationChange(BaseModel):
    field: str
    source: str | None = None
    canonical: str | None = None
    rule: str


class NormalizationMetadata(BaseModel):
    ruleset_version: str
    normalized_at: datetime
    changes: list[NormalizationChange] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    field_confidence: dict[str, float] = Field(default_factory=dict)

    @field_validator("field_confidence")
    @classmethod
    def validate_confidence(cls, value: dict[str, float]) -> dict[str, float]:
        if any(score < 0 or score > 1 for score in value.values()):
            raise ValueError("normalization confidence must be between 0 and 1")
        return value


class CanonicalProjectItem(BaseModel):
    name: str | None = None
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)


class NormalizedResumeCreate(BaseModel):
    document_id: UUID
    extracted_resume_id: UUID
    skills: list[str] = Field(default_factory=list)
    education: list[CanonicalEducationItem] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    job_titles: list[str] = Field(default_factory=list)
    experience: list[CanonicalExperienceItem] = Field(default_factory=list)
    projects: list[CanonicalProjectItem] = Field(default_factory=list)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    locations: list[CanonicalLocation] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    normalization_metadata: NormalizationMetadata
    ruleset_version: str = Field(max_length=32)


class NormalizedResumeRead(NormalizedResumeCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": {
            "id": "11223344-5566-7788-9900-aabbccddeeff",
            "document_id": "550e8400-e29b-41d4-a716-446655440000",
            "extracted_resume_id": "66223344-5566-7788-9900-aabbccddeeff",
            "skills": ["Python", "PostgreSQL"], "education": [],
            "companies": ["Acme Corporation"], "job_titles": ["Software Engineer"],
            "experience": [], "phone": "+919876543210", "email": "jane@example.com",
            "locations": [], "languages": ["English"], "certifications": [],
            "normalization_metadata": {"ruleset_version": "1.0.0", "normalized_at": "2026-08-06T17:00:00Z", "changes": [], "warnings": [], "field_confidence": {"skills": 0.95}},
            "ruleset_version": "1.0.0", "created_at": "2026-08-06T17:00:00Z", "updated_at": "2026-08-06T17:00:00Z",
        }},
    )


class NormalizedJobDescriptionCreate(BaseModel):
    document_id: UUID
    extracted_job_description_id: UUID
    skills: list[str] = Field(default_factory=list)
    degree_requirements: list[str] = Field(default_factory=list)
    experience_requirements: list[CanonicalExperienceRequirement] = Field(default_factory=list)
    domain: str | None = Field(default=None, max_length=255)
    keywords: list[str] = Field(default_factory=list)
    normalization_metadata: NormalizationMetadata
    ruleset_version: str = Field(max_length=32)


class NormalizedJobDescriptionRead(NormalizedJobDescriptionCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": {
            "id": "21223344-5566-7788-9900-aabbccddeeff",
            "document_id": "750e8400-e29b-41d4-a716-446655440000",
            "extracted_job_description_id": "86223344-5566-7788-9900-aabbccddeeff",
            "skills": ["Python", "PostgreSQL"],
            "degree_requirements": ["Bachelor of Engineering"],
            "experience_requirements": [{"minimum_months": 36, "maximum_months": None, "display_value": "3 years+"}],
            "domain": "Software Engineering", "keywords": ["Python", "Software Engineer"],
            "normalization_metadata": {"ruleset_version": "1.0.0", "normalized_at": "2026-08-06T17:00:00Z", "changes": [], "warnings": [], "field_confidence": {"skills": 0.95}},
            "ruleset_version": "1.0.0", "created_at": "2026-08-06T17:00:00Z", "updated_at": "2026-08-06T17:00:00Z",
        }},
    )


class NormalizeDocumentResponse(BaseModel):
    document_id: UUID
    document_type: DocumentType
    processing_stage: ProcessingStage
    ruleset_version: str
    message: str


class NormalizeResponseEnvelope(BaseModel):
    data: NormalizeDocumentResponse


class NormalizedDocumentResponse(BaseModel):
    data: NormalizedResumeRead | NormalizedJobDescriptionRead
