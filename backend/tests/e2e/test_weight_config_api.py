from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.endpoints.weight_configs import get_weight_config_service
from app.main import app
from app.schemas.weight_config import (
    WeightConfigCreate,
    WeightConfigRead,
    WeightConfigUpdate,
)
from app.services.project_service import ProjectNotFoundException
from app.services.weight_config_service import WeightConfigNotFoundException


class FakeWeightConfigService:
    def __init__(self) -> None:
        self.configs: dict[UUID, WeightConfigRead] = {}
        self.existing_projects: set[UUID] = set()

    async def create_or_update_weight_config(
        self, project_id: UUID, payload: WeightConfigCreate
    ) -> WeightConfigRead:
        if project_id not in self.existing_projects:
            raise ProjectNotFoundException()
        now = datetime.now(UTC)
        existing = self.configs.get(project_id)
        version = existing.version + 1 if existing else 1
        config = WeightConfigRead(
            id=existing.id if existing else uuid4(),
            project_id=project_id,
            version=version,
            created_at=existing.created_at if existing else now,
            updated_at=now,
            **payload.model_dump(),
        )
        self.configs[project_id] = config
        return config

    async def get_weight_config(self, project_id: UUID) -> WeightConfigRead:
        if project_id not in self.existing_projects:
            raise ProjectNotFoundException()
        if project_id not in self.configs:
            raise WeightConfigNotFoundException()
        return self.configs[project_id]

    async def update_weight_config(
        self, project_id: UUID, payload: WeightConfigUpdate
    ) -> WeightConfigRead:
        if project_id not in self.existing_projects:
            raise ProjectNotFoundException()
        if project_id not in self.configs:
            raise WeightConfigNotFoundException()
        current = self.configs[project_id]
        update_data = payload.model_dump(exclude_unset=True)
        updated = current.model_copy(
            update={**update_data, "version": current.version + 1, "updated_at": datetime.now(UTC)}
        )
        self.configs[project_id] = updated
        return updated


@pytest.mark.asyncio
async def test_weight_config_api_flow(async_client: httpx.AsyncClient) -> None:
    service = FakeWeightConfigService()
    project_id = uuid4()
    service.existing_projects.add(project_id)

    app.dependency_overrides[get_weight_config_service] = lambda: service

    # 1. Create weight config
    create_resp = await async_client.post(
        f"/api/v1/projects/{project_id}/weight-config",
        json={
            "weights": {
                "skills": 40,
                "experience": 25,
                "projects": 15,
                "education": 10,
                "certifications": 5,
                "languages": 5,
            }
        },
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["data"]["project_id"] == str(project_id)
    assert create_resp.json()["data"]["weights"]["skills"] == 40

    # 2. Get weight config
    get_resp = await async_client.get(f"/api/v1/projects/{project_id}/weight-config")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["weights"]["experience"] == 25

    # 3. Update weight config
    patch_resp = await async_client.patch(
        f"/api/v1/projects/{project_id}/weight-config",
        json={
            "weights": {
                "skills": 50,
                "experience": 20,
                "projects": 15,
                "education": 5,
                "certifications": 5,
                "languages": 5,
            }
        },
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["data"]["weights"]["skills"] == 50
    assert patch_resp.json()["data"]["version"] == 2

    # 4. Invalid total weight (sum = 110 != 100) -> 422
    invalid_resp = await async_client.post(
        f"/api/v1/projects/{project_id}/weight-config",
        json={
            "weights": {
                "skills": 50,
                "experience": 25,
                "projects": 15,
                "education": 10,
                "certifications": 5,
                "languages": 5,
            }
        },
    )
    assert invalid_resp.status_code == 422

    # 5. Missing project -> 404
    missing_proj_resp = await async_client.get(
        f"/api/v1/projects/{uuid4()}/weight-config"
    )
    assert missing_proj_resp.status_code == 404

    app.dependency_overrides.clear()
