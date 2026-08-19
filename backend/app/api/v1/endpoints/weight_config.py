from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status

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


def get_weight_config_service(db: DatabaseDependency) -> WeightConfigService:
    return WeightConfigService(
        WeightConfigRepository(db),
        ProjectRepository(db),
    )


WeightConfigServiceDependency = Annotated[
    WeightConfigService, Depends(get_weight_config_service)
]
ProjectId = Annotated[
    UUID, Path(description="Owning project UUID")
]

ERRORS = {
    400: {"model": ErrorResponsePayload, "description": "Invalid weight configuration payload."},
    404: {"model": ErrorResponsePayload, "description": "Project or weight configuration not found."},
    500: {"model": ErrorResponsePayload, "description": "Weight configuration operation failed."},
}


@router.post(
    "/projects/{project_id}/weight-config",
    response_model=WeightConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or initialize weight configuration",
    description="Set custom weights and screening thresholds for a project.",
    responses=ERRORS,
)
async def create_weight_config(
    project_id: ProjectId,
    payload: WeightConfigCreate,
    service: WeightConfigServiceDependency,
) -> WeightConfigResponse:
    return WeightConfigResponse(
        data=await service.create_or_update_weight_config(project_id, payload)
    )


@router.get(
    "/projects/{project_id}/weight-config",
    response_model=WeightConfigResponse,
    summary="Get project weight configuration",
    description="Retrieve the configured weights and screening threshold for a project.",
    responses=ERRORS,
)
async def get_weight_config(
    project_id: ProjectId,
    service: WeightConfigServiceDependency,
) -> WeightConfigResponse:
    return WeightConfigResponse(
        data=await service.get_weight_config(project_id)
    )


@router.patch(
    "/projects/{project_id}/weight-config",
    response_model=WeightConfigResponse,
    summary="Update project weight configuration",
    description="Partially update weights or screening threshold for a project.",
    responses=ERRORS,
)
async def update_weight_config(
    project_id: ProjectId,
    payload: WeightConfigUpdate,
    service: WeightConfigServiceDependency,
) -> WeightConfigResponse:
    return WeightConfigResponse(
        data=await service.create_or_update_weight_config(project_id, payload)
    )


@router.delete(
    "/projects/{project_id}/weight-config",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete project weight configuration",
    description="Reset project weight configuration to defaults.",
    responses=ERRORS,
)
async def delete_weight_config(
    project_id: ProjectId,
    service: WeightConfigServiceDependency,
) -> Response:
    await service.delete_weight_config(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
