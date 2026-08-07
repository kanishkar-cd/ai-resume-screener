from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.endpoints.ranking import get_ranking_service
from app.main import app
from app.schemas.ranking import (
    CandidateRankingRead, ProjectLeaderboardRead, ProjectRankingListRead,
    ProjectStatisticsRead, RankingComputationRead, RecommendationDistribution,
)
from app.schemas.scoring import RecommendationLevel
from app.services.ranking_service import NoScoredCandidatesException


class FakeRankingService:
    def __init__(self): self.project_id = uuid4(); self.empty = False
    def candidate(self):
        return CandidateRankingRead(id=uuid4(), project_id=self.project_id, document_id=uuid4(), candidate_name="Jane Doe", email="jane@example.com", rank_position=1, percentile=100, final_score=92, recommendation=RecommendationLevel.STRONG_MATCH, confidence=90, is_knocked_out=False, skills_score=95, experience_score=85, previous_rank=2, rank_change=1, created_at=datetime.now(UTC))
    async def compute_project_rankings(self, project_id):
        if self.empty: raise NoScoredCandidatesException()
        return RankingComputationRead(project_id=project_id, total_ranked=1, message="Candidate rankings computed successfully.")
    async def list_rankings(self, project_id, **kwargs): return ProjectRankingListRead(items=[self.candidate()], total=1, page=kwargs["page"], page_size=kwargs["page_size"], total_pages=1)
    async def get_leaderboard(self, project_id, limit): return ProjectLeaderboardRead(project_id=project_id, top_n=limit, candidates=[self.candidate()])
    async def get_statistics(self, project_id): return ProjectStatisticsRead(project_id=project_id, total_candidates=1, average_score=92, highest_score=92, lowest_score=92, knocked_out_count=0, average_confidence=90, recommendation_distribution=RecommendationDistribution(strong_match_count=1))


@pytest.mark.asyncio
async def test_all_ranking_api_contracts(async_client: httpx.AsyncClient) -> None:
    service = FakeRankingService()
    app.dependency_overrides[get_ranking_service] = lambda: service
    base = f"/api/v1/projects/{service.project_id}"
    ranked = await async_client.post(f"{base}/rank")
    assert ranked.status_code == 200 and ranked.json()["data"]["total_ranked"] == 1
    listed = await async_client.get(f"{base}/rankings?search=jane&recommendation=STRONG_MATCH&min_score=80&sort_by=final_score&order=desc")
    assert listed.status_code == 200 and listed.json()["data"]["items"][0]["rank_change"] == 1
    leaders = await async_client.get(f"{base}/leaderboard?limit=5")
    assert leaders.status_code == 200 and leaders.json()["data"]["top_n"] == 5
    stats = await async_client.get(f"{base}/statistics")
    assert stats.status_code == 200 and stats.json()["data"]["average_confidence"] == 90
    assert (await async_client.get(f"{base}/rankings?min_score=101")).status_code == 422
    service.empty = True
    failed = await async_client.post(f"{base}/rank")
    assert failed.status_code == 400 and failed.json()["error"]["code"] == "NO_SCORED_CANDIDATES"


def test_stage7_openapi_regression_paths() -> None:
    paths = app.openapi()["paths"]
    for path in (
        "/api/v1/projects/{project_id}/rank", "/api/v1/projects/{project_id}/rankings",
        "/api/v1/projects/{project_id}/leaderboard", "/api/v1/projects/{project_id}/statistics",
        "/api/v1/projects/{project_id}/score", "/api/v1/projects/{project_id}/weight-config",
    ): assert path in paths
