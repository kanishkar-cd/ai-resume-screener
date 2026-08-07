from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.endpoints.weight_config import get_weight_config_service
from app.main import app
from app.schemas.weight_config import (
    WeightConfigCreate, WeightConfigRead, WeightConfigUpdate, WeightDistribution,
)
from app.services.weight_config_service import WeightConfigNotFoundException, WeightConfigService


class FakeWeightConfigService:
    def __init__(self) -> None: self.project_id = uuid4(); self.config = None
    def _read(self, project_id: UUID, version: int, passing_score: float = 70) -> WeightConfigRead:
        now = datetime.now(UTC)
        return WeightConfigRead(id=uuid4(), project_id=project_id, weights=WeightDistribution(), passing_score=passing_score, min_experience_years=0, required_degree=None, required_certifications=[], mandatory_skills=["Python"], preferred_skills=[], knockout_rules=[], custom_keywords=[], version=version, created_at=now, updated_at=now)
    async def create_weight_config(self, project_id: UUID, payload: WeightConfigCreate) -> WeightConfigRead:
        payload = WeightConfigService._validate(payload)
        self.config = self._read(project_id, 1, payload.passing_score); return self.config
    async def get_weight_config(self, project_id: UUID) -> WeightConfigRead:
        if self.config is None: raise WeightConfigNotFoundException()
        return self.config
    async def update_weight_config(self, project_id: UUID, payload: WeightConfigUpdate) -> WeightConfigRead:
        if self.config is None: raise WeightConfigNotFoundException()
        self.config = self._read(project_id, self.config.version + 1, payload.passing_score or self.config.passing_score); return self.config
    async def delete_weight_config(self, project_id: UUID) -> None:
        if self.config is None: raise WeightConfigNotFoundException()
        self.config = None


@pytest.mark.asyncio
async def test_weight_config_crud_api(async_client: httpx.AsyncClient) -> None:
    service = FakeWeightConfigService()
    app.dependency_overrides[get_weight_config_service] = lambda: service
    path = f"/api/v1/projects/{service.project_id}/weight-config"
    created = await async_client.post(path, json={"mandatory_skills": ["Python"]})
    assert created.status_code == 201 and created.json()["data"]["version"] == 1
    assert (await async_client.get(path)).status_code == 200
    updated = await async_client.patch(path, json={"passing_score": 80})
    assert updated.status_code == 200 and updated.json()["data"]["version"] == 2
    assert updated.json()["data"]["passing_score"] == 80
    assert (await async_client.delete(path)).status_code == 204
    assert (await async_client.get(path)).status_code == 404


@pytest.mark.asyncio
async def test_weight_config_request_bounds(async_client: httpx.AsyncClient) -> None:
    service = FakeWeightConfigService()
    app.dependency_overrides[get_weight_config_service] = lambda: service
    path = f"/api/v1/projects/{service.project_id}/weight-config"
    assert (await async_client.post(path, json={"passing_score": 101})).status_code == 422
    assert (await async_client.post(path, json={"weights": {"skills": 101}})).status_code == 422
    invalid_total = await async_client.post(path, json={"weights": {"skills": 35}})
    assert invalid_total.status_code == 422
    assert invalid_total.json()["error"]["code"] == "INVALID_WEIGHT_TOTAL"
    duplicates = await async_client.post(path, json={"mandatory_skills": ["Python", " python "]})
    assert duplicates.status_code == 422
    assert duplicates.json()["error"]["code"] == "DUPLICATE_MANDATORY_SKILL"


def test_weight_config_openapi_preserves_previous_stages() -> None:
    paths = app.openapi()["paths"]
    assert set(paths["/api/v1/projects/{project_id}/weight-config"]) >= {"post", "get", "patch", "delete"}
    assert "/api/v1/documents/{document_id}/normalized" in paths
