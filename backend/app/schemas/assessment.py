from uuid import UUID
from pydantic import Field, field_validator
from app.schemas.base import APIModel


class AssessmentHandoffRequest(APIModel):
    candidate_ids: list[UUID] = Field(..., min_length=1, description="List of candidate document UUIDs to hand off")
    requisition_ref: str = Field(..., min_length=1, max_length=100, description="Requisition reference string")
    provider: str = Field(default="ses", description="Email provider to use: 'ses', 'smtp', 'gmail', or 'outlook'")

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        v_clean = v.strip().lower()
        if v_clean not in ("ses", "smtp", "amazon_ses", "gmail", "outlook"):
            raise ValueError(
                f"Invalid email provider '{v}'. Allowed providers are 'ses', 'smtp', 'gmail', and 'outlook'."
            )
        return v_clean



class CandidateAssessmentItem(APIModel):
    candidate_id: UUID
    candidate_name: str
    email: str
    assessment_link: str | None = None
    status: str = "INVITED"


class AssessmentHandoffData(APIModel):
    project_id: UUID
    requisition_ref: str
    total_invited: int
    candidates: list[CandidateAssessmentItem]


class AssessmentHandoffResponse(APIModel):
    data: AssessmentHandoffData
