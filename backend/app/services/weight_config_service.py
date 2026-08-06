from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppException, InternalServerException
from app.models.weight_config import ProjectWeightConfigModel
from app.repositories.project_repository import ProjectRepository
from app.repositories.weight_config_repository import WeightConfigRepository
from app.schemas.weight_config import (
    WeightConfigCreate, WeightConfigRead, WeightConfigUpdate, WeightDistribution,
)
from app.services.project_service import ProjectNotFoundException
from app.utils.weight_validation import clean_unique, duplicate_values, weight_total


class InvalidWeightTotalException(AppException):
    status_code = 422
    error_code = "INVALID_WEIGHT_TOTAL"
    default_message = "Total weights must sum to exactly 100.0%."


class DuplicateMandatorySkillException(AppException):
    status_code = 422
    error_code = "DUPLICATE_MANDATORY_SKILL"
    default_message = "Duplicate mandatory skills are not allowed."


class InvalidPreferredSkillException(AppException):
    status_code = 422
    error_code = "INVALID_PREFERRED_SKILL"
    default_message = "Preferred skills must be unique and distinct from mandatory skills."


class WeightConfigNotFoundException(AppException):
    status_code = 404
    error_code = "WEIGHT_CONFIG_NOT_FOUND"
    default_message = "No weight configuration exists for this project."


class WeightConfigService:
    def __init__(self, projects: ProjectRepository, configs: WeightConfigRepository) -> None:
        self.projects = projects
        self.configs = configs

    async def create_weight_config(self, project_id: UUID, payload: WeightConfigCreate) -> WeightConfigRead:
        await self._verify_project(project_id)
        validated = self._validate(payload)
        try:
            model = await self.configs.create_or_update(project_id, validated)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to persist weight configuration.") from exc
        return self._read(model)

    async def get_weight_config(self, project_id: UUID) -> WeightConfigRead:
        await self._verify_project(project_id)
        return self._read(await self._get_config(project_id))

    async def update_weight_config(self, project_id: UUID, payload: WeightConfigUpdate) -> WeightConfigRead:
        await self._verify_project(project_id)
        existing = await self._get_config(project_id)
        current = self._create_from_model(existing).model_dump()
        current.update(payload.model_dump(exclude_unset=True))
        validated = self._validate(WeightConfigCreate.model_validate(current))
        try:
            model = await self.configs.create_or_update(project_id, validated)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to update weight configuration.") from exc
        return self._read(model)

    async def delete_weight_config(self, project_id: UUID) -> None:
        await self._verify_project(project_id)
        try:
            deleted = await self.configs.delete_by_project_id(project_id)
        except SQLAlchemyError as exc:
            await self.configs.session.rollback()
            raise InternalServerException("Unable to delete weight configuration.") from exc
        if not deleted:
            raise WeightConfigNotFoundException()

    async def _verify_project(self, project_id: UUID) -> None:
        try:
            project = await self.projects.get_by_id(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve project.") from exc
        if project is None:
            raise ProjectNotFoundException()

    async def _get_config(self, project_id: UUID) -> ProjectWeightConfigModel:
        try:
            model = await self.configs.get_by_project_id(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve weight configuration.") from exc
        if model is None:
            raise WeightConfigNotFoundException()
        return model

    @staticmethod
    def _validate(payload: WeightConfigCreate) -> WeightConfigCreate:
        total = weight_total(payload)
        if abs(total - 100.0) > 0.01:
            raise InvalidWeightTotalException(details={"total": round(total, 2)})
        duplicates = duplicate_values(payload.mandatory_skills)
        if duplicates:
            raise DuplicateMandatorySkillException(details={"duplicates": duplicates})
        preferred_duplicates = duplicate_values(payload.preferred_skills)
        mandatory = {value.strip().casefold() for value in payload.mandatory_skills if value.strip()}
        preferred = {value.strip().casefold() for value in payload.preferred_skills if value.strip()}
        overlap = sorted(mandatory & preferred)
        if preferred_duplicates or overlap:
            raise InvalidPreferredSkillException(details={"duplicates": preferred_duplicates, "mandatory_overlap": overlap})
        return payload.model_copy(update={
            "mandatory_skills": clean_unique(payload.mandatory_skills),
            "preferred_skills": clean_unique(payload.preferred_skills),
            "required_certifications": clean_unique(payload.required_certifications),
            "custom_keywords": clean_unique(payload.custom_keywords),
        })

    @staticmethod
    def _weights(model: ProjectWeightConfigModel) -> WeightDistribution:
        return WeightDistribution(
            skills=float(model.skills_weight), experience=float(model.experience_weight),
            projects=float(model.projects_weight), education=float(model.education_weight),
            certifications=float(model.certifications_weight), languages=float(model.languages_weight),
        )

    @classmethod
    def _create_from_model(cls, model: ProjectWeightConfigModel) -> WeightConfigCreate:
        return WeightConfigCreate(
            weights=cls._weights(model), passing_score=float(model.passing_score),
            min_experience_years=float(model.min_experience_years), required_degree=model.required_degree,
            required_certifications=model.required_certifications, mandatory_skills=model.mandatory_skills,
            preferred_skills=model.preferred_skills, knockout_rules=model.knockout_rules,
            custom_keywords=model.custom_keywords,
        )

    @classmethod
    def _read(cls, model: ProjectWeightConfigModel) -> WeightConfigRead:
        values = cls._create_from_model(model).model_dump()
        return WeightConfigRead(
            id=model.id, project_id=model.project_id, version=model.version,
            created_at=model.created_at, updated_at=model.updated_at, **values,
        )
