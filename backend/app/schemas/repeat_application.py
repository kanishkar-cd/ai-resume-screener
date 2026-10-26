from __future__ import annotations

from datetime import datetime
import enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.candidate_identity import (
    CandidateIdentityInput,
    CandidateIdentityMatchResult,
)


class RepeatApplicationStatus(str, enum.Enum):
    """Deterministic classification of candidate repeat application status."""
    FIRST_APPLICATION = "FIRST_APPLICATION"
    REPEAT_APPLICATION_SAME_JOB = "REPEAT_APPLICATION_SAME_JOB"
    REPEAT_APPLICATION_DIFFERENT_JOB = "REPEAT_APPLICATION_DIFFERENT_JOB"
    MULTIPLE_PREVIOUS_APPLICATIONS = "MULTIPLE_PREVIOUS_APPLICATIONS"
    IDENTITY_REVIEW_REQUIRED = "IDENTITY_REVIEW_REQUIRED"
    JOB_OPENING_REQUIRED = "JOB_OPENING_REQUIRED"


class ApplicationHistoryItem(BaseModel):
    """Represents a distinct historical job application event for a candidate."""
    model_config = ConfigDict(extra="ignore")

    job_opening_id: str | None = None
    project_id: UUID | str | None = None
    job_title: str | None = None
    document_ids: list[UUID | str] = Field(default_factory=list)
    applied_at: datetime | str | None = None
    is_same_job: bool = False
    source: str | None = None  # e.g. "zoho", "manual_upload"


class RepeatApplicationInput(BaseModel):
    """Input payload for repeat application detection."""
    model_config = ConfigDict(extra="ignore")

    candidate_input: CandidateIdentityInput | dict[str, Any]
    job_opening_id: str | None = None
    project_id: UUID | str | None = None
    document_id: UUID | str | None = None
    job_title: str | None = None
    is_new_application_submission: bool = False


class RepeatApplicationResult(BaseModel):
    """Structured result returned by the Phase 3 Repeat Application Detection Engine."""
    model_config = ConfigDict(extra="ignore")

    status: RepeatApplicationStatus
    is_repeat: bool = False
    candidate_id: str | None = None
    zoho_candidate_id: str | None = None
    current_job_opening_id: str | None = None
    current_project_id: str | None = None
    total_previous_applications: int = 0
    previous_applications: list[ApplicationHistoryItem] = Field(default_factory=list)
    identity_match_result: CandidateIdentityMatchResult | None = None
    reasons: list[str] = Field(default_factory=list)
