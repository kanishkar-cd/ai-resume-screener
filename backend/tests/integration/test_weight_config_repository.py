from uuid import uuid4

import pytest

from app.db.session import AsyncSessionLocal
from app.repositories.project_repository import ProjectRepository
from app.repositories.weight_config_repository import WeightConfigRepository
from app.schemas.project import ProjectCreate
from app.schemas.weight_config import WeightConfigCreate, WeightDistribution


@pytest.mark.asyncio(loop_scope="session")
async def test_weight_config_repository_upsert_version_and_delete() -> None:
    marker = uuid4().hex
    async with AsyncSessionLocal() as session:
        projects = ProjectRepository(session)
        configs = WeightConfigRepository(session)
        project = await projects.create(ProjectCreate(title=f"Weights {marker}", target_role="Engineer"))
        created = await configs.upsert(project.id, WeightConfigCreate(mandatory_skills=["Python"]))
        original_id = created.id
        updated = await configs.upsert(project.id, WeightConfigCreate(
            weights=WeightDistribution(skills=50, experience=20, projects=10, education=10, certifications=5, languages=5),
            passing_score=80, mandatory_skills=["Python"],
        ))
        assert updated.id == original_id and updated.version == 2
        assert updated.weights["skills"] == 50 and float(updated.passing_score) == 80
        assert await configs.get_by_project_id(project.id) is not None
        await projects.soft_delete(project.id)
