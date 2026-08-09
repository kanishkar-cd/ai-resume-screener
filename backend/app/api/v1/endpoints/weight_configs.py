from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import DatabaseDependency
from app.repositories.project_repository import ProjectRepository
from app.repositories.weight_config_repository import WeightConfigRepository
from app.schemas.error import ErrorResponsePayload
from app.schemas.weight_config import (
    WeightConfigCreate,
    WeightConfigResponse,
    WeightConfigUpdate,
)
from app.services.weight_config_service import WeightConfigService

router = APIRouter()

NOT_FOUND_RESPONSE = {
    "model": ErrorResponsePayload,
    "description": "The project or weight configuration was not found.",
}

VALIDATION_ERROR_RESPONSE = {
    "model": ErrorResponsePayload,
    "description": "Validation failed (e.g. total weight does not equal 100%).",
}


def get_weight_config_service(db: DatabaseDependency) -> WeightConfigService:
    """Build the request-scoped weight configuration service."""
    return WeightConfigService(
        WeightConfigRepository(db),
        ProjectRepository(db),
    )


WeightConfigServiceDependency = Annotated[
    WeightConfigService, Depends(get_weight_config_service)
]


@router.post(
    "/{project_id}/weight-config",
    response_model=WeightConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save weight configuration",
    description="Create or replace weight configuration for a project. Total criterion weight must equal 100%.",
    responses={
        400: VALIDATION_ERROR_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
    },
)
async def create_weight_config(
    project_id: Annotated[UUID, Path(description="Owning project UUID")],
    payload: WeightConfigCreate,
    service: WeightConfigServiceDependency,
) -> WeightConfigResponse:
    config = await service.create_or_update_weight_config(project_id, payload)
    return WeightConfigResponse(data=config)


@router.get(
    "/{project_id}/weight-config",
    response_model=WeightConfigResponse,
    summary="Get weight configuration",
    description="Retrieve active weight configuration for a project.",
    responses={404: NOT_FOUND_RESPONSE},
)
async def get_weight_config(
    project_id: Annotated[UUID, Path(description="Owning project UUID")],
    service: WeightConfigServiceDependency,
) -> WeightConfigResponse:
    config = await service.get_weight_config(project_id)
    return WeightConfigResponse(data=config)


@router.patch(
    "/{project_id}/weight-config",
    response_model=WeightConfigResponse,
    summary="Update weight configuration",
    description="Partially update weight configuration fields for a project.",
    responses={
        400: VALIDATION_ERROR_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
    },
)
async def update_weight_config(
    project_id: Annotated[UUID, Path(description="Owning project UUID")],
    payload: WeightConfigUpdate,
    service: WeightConfigServiceDependency,
) -> WeightConfigResponse:
    config = await service.update_weight_config(project_id, payload)
    return WeightConfigResponse(data=config)
