from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CandidateInsightCreate(BaseModel):
    document_id: UUID
    project_id: UUID
    summary: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    score_explanation: str
    recommendation_reason: str
    improvement_suggestions: list[str] = Field(default_factory=list)


class CandidateInsightsRead(CandidateInsightCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CandidateInsightsResponse(BaseModel):
    data: CandidateInsightsRead


class PipelineStageStatus(BaseModel):
    total_candidates: int
    candidates_ingested: int
    candidates_parsed: int
    candidates_extracted: int
    candidates_normalized: int
    candidates_scored: int
    candidates_ranked: int


class PipelineStatusRead(BaseModel):
    project_id: UUID
    current_stage: str
    completed_stages: list[str]
    remaining_stages: list[str]
    resume_count: int
    stage_counts: PipelineStageStatus
    completion_percentage: float


class PipelineStatusResponse(BaseModel):
    data: PipelineStatusRead


class SkillFrequencyItem(BaseModel):
    skill_name: str
    frequency_count: int
    percentage: float


class ProjectAnalyticsRead(BaseModel):
    project_id: UUID
    total_candidates: int
    average_score: float
    highest_score: float
    lowest_score: float
    average_confidence: float
    recommendation_distribution: dict[str, int]
    top_matched_skills: list[SkillFrequencyItem]
    top_missing_skills: list[SkillFrequencyItem]
    knocked_out_count: int
    knocked_out_summary: list[dict[str, Any]]


class ProjectAnalyticsResponse(BaseModel):
    data: ProjectAnalyticsRead


class ProjectSummary(BaseModel):
    project_id: UUID
    project_title: str
    target_role: str
    total_candidates: int


class ProjectDashboardRead(BaseModel):
    project_summary: ProjectSummary
    pipeline_counts: PipelineStageStatus
    analytics: ProjectAnalyticsRead
    top_candidates: list[dict[str, Any]]
    pipeline_completion_percentage: float
    processing_time_seconds: float
    last_updated: datetime


class ProjectDashboardResponse(BaseModel):
    data: ProjectDashboardRead
