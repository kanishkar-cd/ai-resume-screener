from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.weight_config import ProjectWeightConfigModel
from app.schemas.weight_config import WeightConfigCreate


class WeightConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_or_update(self, project_id: UUID, config_in: WeightConfigCreate) -> ProjectWeightConfigModel:
        model = await self.get_by_project_id(project_id)
        values = self._flatten(config_in)
        if model is None:
            model = ProjectWeightConfigModel(project_id=project_id, version=1, **values)
            self.session.add(model)
        else:
            for field, value in values.items():
                setattr(model, field, value)
            model.version += 1
        try:
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        await self.session.refresh(model)
        return model

    async def get_by_project_id(self, project_id: UUID) -> ProjectWeightConfigModel | None:
        return await self.session.scalar(select(ProjectWeightConfigModel).where(ProjectWeightConfigModel.project_id == project_id))

    async def delete_by_project_id(self, project_id: UUID) -> bool:
        result = await self.session.execute(delete(ProjectWeightConfigModel).where(ProjectWeightConfigModel.project_id == project_id))
        await self.session.commit()
        return bool(result.rowcount)

    @staticmethod
    def _flatten(config: WeightConfigCreate) -> dict[str, object]:
        values = config.model_dump(mode="json")
        weights = values.pop("weights")
        values.update({f"{name}_weight": value for name, value in weights.items()})
        return values
