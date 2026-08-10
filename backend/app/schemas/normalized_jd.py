from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.document import DocumentType, ProcessingStage, ProcessingStatus


class NormalizationChange(BaseModel):
    field: str
    source: str | None = None
    canonical: str | None = None
    rule: str


class NormalizationMetadata(BaseModel):
    ruleset_version: str = "1.0"
    normalized_at: str
    changes: list[NormalizationChange] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    field_confidence: dict[str, float] = Field(default_factory=dict)


class CanonicalExperienceRequirement(BaseModel):
    minimum_months: int | None = None
    maximum_months: int | None = None
    display_value: str


class NormalizedJDCreate(BaseModel):
    """Internal DTO for persisting a JD normalization result."""
    document_id: UUID
    extracted_job_description_id: UUID
    skills: list[str] = Field(default_factory=list)
    degree_requirements: list[str] = Field(default_factory=list)
    experience_requirements: list[CanonicalExperienceRequirement] = Field(default_factory=list)
    domain: str | None = None
    keywords: list[str] = Field(default_factory=list)
    normalization_metadata: NormalizationMetadata
    ruleset_version: str = "1.0"


class NormalizedJDRead(BaseModel):
    """API response shape for a persisted JD normalization."""
    id: UUID
    document_id: UUID
    extracted_job_description_id: UUID
    skills: list[str]
    degree_requirements: list[str]
    experience_requirements: list[CanonicalExperienceRequirement]
    domain: str | None
    keywords: list[str]
    normalization_metadata: NormalizationMetadata
    ruleset_version: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm_model(cls, obj: Any) -> "NormalizedJDRead":
        """Build from ORM model, parsing JSONB dicts into typed sub-models."""
        meta_raw = obj.normalization_metadata or {}
        if isinstance(meta_raw, dict):
            meta = NormalizationMetadata(
                ruleset_version=meta_raw.get("ruleset_version", obj.ruleset_version),
                normalized_at=meta_raw.get("normalized_at", ""),
                changes=[
                    NormalizationChange(**c) if isinstance(c, dict) else c
                    for c in meta_raw.get("changes", [])
                ],
                warnings=meta_raw.get("warnings", []),
                field_confidence=meta_raw.get("field_confidence", {}),
            )
        else:
            meta = meta_raw

        exp_reqs_raw = obj.experience_requirements or []
        exp_reqs = [
            CanonicalExperienceRequirement(**e) if isinstance(e, dict) else e
            for e in exp_reqs_raw
        ]

        return cls(
            id=obj.id,
            document_id=obj.document_id,
            extracted_job_description_id=obj.extracted_job_description_id,
            skills=obj.skills or [],
            degree_requirements=obj.degree_requirements or [],
            experience_requirements=exp_reqs,
            domain=obj.domain,
            keywords=obj.keywords or [],
            normalization_metadata=meta,
            ruleset_version=obj.ruleset_version,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class NormalizedJDResponse(BaseModel):
    data: NormalizedJDRead


class JDNormalizeResult(BaseModel):
    """POST /documents/{id}/normalize response body."""
    document_id: UUID
    document_type: DocumentType
    processing_stage: ProcessingStage
    processing_status: ProcessingStatus
    ruleset_version: str
    message: str


class JDNormalizeResponse(BaseModel):
    data: JDNormalizeResult
