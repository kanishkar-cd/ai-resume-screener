from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from app.api.v1.endpoints.reporting import get_dashboard_service, get_insight_service, get_reporting_service
from app.main import app
from app.schemas.insights import (
    CandidateInsightsRead, PipelineStageStatus, PipelineStatusRead,
    ProjectAnalyticsRead, ProjectDashboardRead, ProjectSummary,
)


class FakeDashboard:
    def __init__(self): self.project_id = uuid4()
    def analytics(self): return ProjectAnalyticsRead(project_id=self.project_id, total_candidates=1, average_score=90, highest_score=90, lowest_score=90, average_confidence=95, recommendation_distribution={"STRONG_MATCH": 1}, top_matched_skills=[], top_missing_skills=[], knocked_out_count=0, knocked_out_summary=[])
    def counts(self): return PipelineStageStatus(total_candidates=1, candidates_ingested=1, candidates_parsed=1, candidates_extracted=1, candidates_normalized=1, candidates_scored=1, candidates_ranked=1)
    async def get_analytics(self, project_id): return self.analytics()
    async def get_pipeline_status(self, project_id): return PipelineStatusRead(project_id=project_id, current_stage="COMPLETED", completed_stages=["INGESTION", "PARSING", "EXTRACTION", "NORMALIZATION", "SCORING", "RANKING"], remaining_stages=[], resume_count=1, stage_counts=self.counts(), completion_percentage=100)
    async def get_dashboard(self, project_id): return ProjectDashboardRead(project_summary=ProjectSummary(project_id=project_id, project_title="Campaign", target_role="Engineer", total_candidates=1), pipeline_counts=self.counts(), analytics=self.analytics(), top_candidates=[], pipeline_completion_percentage=100, processing_time_seconds=10, last_updated=datetime.now(UTC))


class FakeInsights:
    document_id = uuid4()
    async def get_candidate_insights(self, document_id): return CandidateInsightsRead(id=uuid4(), document_id=document_id, project_id=uuid4(), summary="Deterministic summary", strengths=["Skills scored 90%."], weaknesses=[], matched_skills=["Python"], missing_skills=[], score_explanation="Score calculation.", recommendation_reason="RECOMMENDED.", improvement_suggestions=[], created_at=datetime.now(UTC), updated_at=datetime.now(UTC))


class FakeReporting:
    async def generate(self, project_id, export_format):
        types = {"csv": (b"a,b\n", "text/csv", "report.csv"), "excel": (b"PK", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "report.xlsx"), "pdf": (b"%PDF", "application/pdf", "summary.pdf"), "json": (b"{}", "application/json", "report.json")}
        return types[export_format]


@pytest.mark.asyncio
async def test_all_reporting_api_contracts(async_client: httpx.AsyncClient) -> None:
    dashboard, insights = FakeDashboard(), FakeInsights()
    app.dependency_overrides[get_dashboard_service] = lambda: dashboard
    app.dependency_overrides[get_insight_service] = lambda: insights
    app.dependency_overrides[get_reporting_service] = lambda: FakeReporting()
    base = f"/api/v1/projects/{dashboard.project_id}"
    assert (await async_client.get(f"{base}/dashboard")).json()["data"]["pipeline_completion_percentage"] == 100
    assert (await async_client.get(f"{base}/analytics")).json()["data"]["average_score"] == 90
    assert (await async_client.get(f"{base}/pipeline-status")).json()["data"]["current_stage"] == "COMPLETED"
    assert (await async_client.get(f"/api/v1/documents/{insights.document_id}/insights")).json()["data"]["matched_skills"] == ["Python"]
    for fmt, media in (("csv", "text/csv"), ("excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), ("pdf", "application/pdf"), ("json", "application/json")):
        response = await async_client.get(f"{base}/export/{fmt}")
        assert response.status_code == 200 and media in response.headers["content-type"] and "attachment" in response.headers["content-disposition"]


def test_stage8_openapi_regression_paths() -> None:
    paths = app.openapi()["paths"]
    for path in (
        "/api/v1/projects/{project_id}/dashboard", "/api/v1/projects/{project_id}/analytics",
        "/api/v1/projects/{project_id}/pipeline-status", "/api/v1/documents/{document_id}/insights",
        "/api/v1/projects/{project_id}/export/csv", "/api/v1/projects/{project_id}/export/excel",
        "/api/v1/projects/{project_id}/export/pdf", "/api/v1/projects/{project_id}/export/json",
        "/api/v1/projects/{project_id}/rank", "/api/v1/projects/{project_id}/score",
    ): assert path in paths
