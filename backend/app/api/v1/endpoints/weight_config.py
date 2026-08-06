from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import DatabaseDependency
from app.repositories.project_repository import ProjectRepository
from app.repositories.weight_config_repository import WeightConfigRepository
from app.schemas.error import ErrorResponsePayload
from app.schemas.weight_config import WeightConfigCreate, WeightConfigResponse, WeightConfigUpdate
from app.services.weight_config_service import WeightConfigService

router = APIRouter()


def get_weight_config_service(db: DatabaseDependency) -> WeightConfigService:
    return WeightConfigService(ProjectRepository(db), WeightConfigRepository(db))


WeightConfigServiceDependency = Annotated[WeightConfigService, Depends(get_weight_config_service)]


@router.post(
    "/{project_id}/weight-config", response_model=WeightConfigResponse,
    status_code=status.HTTP_201_CREATED, summary="Create project weight configuration",
    description="Create or replace the versioned evaluation configuration for a project.",
    responses={404: {"model": ErrorResponsePayload}, 422: {"model": ErrorResponsePayload}},
)
async def create_weight_config(project_id: UUID, payload: WeightConfigCreate, service: WeightConfigServiceDependency) -> WeightConfigResponse:
    return WeightConfigResponse(data=await service.create_weight_config(project_id, payload))


@router.get(
    "/{project_id}/weight-config", response_model=WeightConfigResponse,
    summary="Get project weight configuration",
    responses={404: {"model": ErrorResponsePayload}},
)
async def get_weight_config(project_id: UUID, service: WeightConfigServiceDependency) -> WeightConfigResponse:
    return WeightConfigResponse(data=await service.get_weight_config(project_id))


@router.patch(
    "/{project_id}/weight-config", response_model=WeightConfigResponse,
    summary="Update project weight configuration",
    description="Partially update a configuration and increment its version.",
    responses={404: {"model": ErrorResponsePayload}, 422: {"model": ErrorResponsePayload}},
)
async def update_weight_config(project_id: UUID, payload: WeightConfigUpdate, service: WeightConfigServiceDependency) -> WeightConfigResponse:
    return WeightConfigResponse(data=await service.update_weight_config(project_id, payload))


@router.delete(
    "/{project_id}/weight-config", status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete project weight configuration", responses={404: {"model": ErrorResponsePayload}},
)
async def delete_weight_config(project_id: UUID, service: WeightConfigServiceDependency) -> Response:
    await service.delete_weight_config(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
