from __future__ import annotations

import enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CandidateIdentityStatus(str, enum.Enum):
    EXISTING_CANDIDATE = "EXISTING_CANDIDATE"
    NEW_CANDIDATE = "NEW_CANDIDATE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class IdentityMatchMethod(str, enum.Enum):
    ZOHO_CANDIDATE_ID = "ZOHO_CANDIDATE_ID"
    NORMALIZED_EMAIL = "NORMALIZED_EMAIL"
    NORMALIZED_PHONE = "NORMALIZED_PHONE"
    NONE = "NONE"


class CandidateIdentityRecord(BaseModel):
    """Represents a candidate identity record found in the database or provided as input."""
    model_config = ConfigDict(extra="ignore")

    document_id: UUID | str
    candidate_name: str | None = None
    email: str | None = None
    phone: str | None = None
    zoho_candidate_id: str | None = None
    zoho_candidate_number: str | None = None
    zoho_attachment_id: str | None = None
    job_opening_id: str | None = None
    zoho_job_opening_id: str | None = None
    project_id: UUID | str | None = None
    job_title: str | None = None


class CandidateIdentityInput(BaseModel):
    """Input payload for matching candidate identity against existing records."""
    model_config = ConfigDict(extra="ignore")

    candidate_name: str | None = None
    email: str | None = None
    phone: str | None = None
    zoho_candidate_id: str | None = None
    zoho_attachment_id: str | None = None
    document_id: UUID | str | None = None


class CandidateIdentityMatchResult(BaseModel):
    """Structured result returned by the Phase 2 Candidate Identity Matching Engine."""
    model_config = ConfigDict(extra="ignore")

    status: CandidateIdentityStatus
    matched_candidate_id: str | None = None
    match_method: IdentityMatchMethod = IdentityMatchMethod.NONE
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    normalized_identity: dict[str, Any] = Field(default_factory=dict)
