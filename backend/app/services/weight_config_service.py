from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppException, InternalServerException
from app.repositories.project_repository import ProjectRepository
from app.repositories.weight_config_repository import WeightConfigRepository
from app.schemas.weight_config import (
    WeightConfigCreate,
    WeightConfigRead,
    WeightConfigUpdate,
)
from app.services.project_service import ProjectNotFoundException

logger = structlog.get_logger(__name__)


class WeightConfigNotFoundException(AppException):
    status_code = 404
    error_code = "WEIGHT_CONFIG_NOT_FOUND"
    default_message = "Weight configuration for this project was not found."


class WeightConfigService:
    def __init__(
        self,
        weight_configs: WeightConfigRepository,
        projects: ProjectRepository,
    ) -> None:
        self.weight_configs = weight_configs
        self.projects = projects

    async def get_weight_config(self, project_id: UUID) -> WeightConfigRead:
        await self._verify_project(project_id)
        try:
            model = await self.weight_configs.get_by_project_id(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve weight configuration.") from exc

        if model is None:
            raise WeightConfigNotFoundException()
        return WeightConfigRead.model_validate(model)

    async def create_or_update_weight_config(
        self,
        project_id: UUID,
        payload: WeightConfigCreate | WeightConfigUpdate,
    ) -> WeightConfigRead:
        await self._verify_project(project_id)
        try:
            model = await self.weight_configs.upsert(project_id, payload)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to save weight configuration.") from exc

        logger.info(
            "[WEIGHT_CONFIG] saved",
            project_id=str(project_id),
            passing_score=float(model.passing_score),
        )
        return WeightConfigRead.model_validate(model)

    async def delete_weight_config(self, project_id: UUID) -> None:
        await self._verify_project(project_id)
        try:
            await self.weight_configs.delete_by_project_id(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to delete weight configuration.") from exc

    async def _verify_project(self, project_id: UUID) -> None:
        try:
            project = await self.projects.get_by_id(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve project.") from exc
        if project is None:
            raise ProjectNotFoundException()
