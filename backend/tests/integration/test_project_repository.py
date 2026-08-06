from uuid import uuid4

import pytest

from app.db.session import AsyncSessionLocal
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectStatus, ProjectUpdate


@pytest.mark.asyncio(loop_scope="session")
async def test_project_repository_crud_search_filter_and_soft_delete() -> None:
    marker = uuid4().hex
    async with AsyncSessionLocal() as session:
        repository = ProjectRepository(session)
        created = await repository.create(
            ProjectCreate(
                title=f"Integration {marker}",
                target_role=f"Engineer {marker}",
                status=ProjectStatus.DRAFT,
            )
        )

        fetched = await repository.get_by_id(created.id)
        assert fetched is not None

        projects, total = await repository.list_projects(
            ProjectStatus.DRAFT, marker, page=1, page_size=10
        )
        assert total == 1
        assert projects[0].id == created.id

        updated = await repository.update(
            created.id, ProjectUpdate(status=ProjectStatus.ACTIVE)
        )
        assert updated is not None
        assert updated.status.value == "ACTIVE"

        assert await repository.soft_delete(created.id) is True
        assert await repository.get_by_id(created.id) is None
