from uuid import uuid4

import pytest

from app.schemas.insights import PipelineStageStatus
from app.services.pipeline_status_service import PipelineStatusService


class StubAnalytics:
    async def get_pipeline_stage_counts(self, project_id):
        return PipelineStageStatus(total_candidates=4, candidates_ingested=4, candidates_parsed=4, candidates_extracted=4, candidates_normalized=3, candidates_scored=2, candidates_ranked=1)


@pytest.mark.asyncio
async def test_pipeline_status_current_remaining_and_percentage() -> None:
    status = await PipelineStatusService(StubAnalytics()).get_status(uuid4())
    assert status.current_stage == "NORMALIZATION"
    assert status.completed_stages == ["INGESTION", "PARSING", "EXTRACTION"]
    assert status.remaining_stages == ["NORMALIZATION", "SCORING", "RANKING"]
    assert status.completion_percentage == 75
