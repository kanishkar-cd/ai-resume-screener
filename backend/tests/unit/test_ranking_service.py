from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.ranking_service import NoScoredCandidatesException, RankingService


class StubProjects:
    async def get_by_id(self, project_id): return SimpleNamespace(id=project_id)


class StubScores:
    async def get_project_scores(self, project_id): return []


@pytest.mark.asyncio
async def test_ranking_service_rejects_project_without_scores() -> None:
    service = RankingService(StubProjects(), SimpleNamespace(), StubScores(), SimpleNamespace())
    with pytest.raises(NoScoredCandidatesException):
        await service.compute_project_rankings(uuid4())
