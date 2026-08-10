from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.weight_config import WeightConfigCreate, WeightConfigUpdate, WeightDistribution
from app.services.weight_config_service import (
    DuplicateMandatorySkillException, InvalidPreferredSkillException,
    InvalidWeightTotalException, WeightConfigService,
)


def test_valid_weights_equal_exactly_one_hundred() -> None:
    payload = WeightConfigCreate(weights=WeightDistribution(skills=50, experience=20, projects=10, education=10, certifications=5, languages=5))
    assert WeightConfigService._validate(payload).weights.skills == 50


@pytest.mark.parametrize("skills", [35, 45])
def test_invalid_weight_total_is_rejected(skills: int) -> None:
    with pytest.raises((InvalidWeightTotalException, ValueError, ValidationError)):
        WeightConfigCreate(weights=WeightDistribution(skills=skills, experience=20, projects=10, education=10, certifications=5, languages=5))


def test_duplicate_and_preferred_skill_rules_are_case_insensitive() -> None:
    with pytest.raises(DuplicateMandatorySkillException):
        WeightConfigService._validate(WeightConfigCreate(mandatory_skills=["Python", " python "]))
    with pytest.raises(InvalidPreferredSkillException):
        WeightConfigService._validate(WeightConfigCreate(mandatory_skills=["Python"], preferred_skills=["PYTHON"]))
    with pytest.raises(InvalidPreferredSkillException):
        WeightConfigService._validate(WeightConfigCreate(preferred_skills=["SQL", "sql"]))


class StubProjects:
    async def get_by_id(self, project_id): return SimpleNamespace(id=project_id)
    async def get_project(self, project_id): return SimpleNamespace(id=project_id)


class StubConfigs:
    def __init__(self): self.model = None; self.session = SimpleNamespace(rollback=None)
    async def get_by_project_id(self, project_id): return self.model
    async def upsert(self, project_id, payload):
        if self.model is None:
            self.model = SimpleNamespace(
                id=uuid4(),
                project_id=project_id,
                version=1,
                created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                weights=payload.weights.model_dump(),
                passing_score=payload.passing_score,
                min_experience_years=payload.min_experience_years,
                required_degree=payload.required_degree,
                required_certifications=payload.required_certifications,
                mandatory_skills=payload.mandatory_skills,
                preferred_skills=payload.preferred_skills,
                knockout_rules=payload.knockout_rules,
                custom_keywords=payload.custom_keywords,
            )
        else:
            self.model.version += 1
            self.model.weights = payload.weights.model_dump()
            self.model.passing_score = payload.passing_score
            self.model.mandatory_skills = payload.mandatory_skills
        self.model.updated_at = self.model.created_at
        return self.model

    async def update(self, project_id, payload):
        if self.model is not None:
            self.model.version += 1
            if payload.passing_score is not None:
                self.model.passing_score = payload.passing_score
        return self.model


@pytest.mark.asyncio
async def test_partial_patch_preserves_values_and_increments_version() -> None:
    configs = StubConfigs()
    service = WeightConfigService(configs, StubProjects())
    project_id = uuid4()
    created = await service.create_weight_config(project_id, WeightConfigCreate(mandatory_skills=["Python"]))
    updated = await service.update_weight_config(project_id, WeightConfigUpdate(passing_score=80))
    assert created.version == 1 and updated.version == 2
    assert updated.passing_score == 80 and updated.mandatory_skills == ["Python"]
