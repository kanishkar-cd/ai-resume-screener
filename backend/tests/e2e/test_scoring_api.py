from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.endpoints.scoring import get_scoring_facade
from app.main import app
from app.schemas.scoring import (
    CandidateScoreRead, ComponentScoreDetail, ComponentScores, ProjectScoringRead,
    RecommendationLevel, WeightedScores,
)
from app.services.scoring_service import CandidateScoreNotFoundException


class FakeScoringFacade:
    def __init__(self) -> None: self.project_id, self.document_id = uuid4(), uuid4()
    def score(self) -> CandidateScoreRead:
        now = datetime.now(UTC)
        detail = ComponentScoreDetail(score=100, matched_items=["Python"], explanation="Matched requirement.")
        components = ComponentScores(skills=detail, experience=detail, projects=detail, education=detail, certifications=detail, languages=detail)
        return CandidateScoreRead(
            id=uuid4(), document_id=self.document_id, project_id=self.project_id,
            component_scores=components, weighted_scores=WeightedScores(skills=40, experience=25, projects=15, education=10, certifications=5, languages=5),
            raw_total_score=100, weighted_total_score=100, penalty_total=0, bonus_total=0,
            final_score=100, confidence=91.67, recommendation=RecommendationLevel.SHORTLIST,
            weight_config_version=3, skills_score=100, experience_score=100, projects_score=100,
            education_score=100, certifications_score=100, languages_score=100,
            created_at=now, updated_at=now,
        )
    async def score_project(self, project_id: UUID): return ProjectScoringRead(project_id=project_id, total_evaluated=1, scores=[self.score()])
    async def score_document(self, project_id: UUID, document_id: UUID): return self.score()
    async def get_project_scores(self, project_id: UUID): return [self.score()]
    async def get_document_score(self, document_id: UUID):
        if document_id != self.document_id: raise CandidateScoreNotFoundException()
        return self.score()


@pytest.mark.asyncio
async def test_all_scoring_api_contracts(async_client: httpx.AsyncClient) -> None:
    service = FakeScoringFacade()
    app.dependency_overrides[get_scoring_facade] = lambda: service
    bulk = await async_client.post(f"/api/v1/projects/{service.project_id}/score")
    assert bulk.status_code == 200 and bulk.json()["data"]["total_evaluated"] == 1
    single = await async_client.post(f"/api/v1/projects/{service.project_id}/documents/{service.document_id}/score")
    assert single.status_code == 200 and single.json()["data"]["final_score"] == 100
    listed = await async_client.get(f"/api/v1/projects/{service.project_id}/scores")
    assert listed.status_code == 200 and listed.json()["data"][0]["weight_config_version"] == 3
    fetched = await async_client.get(f"/api/v1/documents/{service.document_id}/score")
    assert fetched.status_code == 200 and fetched.json()["data"]["component_scores"]["skills"]["matched_items"] == ["Python"]
    assert (await async_client.get(f"/api/v1/documents/{uuid4()}/score")).status_code == 404


def test_stage6_openapi_and_regression_paths() -> None:
    paths = app.openapi()["paths"]
    for path in (
        "/api/v1/projects/{project_id}/score", "/api/v1/projects/{project_id}/documents/{document_id}/score",
        "/api/v1/projects/{project_id}/scores", "/api/v1/documents/{document_id}/score",
        "/api/v1/projects/{project_id}/weight-config", "/api/v1/documents/{document_id}/normalized",
    ): assert path in paths
