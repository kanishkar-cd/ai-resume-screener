from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.project import ProjectStatusEnum
from app.schemas.project import ProjectCreate, ProjectStatus, ProjectUpdate
from app.services.project_service import (
    InvalidProjectStatusTransitionException,
    ProjectNotFoundException,
    ProjectService,
)


def project_record(status: ProjectStatusEnum = ProjectStatusEnum.DRAFT) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        title="Backend Campaign",
        description=None,
        target_role="Python Engineer",
        department="Engineering",
        status=status,
        metadata_json={},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_create_sanitizes_title_and_target_role() -> None:
    repository = AsyncMock()
    repository.create.return_value = project_record()
    service = ProjectService(repository)

    await service.create_project(
        ProjectCreate(title="  Backend Campaign  ", target_role=" Python Engineer ")
    )

    saved = repository.create.await_args.args[0]
    assert saved.title == "Backend Campaign"
    assert saved.target_role == "Python Engineer"


@pytest.mark.asyncio
async def test_get_missing_project_raises_project_not_found() -> None:
    repository = AsyncMock()
    repository.get_by_id.return_value = None
    service = ProjectService(repository)

    with pytest.raises(ProjectNotFoundException):
        await service.get_project(uuid4())


@pytest.mark.asyncio
async def test_archived_project_cannot_transition_to_draft() -> None:
    repository = AsyncMock()
    repository.get_by_id.return_value = project_record(ProjectStatusEnum.ARCHIVED)
    service = ProjectService(repository)

    with pytest.raises(InvalidProjectStatusTransitionException):
        await service.update_project(
            uuid4(), ProjectUpdate(status=ProjectStatus.DRAFT)
        )
