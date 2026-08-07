from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import DatabaseDependency
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.ranking_repository import RankingRepository
from app.repositories.scoring_repository import ScoringRepository
from app.schemas.error import ErrorResponsePayload
from app.schemas.ranking import (
    ProjectLeaderboardResponse, ProjectRankingListResponse, ProjectStatisticsResponse,
    RankingComputationResponse, RankingSortField, RankingSortOrder,
)
from app.schemas.scoring import RecommendationLevel
from app.services.ranking_service import RankingService

router = APIRouter()


def get_ranking_service(db: DatabaseDependency) -> RankingService:
    return RankingService(ProjectRepository(db), DocumentRepository(db), ScoringRepository(db), RankingRepository(db))


RankingDependency = Annotated[RankingService, Depends(get_ranking_service)]
ERRORS = {400: {"model": ErrorResponsePayload}, 404: {"model": ErrorResponsePayload}, 422: {"model": ErrorResponsePayload}, 500: {"model": ErrorResponsePayload}}


@router.post("/projects/{project_id}/rank", response_model=RankingComputationResponse, summary="Compute project candidate rankings", description="Deterministically rank all Stage 6 candidate scores and preserve prior positions.", responses=ERRORS)
async def rank_project(project_id: UUID, service: RankingDependency) -> RankingComputationResponse:
    return RankingComputationResponse(data=await service.compute_project_rankings(project_id))


@router.get("/projects/{project_id}/rankings", response_model=ProjectRankingListResponse, summary="List project candidate rankings", description="Search, filter, sort, and paginate the persisted project rankings.", responses=ERRORS)
async def list_project_rankings(
    project_id: UUID, service: RankingDependency,
    page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    recommendation: RecommendationLevel | None = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    max_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    is_knocked_out: bool | None = None,
    search: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    sort_by: RankingSortField = RankingSortField.RANK,
    order: RankingSortOrder = RankingSortOrder.ASC,
) -> ProjectRankingListResponse:
    return ProjectRankingListResponse(data=await service.list_rankings(project_id, page=page, page_size=page_size, recommendation=recommendation, min_score=min_score, max_score=max_score, is_knocked_out=is_knocked_out, search=search, sort_by=sort_by, order=order))


@router.get("/projects/{project_id}/leaderboard", response_model=ProjectLeaderboardResponse, summary="Get project leaderboard", responses=ERRORS)
async def get_project_leaderboard(project_id: UUID, service: RankingDependency, limit: Annotated[int, Query(ge=1, le=100)] = 10) -> ProjectLeaderboardResponse:
    return ProjectLeaderboardResponse(data=await service.get_leaderboard(project_id, limit))


@router.get("/projects/{project_id}/statistics", response_model=ProjectStatisticsResponse, summary="Get project ranking statistics", responses=ERRORS)
async def get_project_statistics(project_id: UUID, service: RankingDependency) -> ProjectStatisticsResponse:
    return ProjectStatisticsResponse(data=await service.get_statistics(project_id))
