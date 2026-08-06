from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.endpoints.projects import get_project_service
from app.main import app
from app.schemas.project import (
    ProjectCreate,
    ProjectPaginatedResponse,
    ProjectRead,
    ProjectStatus,
    ProjectUpdate,
)
from app.services.project_service import ProjectNotFoundException


class FakeProjectService:
    def __init__(self) -> None:
        self.projects: dict[UUID, ProjectRead] = {}

    async def create_project(self, payload: ProjectCreate) -> ProjectRead:
        now = datetime.now(UTC)
        project = ProjectRead(id=uuid4(), created_at=now, updated_at=now, **payload.model_dump())
        self.projects[project.id] = project
        return project

    async def get_project(self, project_id: UUID) -> ProjectRead:
        if project_id not in self.projects:
            raise ProjectNotFoundException()
        return self.projects[project_id]

    async def list_projects(
        self,
        status: ProjectStatus | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> ProjectPaginatedResponse:
        items = list(self.projects.values())
        if status:
            items = [item for item in items if item.status == status]
        if search:
            items = [item for item in items if search.casefold() in item.title.casefold()]
        return ProjectPaginatedResponse(
            items=items, total=len(items), page=page, page_size=page_size,
            total_pages=1 if items else 0,
        )

    async def update_project(self, project_id: UUID, payload: ProjectUpdate) -> ProjectRead:
        project = await self.get_project(project_id)
        updated = project.model_copy(update=payload.model_dump(exclude_unset=True))
        self.projects[project_id] = updated
        return updated

    async def delete_project(self, project_id: UUID) -> bool:
        await self.get_project(project_id)
        del self.projects[project_id]
        return True


@pytest.mark.asyncio
async def test_projects_crud_api(async_client: httpx.AsyncClient) -> None:
    service = FakeProjectService()
    app.dependency_overrides[get_project_service] = lambda: service

    created = await async_client.post(
        "/api/v1/projects",
        json={"title": "API Campaign", "target_role": "Backend Engineer"},
    )
    assert created.status_code == 201
    project_id = created.json()["data"]["id"]

    listed = await async_client.get("/api/v1/projects?status=DRAFT&search=API")
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1

    fetched = await async_client.get(f"/api/v1/projects/{project_id}")
    assert fetched.status_code == 200

    updated = await async_client.patch(
        f"/api/v1/projects/{project_id}", json={"status": "ACTIVE"}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["status"] == "ACTIVE"

    deleted = await async_client.delete(f"/api/v1/projects/{project_id}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    missing = await async_client.get(f"/api/v1/projects/{project_id}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "PROJECT_NOT_FOUND"
