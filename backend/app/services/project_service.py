import math
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.exceptions import (
    AppException,
    ConflictException,
    InternalServerException,
    ValidationException,
)
from app.models.project import ProjectStatusEnum
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import (
    ProjectCreate,
    ProjectPaginatedResponse,
    ProjectRead,
    ProjectStatus,
    ProjectUpdate,
)


class ProjectNotFoundException(AppException):
    status_code = 404
    error_code = "PROJECT_NOT_FOUND"
    default_message = "The requested project was not found."


class DuplicateProjectException(ConflictException):
    error_code = "DUPLICATE_PROJECT"
    default_message = "A conflicting project already exists."


class InvalidProjectStatusTransitionException(ConflictException):
    error_code = "INVALID_PROJECT_STATUS_TRANSITION"
    default_message = "Archived projects cannot transition directly to draft."


class ProjectService:
    """Project use cases and lifecycle validation."""

    def __init__(self, repository: ProjectRepository) -> None:
        self.repository = repository

    @staticmethod
    def _sanitize_create(payload: ProjectCreate) -> ProjectCreate:
        title = payload.title.strip()
        target_role = payload.target_role.strip()
        if len(title) < 3 or len(target_role) < 2:
            raise ValidationException(
                "Project title and target role cannot be blank.",
                details={"fields": ["title", "target_role"]},
            )
        return payload.model_copy(update={"title": title, "target_role": target_role})

    @staticmethod
    def _sanitize_update(payload: ProjectUpdate) -> ProjectUpdate:
        updates: dict[str, str] = {}
        if payload.title is not None:
            updates["title"] = payload.title.strip()
        if payload.target_role is not None:
            updates["target_role"] = payload.target_role.strip()
        if "title" in updates and len(updates["title"]) < 3:
            raise ValidationException("Project title cannot be blank.")
        if "target_role" in updates and len(updates["target_role"]) < 2:
            raise ValidationException("Project target role cannot be blank.")
        return payload.model_copy(update=updates)

    async def create_project(self, payload: ProjectCreate) -> ProjectRead:
        try:
            project = await self.repository.create(self._sanitize_create(payload))
        except IntegrityError as exc:
            await self.repository.session.rollback()
            raise DuplicateProjectException() from exc
        except SQLAlchemyError as exc:
            await self.repository.session.rollback()
            raise InternalServerException("Unable to create project.") from exc
        return ProjectRead.model_validate(project)

    async def get_project(self, project_id: UUID) -> ProjectRead:
        try:
            project = await self.repository.get_by_id(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve project.") from exc
        if project is None:
            raise ProjectNotFoundException()
        return ProjectRead.model_validate(project)

    async def list_projects(
        self,
        status: ProjectStatus | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> ProjectPaginatedResponse:
        normalized_search = search.strip() if search else None
        try:
            projects, total = await self.repository.list_projects(
                status, normalized_search, page, page_size
            )
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to list projects.") from exc
        return ProjectPaginatedResponse(
            items=[ProjectRead.model_validate(project) for project in projects],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size),
        )

    async def update_project(
        self, project_id: UUID, payload: ProjectUpdate
    ) -> ProjectRead:
        try:
            existing = await self.repository.get_by_id(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve project.") from exc
        if existing is None:
            raise ProjectNotFoundException()
        if (
            existing.status == ProjectStatusEnum.ARCHIVED
            and payload.status == ProjectStatus.DRAFT
        ):
            raise InvalidProjectStatusTransitionException()
        try:
            project = await self.repository.update(
                project_id, self._sanitize_update(payload)
            )
        except IntegrityError as exc:
            await self.repository.session.rollback()
            raise DuplicateProjectException() from exc
        except SQLAlchemyError as exc:
            await self.repository.session.rollback()
            raise InternalServerException("Unable to update project.") from exc
        if project is None:
            raise ProjectNotFoundException()
        return ProjectRead.model_validate(project)

    async def delete_project(self, project_id: UUID) -> bool:
        try:
            deleted = await self.repository.soft_delete(project_id)
        except SQLAlchemyError as exc:
            await self.repository.session.rollback()
            raise InternalServerException("Unable to delete project.") from exc
        if not deleted:
            raise ProjectNotFoundException()
        return True
