from uuid import UUID

import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppException, InternalServerException, ValidationException
from app.repositories.project_repository import ProjectRepository
from app.repositories.weight_config_repository import WeightConfigRepository
from app.schemas.weight_config import (
    WeightConfigCreate,
    WeightConfigRead,
    WeightConfigUpdate,
    WeightDistribution,
)
from app.services.project_service import ProjectNotFoundException

logger = structlog.get_logger(__name__)


class WeightConfigNotFoundException(AppException):
    status_code = 404
    error_code = "WEIGHT_CONFIG_NOT_FOUND"
    default_message = "No weight configuration found for this project."


class WeightConfigService:
    """Service handling project weight configuration logic."""

    def __init__(
        self,
        repository: WeightConfigRepository,
        project_repository: ProjectRepository,
    ) -> None:
        self.repository = repository
        self.project_repository = project_repository

    async def _verify_project(self, project_id: UUID) -> None:
        try:
            project = await self.project_repository.get_by_id(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to verify project ownership.") from exc
        if project is None:
            raise ProjectNotFoundException()

    async def create_or_update_weight_config(
        self, project_id: UUID, payload: WeightConfigCreate
    ) -> WeightConfigRead:
        await self._verify_project(project_id)

        try:
            config = await self.repository.upsert(project_id, payload)
        except SQLAlchemyError as exc:
            await self.repository.session.rollback()
            raise InternalServerException(f"Unable to persist weight configuration: {exc!r}") from exc

        logger.info(
            "weight_config_saved",
            project_id=str(project_id),
            config_id=str(config.id),
            version=config.version,
        )
        return WeightConfigRead.model_validate(config)

    async def get_weight_config(self, project_id: UUID) -> WeightConfigRead:
        await self._verify_project(project_id)

        try:
            config = await self.repository.get_by_project_id(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve weight configuration.") from exc

        if config is None:
            raise WeightConfigNotFoundException()

        return WeightConfigRead.model_validate(config)

    async def update_weight_config(
        self, project_id: UUID, payload: WeightConfigUpdate
    ) -> WeightConfigRead:
        await self._verify_project(project_id)

        existing = await self.repository.get_by_project_id(project_id)
        if existing is None:
            raise WeightConfigNotFoundException()

        # If partial update includes weights, validate merged total weight == 100
        if payload.weights is not None:
            current_weights = dict(existing.weights)
            update_weights = payload.weights.model_dump()
            current_weights.update(update_weights)
            try:
                WeightDistribution(**current_weights)
            except ValueError as val_err:
                raise ValidationException(str(val_err)) from val_err

        try:
            config = await self.repository.update(project_id, payload)
        except SQLAlchemyError as exc:
            await self.repository.session.rollback()
            raise InternalServerException("Unable to update weight configuration.") from exc

        if config is None:
            raise WeightConfigNotFoundException()

        logger.info(
            "weight_config_updated",
            project_id=str(project_id),
            config_id=str(config.id),
            version=config.version,
        )
        return WeightConfigRead.model_validate(config)
