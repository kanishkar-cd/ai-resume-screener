from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.deps import DatabaseDependency
from app.repositories.analytics_repository import AnalyticsRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.normalization_repository import NormalizationRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.ranking_repository import RankingRepository
from app.repositories.scoring_repository import ScoringRepository
from app.schemas.error import ErrorResponsePayload
from app.schemas.insights import (
    CandidateInsightsResponse, PipelineStatusResponse, ProjectAnalyticsResponse,
    ProjectDashboardResponse,
)
from app.services.dashboard_analytics_service import DashboardAnalyticsService
from app.services.insights_service import InsightService
from app.services.reporting_service import ReportingService

router = APIRouter()


def get_dashboard_service(db: DatabaseDependency) -> DashboardAnalyticsService:
    return DashboardAnalyticsService(ProjectRepository(db), AnalyticsRepository(db), RankingRepository(db))


def get_insight_service(db: DatabaseDependency) -> InsightService:
    return InsightService(DocumentRepository(db), ExtractionRepository(db), NormalizationRepository(db), ScoringRepository(db), RankingRepository(db), AnalyticsRepository(db))


def get_reporting_service(db: DatabaseDependency) -> ReportingService:
    dashboard = DashboardAnalyticsService(ProjectRepository(db), AnalyticsRepository(db), RankingRepository(db))
    return ReportingService(ProjectRepository(db), AnalyticsRepository(db), dashboard)


DashboardDependency = Annotated[DashboardAnalyticsService, Depends(get_dashboard_service)]
InsightDependency = Annotated[InsightService, Depends(get_insight_service)]
ReportingDependency = Annotated[ReportingService, Depends(get_reporting_service)]
ERRORS = {404: {"model": ErrorResponsePayload}, 500: {"model": ErrorResponsePayload}}


@router.get("/projects/{project_id}/dashboard", response_model=ProjectDashboardResponse, summary="Get project dashboard", description="Return campaign summary, pipeline progress, score analytics, skill gaps, and top candidates.", responses=ERRORS)
async def get_dashboard(project_id: UUID, service: DashboardDependency) -> ProjectDashboardResponse:
    return ProjectDashboardResponse(data=await service.get_dashboard(project_id))


@router.get("/projects/{project_id}/analytics", response_model=ProjectAnalyticsResponse, summary="Get project analytics", responses=ERRORS)
async def get_analytics(project_id: UUID, service: DashboardDependency) -> ProjectAnalyticsResponse:
    return ProjectAnalyticsResponse(data=await service.get_analytics(project_id))


@router.get("/projects/{project_id}/pipeline-status", response_model=PipelineStatusResponse, summary="Get project pipeline status", responses=ERRORS)
async def get_pipeline_status(project_id: UUID, service: DashboardDependency) -> PipelineStatusResponse:
    return PipelineStatusResponse(data=await service.get_pipeline_status(project_id))


@router.get("/documents/{document_id}/insights", response_model=CandidateInsightsResponse, summary="Get deterministic candidate insights", description="Build and cache candidate explanations from Stages 3, 4, 6, and 7 without an LLM.", responses=ERRORS)
async def get_candidate_insights(document_id: UUID, service: InsightDependency) -> CandidateInsightsResponse:
    return CandidateInsightsResponse(data=await service.get_candidate_insights(document_id))


def export_endpoint(export_format: str):
    async def endpoint(project_id: UUID, service: ReportingDependency) -> Response:
        content, media_type, filename = await service.generate(project_id, export_format)
        return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    return endpoint


router.add_api_route("/projects/{project_id}/export/csv", export_endpoint("csv"), methods=["GET"], summary="Export project CSV", responses=ERRORS)
router.add_api_route("/projects/{project_id}/export/excel", export_endpoint("excel"), methods=["GET"], summary="Export project Excel workbook", responses=ERRORS)
router.add_api_route("/projects/{project_id}/export/pdf", export_endpoint("pdf"), methods=["GET"], summary="Export project PDF summary", responses=ERRORS)
router.add_api_route("/projects/{project_id}/export/json", export_endpoint("json"), methods=["GET"], summary="Export project JSON", responses=ERRORS)
