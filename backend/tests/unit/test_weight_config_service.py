from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.weight_config import (
    WeightConfigCreate,
    WeightConfigUpdate,
    WeightDistribution,
)
from app.services.project_service import ProjectNotFoundException
from app.services.weight_config_service import (
    WeightConfigNotFoundException,
    WeightConfigService,
)


def weight_config_record() -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        weights={
            "skills": 40,
            "experience": 25,
            "projects": 15,
            "education": 10,
            "certifications": 5,
            "languages": 5,
        },
        passing_score=60.0,
        min_experience_years=0.0,
        required_degree=None,
        required_certifications=[],
        mandatory_skills=[],
        preferred_skills=[],
        knockout_rules=[],
        custom_keywords=[],
        version=1,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_weight_distribution_total_must_equal_100() -> None:
    with pytest.raises(ValidationError) as exc_info:
        WeightDistribution(
            skills=50,
            experience=25,
            projects=15,
            education=10,
            certifications=5,
            languages=5,
        )
    assert "Total criterion weight distribution must equal 100%" in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_weight_config_missing_project_raises_error() -> None:
    repo = AsyncMock()
    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = None

    service = WeightConfigService(repo, project_repo)

    with pytest.raises(ProjectNotFoundException):
        await service.create_or_update_weight_config(uuid4(), WeightConfigCreate())


@pytest.mark.asyncio
async def test_create_or_update_weight_config_success() -> None:
    repo = AsyncMock()
    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = SimpleNamespace(id=uuid4())
    record = weight_config_record()
    repo.upsert.return_value = record

    service = WeightConfigService(repo, project_repo)
    result = await service.create_or_update_weight_config(
        record.project_id, WeightConfigCreate()
    )

    assert result.id == record.id
    assert result.weights.skills == 40
    assert result.weights.experience == 25
    repo.upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_missing_weight_config_raises_not_found() -> None:
    repo = AsyncMock()
    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = SimpleNamespace(id=uuid4())
    repo.get_by_project_id.return_value = None

    service = WeightConfigService(repo, project_repo)

    with pytest.raises(WeightConfigNotFoundException):
        await service.get_weight_config(uuid4())


@pytest.mark.asyncio
async def test_update_weight_config_success() -> None:
    repo = AsyncMock()
    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = SimpleNamespace(id=uuid4())
    record = weight_config_record()
    repo.get_by_project_id.return_value = record

    updated_record = weight_config_record()
    updated_record.version = 2
    updated_record.weights = {
        "skills": 50,
        "experience": 20,
        "projects": 15,
        "education": 5,
        "certifications": 5,
        "languages": 5,
    }
    repo.update.return_value = updated_record

    service = WeightConfigService(repo, project_repo)
    result = await service.update_weight_config(
        record.project_id,
        WeightConfigUpdate(
            weights=WeightDistribution(
                skills=50,
                experience=20,
                projects=15,
                education=5,
                certifications=5,
                languages=5,
            )
        ),
    )

    assert result.version == 2
    assert result.weights.skills == 50
    assert result.weights.experience == 20
