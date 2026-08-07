from uuid import UUID

from app.repositories.analytics_repository import AnalyticsRepository
from app.schemas.insights import PipelineStatusRead


class PipelineStatusService:
    STAGES = ("INGESTION", "PARSING", "EXTRACTION", "NORMALIZATION", "SCORING", "RANKING")
    COUNT_FIELDS = ("candidates_ingested", "candidates_parsed", "candidates_extracted", "candidates_normalized", "candidates_scored", "candidates_ranked")

    def __init__(self, analytics: AnalyticsRepository) -> None:
        self.analytics = analytics

    async def get_status(self, project_id: UUID) -> PipelineStatusRead:
        counts = await self.analytics.get_pipeline_stage_counts(project_id)
        total = counts.total_candidates
        values = [getattr(counts, field) for field in self.COUNT_FIELDS]
        completed = [stage for stage, count in zip(self.STAGES, values) if total > 0 and count == total]
        first_incomplete = next((index for index, count in enumerate(values) if total == 0 or count < total), len(self.STAGES) - 1)
        current = "COMPLETED" if total > 0 and len(completed) == len(self.STAGES) else self.STAGES[first_incomplete]
        remaining = [] if current == "COMPLETED" else list(self.STAGES[first_incomplete:])
        percentage = round(sum(values) / (total * len(self.STAGES)) * 100, 2) if total else 0.0
        return PipelineStatusRead(project_id=project_id, current_stage=current, completed_stages=completed, remaining_stages=remaining, resume_count=total, stage_counts=counts, completion_percentage=percentage)
