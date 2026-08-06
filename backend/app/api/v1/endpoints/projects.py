from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import DatabaseDependency
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectStatus,
    ProjectUpdate,
)
from app.services.project_service import ProjectService

router = APIRouter()


def get_project_service(db: DatabaseDependency) -> ProjectService:
    """Build a request-scoped project service."""
    return ProjectService(ProjectRepository(db))


ProjectServiceDependency = Annotated[ProjectService, Depends(get_project_service)]


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create project",
    description="Create a new hiring campaign project.",
)
async def create_project(
    payload: ProjectCreate, service: ProjectServiceDependency
) -> ProjectResponse:
    return ProjectResponse(data=await service.create_project(payload))


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List projects",
    description="List active projects with pagination, search, and status filtering.",
)
async def list_projects(
    service: ProjectServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_status: Annotated[ProjectStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(min_length=1)] = None,
) -> ProjectListResponse:
    projects = await service.list_projects(
        project_status, search, page, page_size
    )
    return ProjectListResponse(data=projects)


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get project",
    description="Retrieve one active project by UUID.",
)
async def get_project(
    project_id: UUID, service: ProjectServiceDependency
) -> ProjectResponse:
    return ProjectResponse(data=await service.get_project(project_id))


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Update project",
    description="Partially update project fields or lifecycle status.",
)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    service: ProjectServiceDependency,
) -> ProjectResponse:
    return ProjectResponse(data=await service.update_project(project_id, payload))


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete project",
    description="Soft delete a project while retaining its database record.",
)
async def delete_project(
    project_id: UUID, service: ProjectServiceDependency
) -> Response:
    await service.delete_project(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
