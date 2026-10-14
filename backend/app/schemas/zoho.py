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
    auto_process: bool = Field(default=False, description="Whether to run parsing, extraction, and normalization on imported resumes")


class ZohoFetchSummary(BaseModel):
    total_found: int = Field(..., description="Total eligible resumes currently found in Zoho for the selected Job Opening.")
    already_fetched: int = Field(..., description="Number of those resumes that had already been imported for this Job Opening before the current fetch began.")
    new_resumes: int = Field(..., description="Number of previously unimported resumes successfully imported during this fetch.")
    failed_resumes: int = Field(default=0, description="Number of eligible resumes that failed to import during this fetch.")


class ZohoImportApplicantsResponse(BaseModel):
    project_id: UUID
    job_id: str
    candidates_seen: int
    total_resumes: int = 0
    imported_count: int
    skipped_count: int
    failed_count: int = 0
    document_ids: list[UUID]
    skipped: list[dict[str, str]] = Field(default_factory=list)
    total_found: int = 0
    already_fetched: int = 0
    new_resumes: int = 0
    failed_resumes: int = 0
    summary: ZohoFetchSummary | None = None
