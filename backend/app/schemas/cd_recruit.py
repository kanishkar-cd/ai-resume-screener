from datetime import datetime
from typing import Any
from pydantic import Field, field_validator
from app.schemas.base import APIModel


class CDRecruitCandidateItem(APIModel):
    name: str = Field(..., min_length=1, description="Candidate full name")
    email: str = Field(..., description="Candidate email address")
    phone: str = Field(default="", description="Candidate contact phone number")
    ai_score: float = Field(default=0.0, description="Candidate AI match score")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Candidate metadata including document_id")


class CDRecruitPushPayload(APIModel):
    requisition_ref: str = Field(..., description="Stable requisition reference string")
    department_code: str = Field(..., description="One of 8 CD-Recruit department codes")
    level: str = Field(..., description="Top-level experience level: 'FRESHER' or 'EXPERIENCED'")
    drive_name: str = Field(..., description="Hiring campaign drive title")
    candidates: list[CDRecruitCandidateItem] = Field(..., min_length=1)

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        v_clean = v.strip().upper()
        if v_clean not in ("FRESHER", "EXPERIENCED"):
            raise ValueError(f"Invalid level '{v}'. Level must be 'FRESHER' or 'EXPERIENCED'.")
        return v_clean


class CDRecruitInviteResponseItem(APIModel):
    external_candidate_ref: str | None = None
    candidate_email: str | None = None
    email: str | None = None
    assessment_link: str | None = None
    assessment_url: str | None = None
    expires_at: str | datetime | None = None


class CDRecruitRequisitionStatusResponse(APIModel):
    requisition_ref: str
    drive_id: str | None = None
    session_status: str = "not_started"
    score_status: str = "not_graded"
    composite_score_band: str | None = None
    decision: str | None = None
