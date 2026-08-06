from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import InternalServerException
from app.repositories.analytics_repository import AnalyticsRepository
from app.repositories.project_repository import ProjectRepository
from app.services.dashboard_analytics_service import DashboardAnalyticsService
from app.services.export_service import ExportService
from app.services.project_service import ProjectNotFoundException


class ReportingService:
    MEDIA = {
        "csv": ("text/csv; charset=utf-8", "report.csv"),
        "excel": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "report.xlsx"),
        "pdf": ("application/pdf", "summary.pdf"),
        "json": ("application/json", "report.json"),
    }

    def __init__(self, projects: ProjectRepository, analytics: AnalyticsRepository, dashboard: DashboardAnalyticsService) -> None:
        self.projects, self.analytics, self.dashboard = projects, analytics, dashboard

    async def generate(self, project_id: UUID, export_format: str) -> tuple[bytes, str, str]:
        try:
            project = await self.projects.get_by_id(project_id)
            if project is None: raise ProjectNotFoundException()
            rows = await self.analytics.get_campaign_export_rows(project_id)
            analytics = (await self.dashboard.get_analytics(project_id)).model_dump(mode="json")
        except ProjectNotFoundException: raise
        except SQLAlchemyError as exc: raise InternalServerException("Unable to retrieve export data.") from exc
        if export_format == "csv": content = ExportService.generate_csv(rows)
        elif export_format == "excel": content = ExportService.generate_excel(rows, analytics)
        elif export_format == "pdf": content = ExportService.generate_pdf(project, rows, analytics)
        else: content = ExportService.generate_json(project, rows, analytics)
        media, suffix = self.MEDIA[export_format]
        filename = f"project_{project_id}_{suffix}"
        return content, media, filename
