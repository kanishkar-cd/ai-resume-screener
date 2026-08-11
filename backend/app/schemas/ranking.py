from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.scoring import RecommendationLevel


class RankingSortField(str, Enum):
    RANK = "rank_position"
    SCORE = "final_score"
    SKILLS = "skills_score"
    EXPERIENCE = "experience_score"
    CONFIDENCE = "confidence"
    CREATED_AT = "created_at"


class RankingSortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class CandidateRankingCreate(BaseModel):
    document_id: UUID
    candidate_score_id: UUID
    rank_position: int = Field(ge=1)
    percentile: float = Field(ge=0, le=100)
    final_score: float = Field(ge=0, le=100)
    recommendation: RecommendationLevel
    confidence: float = Field(ge=0, le=100)
    previous_rank: int | None = Field(default=None, ge=1)
    rank_change: int = 0


class CandidateRankingRead(BaseModel):
    id: UUID
    project_id: UUID
    document_id: UUID
    candidate_name: str = "Anonymous Candidate"
    email: str | None = None
    rank_position: int
    percentile: float
    final_score: float
    recommendation: RecommendationLevel
    confidence: float
    is_knocked_out: bool
    knockout_reason: str | None = None
    skills_score: float
    experience_score: float
    previous_rank: int | None = None
    rank_change: int
    created_at: datetime


class RankingComputationRead(BaseModel):
    project_id: UUID
    total_ranked: int
    message: str


class RankingComputationResponse(BaseModel):
    data: RankingComputationRead


class ProjectRankingListRead(BaseModel):
    items: list[CandidateRankingRead]
    total: int
    page: int
    page_size: int
    total_pages: int


class ProjectRankingListResponse(BaseModel):
    data: ProjectRankingListRead


class ProjectLeaderboardRead(BaseModel):
    project_id: UUID
    top_n: int
    candidates: list[CandidateRankingRead]


class ProjectLeaderboardResponse(BaseModel):
    data: ProjectLeaderboardRead


class RecommendationDistribution(BaseModel):
    strong_match_count: int = 0
    recommended_count: int = 0
    needs_review_count: int = 0
    not_recommended_count: int = 0


class ProjectStatisticsRead(BaseModel):
    project_id: UUID
    total_candidates: int
    average_score: float
    highest_score: float
    lowest_score: float
    knocked_out_count: int
    average_confidence: float
    recommendation_distribution: RecommendationDistribution


class ProjectStatisticsResponse(BaseModel):
    data: ProjectStatisticsRead
