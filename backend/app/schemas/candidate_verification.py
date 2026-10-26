from __future__ import annotations

from datetime import datetime
import enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.candidate_identity import (
    CandidateIdentityMatchResult,
    CandidateIdentityStatus,
)
from app.schemas.repeat_application import (
    ApplicationHistoryItem,
    RepeatApplicationResult,
    RepeatApplicationStatus,
)


class CandidateVerificationStatus(str, enum.Enum):
    """Status of an individual candidate's identity and application verification."""
    VERIFIED = "VERIFIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAILED = "FAILED"
    PENDING = "PENDING"


class BatchVerificationStatus(str, enum.Enum):
    """Status of the batch candidate verification job for a job opening."""
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


class CandidateVerificationItemResult(BaseModel):
    """Verification outcome for an individual candidate (and their grouped attachments)."""
    model_config = ConfigDict(extra="ignore")

    candidate_identifier: str
    document_ids: list[UUID | str] = Field(default_factory=list)
    candidate_name: str | None = None
    email: str | None = None
    phone: str | None = None
    zoho_candidate_id: str | None = None
    verification_status: CandidateVerificationStatus
    identity_status: CandidateIdentityStatus | None = None
    repeat_application_status: RepeatApplicationStatus | None = None
    is_repeat_applicant: bool = False
    confidence: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    previous_applications: list[ApplicationHistoryItem] = Field(default_factory=list)
    verified_at: datetime | str | None = None
    error_message: str | None = None


class BatchVerificationSummary(BaseModel):
    """Aggregate progress and candidate breakdown for batch candidate verification."""
    model_config = ConfigDict(extra="ignore")

    batch_id: str
    job_opening_id: str | None = None
    project_id: UUID | str | None = None
    status: BatchVerificationStatus
    total_candidates: int = 0
    processed_candidates: int = 0
    verified_candidates: int = 0
    review_required_candidates: int = 0
    failed_candidates: int = 0
    progress_percentage: float = 0.0
    started_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    results: list[CandidateVerificationItemResult] = Field(default_factory=list)
    error_message: str | None = None


class BatchVerificationRequest(BaseModel):
    """Request payload to initiate or retry candidate verification for a job opening."""
    model_config = ConfigDict(extra="ignore")

    force_reverify: bool = False


class BatchVerificationResponse(BaseModel):
    """Top-level response envelope for batch candidate verification."""
    model_config = ConfigDict(extra="ignore")

    data: BatchVerificationSummary
