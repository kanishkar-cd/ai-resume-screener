from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import InternalServerException
from app.repositories.analytics_repository import AnalyticsRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.ranking_repository import RankingRepository
from app.schemas.insights import (
    ProjectAnalyticsRead, ProjectDashboardRead, ProjectSummary, SkillFrequencyItem,
)
from app.services.pipeline_status_service import PipelineStatusService
from app.services.project_service import ProjectNotFoundException


class DashboardAnalyticsService:
    def __init__(self, projects: ProjectRepository, analytics: AnalyticsRepository, rankings: RankingRepository) -> None:
        self.projects, self.analytics, self.rankings = projects, analytics, rankings
        self.pipeline = PipelineStatusService(analytics)

    async def get_analytics(self, project_id: UUID) -> ProjectAnalyticsRead:
        await self._project(project_id)
        try:
            stats = await self.rankings.get_project_statistics(project_id)
            matched, missing = await self.analytics.get_skill_frequencies(project_id)
            rows = await self.analytics.get_campaign_export_rows(project_id)
        except SQLAlchemyError as exc: raise InternalServerException("Unable to calculate project analytics.") from exc
        distribution = stats["recommendation_distribution"]
        return ProjectAnalyticsRead(
            project_id=project_id, total_candidates=stats["total_candidates"],
            average_score=stats["average_score"], highest_score=stats["highest_score"], lowest_score=stats["lowest_score"],
            average_confidence=stats["average_confidence"],
            recommendation_distribution={
                "STRONG_MATCH": distribution["strong_match_count"], "RECOMMENDED": distribution["recommended_count"],
                "NEEDS_REVIEW": distribution["needs_review_count"], "NOT_RECOMMENDED": distribution["not_recommended_count"],
            },
            top_matched_skills=[SkillFrequencyItem.model_validate(item) for item in matched],
            top_missing_skills=[SkillFrequencyItem.model_validate(item) for item in missing],
            knocked_out_count=stats["knocked_out_count"],
            knocked_out_summary=[{"document_id": row["document_id"], "candidate_name": row["candidate_name"], "reason": row["knockout_reason"]} for row in rows if row["is_knocked_out"]],
        )

    async def get_dashboard(self, project_id: UUID) -> ProjectDashboardRead:
        project = await self._project(project_id)
        analytics = await self.get_analytics(project_id)
        status = await self.pipeline.get_status(project_id)
        rows = await self.analytics.get_campaign_export_rows(project_id)
        processing_time, last_updated = await self.analytics.get_project_timing(project_id, project.created_at)
        return ProjectDashboardRead(
            project_summary=ProjectSummary(project_id=project.id, project_title=project.title, target_role=project.target_role, total_candidates=status.resume_count),
            pipeline_counts=status.stage_counts, analytics=analytics, top_candidates=rows[:10],
            pipeline_completion_percentage=status.completion_percentage,
            processing_time_seconds=round(processing_time, 2), last_updated=last_updated,
        )

    async def get_pipeline_status(self, project_id: UUID):
        await self._project(project_id)
        return await self.pipeline.get_status(project_id)

    async def _project(self, project_id: UUID):
        try: project = await self.projects.get_by_id(project_id)
        except SQLAlchemyError as exc: raise InternalServerException("Unable to retrieve project.") from exc
        if project is None: raise ProjectNotFoundException()
        return project
