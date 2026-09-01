from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from app.schemas.matching import MatchVerdict


class RecommendationLevel(str, Enum):
    SHORTLIST = "SHORTLIST"
    REVIEW = "REVIEW"
    CONSIDER = "CONSIDER"
    REJECT = "REJECT"




class ComponentScoreDetail(BaseModel):
    score: float = Field(ge=0, le=100)
    matched_items: list[str] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)
    explanation: str


class ComponentScores(BaseModel):
    skills: ComponentScoreDetail
    experience: ComponentScoreDetail
    projects: ComponentScoreDetail
    education: ComponentScoreDetail
    certifications: ComponentScoreDetail
    languages: ComponentScoreDetail
    responsibilities: ComponentScoreDetail | None = None
    preferred_skills: ComponentScoreDetail | None = None


class WeightedScores(BaseModel):
    skills: float
    experience: float
    projects: float
    education: float
    certifications: float
    languages: float = 0.0
    responsibilities: float = 0.0
    preferred_skills: float = 0.0


class AdjustmentItem(BaseModel):
    rule_name: str
    delta_points: float
    description: str


class CategoryBreakdownItem(BaseModel):
    category: str
    component_score: float
    effective_weight: float
    contribution: float
    is_applicable: bool


class CandidateScoreCreate(BaseModel):
    document_id: UUID
    project_id: UUID
    component_scores: ComponentScores
    weighted_scores: WeightedScores
    raw_total_score: float = Field(ge=0, le=100)
    weighted_total_score: float = Field(ge=0, le=100)
    penalty_total: float = Field(ge=0, le=30)
    bonus_total: float = Field(ge=0, le=15)
    final_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    recommendation: RecommendationLevel
    is_knocked_out: bool = False
    knockout_reason: str | None = None
    penalty_summary: list[AdjustmentItem] = Field(default_factory=list)
    bonus_summary: list[AdjustmentItem] = Field(default_factory=list)
    passing_score: float = Field(default=70.0, ge=0, le=100)
    effective_weights: dict[str, float] = Field(default_factory=dict)
    score_breakdown: list[CategoryBreakdownItem] = Field(default_factory=list)
    weight_config_version: int = Field(ge=1)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    match_verdicts: list[MatchVerdict] = Field(default_factory=list)



class CandidateScoreRead(CandidateScoreCreate):
    id: UUID
    skills_score: float
    experience_score: float
    projects_score: float
    education_score: float
    certifications_score: float
    languages_score: float
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CandidateScoreResponse(BaseModel):
    data: CandidateScoreRead


class ProjectScoringRead(BaseModel):
    project_id: UUID
    total_evaluated: int
    scores: list[CandidateScoreRead]


class ProjectScoringResponse(BaseModel):
    data: ProjectScoringRead


class ProjectScoresResponse(BaseModel):
    data: list[CandidateScoreRead]
