from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import ProjectModel, ProjectStatusEnum
from app.schemas.project import ProjectCreate, ProjectStatus, ProjectUpdate


class ProjectRepository:
    """Async persistence operations for projects."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, project_in: ProjectCreate) -> ProjectModel:
        values = project_in.model_dump()
        values["status"] = ProjectStatusEnum(values["status"])
        project = ProjectModel(**values)
        self.session.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def get_by_id(self, project_id: UUID) -> ProjectModel | None:
        statement = select(ProjectModel).where(
            ProjectModel.id == project_id,
            ProjectModel.deleted_at.is_(None),
        )
        return await self.session.scalar(statement)

    async def list_projects(
        self,
        status: ProjectStatus | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ProjectModel], int]:
        filters = [ProjectModel.deleted_at.is_(None)]
        if status is not None:
            filters.append(ProjectModel.status == ProjectStatusEnum(status.value))
        if search:
            pattern = f"%{search}%"
            filters.append(
                or_(
                    ProjectModel.title.ilike(pattern),
                    ProjectModel.target_role.ilike(pattern),
                )
            )

        total = await self.session.scalar(
            select(func.count()).select_from(ProjectModel).where(*filters)
        )
        result = await self.session.scalars(
            select(ProjectModel)
            .where(*filters)
            .order_by(ProjectModel.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.all()), int(total or 0)

    async def update(
        self, project_id: UUID, update_data: ProjectUpdate
    ) -> ProjectModel | None:
        project = await self.get_by_id(project_id)
        if project is None:
            return None
        values = update_data.model_dump(exclude_unset=True)
        if "status" in values and values["status"] is not None:
            values["status"] = ProjectStatusEnum(values["status"])
        for field, value in values.items():
            setattr(project, field, value)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def soft_delete(self, project_id: UUID) -> bool:
        project = await self.get_by_id(project_id)
        if project is None:
            return False
        project.deleted_at = datetime.now(UTC)
        await self.session.commit()
        return True
