from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ZohoStatusResponse(BaseModel):
    configured: bool = Field(..., description="Whether Zoho credentials and at least one refresh token are configured")
    accounts_url: str
    api_url: str
    has_job_token: bool
    has_candidate_token: bool
    has_attachment_token: bool


class ZohoJobOpeningRead(BaseModel):
    id: str = Field(..., description="Zoho Job Opening unique ID")
    posting_title: str = Field(..., description="Title of the job posting")
    job_opening_id: str | None = Field(default=None, description="Internal Job code/ID")
    job_description: str | None = Field(default=None, description="Full JD text / description")
    required_skills: str | None = Field(default=None, description="Required skill keywords")
    job_status: str | None = Field(default=None, description="Status e.g. In-progress, Open, Closed")
    target_date: str | None = None
    city: str | None = None
    department: str | None = None
    modified_time: str | None = None
    no_of_candidates_associated: int = 0


class ZohoJobOpeningListResponse(BaseModel):
    items: list[ZohoJobOpeningRead]
    total: int


class ZohoImportJDRequest(BaseModel):
    job_id: str = Field(..., description="Zoho Job Opening ID to import")


class ZohoImportApplicantsRequest(BaseModel):
    job_id: str = Field(..., description="Zoho Job Opening ID to fetch candidate resumes for")
    limit: int | None = Field(default=None, ge=1, le=200, description="Optional cap on number of resumes to import")


class ZohoImportApplicantsResponse(BaseModel):
    project_id: UUID
    job_id: str
    candidates_seen: int
    imported_count: int
    skipped_count: int
    document_ids: list[UUID]
    skipped: list[dict[str, str]] = Field(default_factory=list)
