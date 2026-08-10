from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.weight_config import WeightConfigModel
from app.schemas.weight_config import WeightConfigCreate, WeightConfigUpdate


class WeightConfigRepository:
    """Async persistence operations for project weight configurations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_project_id(
        self, project_id: UUID
    ) -> WeightConfigModel | None:
        statement = select(WeightConfigModel).where(
            WeightConfigModel.project_id == project_id
        )
        return await self.session.scalar(statement)

    async def upsert(
        self, project_id: UUID, payload: WeightConfigCreate, *, commit: bool = True
    ) -> WeightConfigModel:
        existing = await self.get_by_project_id(project_id)
        data = payload.model_dump()
        weights_dict = data.pop("weights")
        knockout_rules_list = data.pop("knockout_rules")

        if existing is None:
            model = WeightConfigModel(
                project_id=project_id,
                weights=weights_dict,
                knockout_rules=knockout_rules_list,
                version=1,
                **data,
            )
            self.session.add(model)
        else:
            existing.weights = weights_dict
            existing.passing_score = data["passing_score"]
            existing.min_experience_years = data["min_experience_years"]
            existing.required_degree = data["required_degree"]
            existing.required_certifications = data["required_certifications"]
            existing.mandatory_skills = data["mandatory_skills"]
            existing.preferred_skills = data["preferred_skills"]
            existing.knockout_rules = knockout_rules_list
            existing.custom_keywords = data["custom_keywords"]
            existing.version += 1
            model = existing

        if commit:
            await self.session.commit()
            await self.session.refresh(model)
        else:
            await self.session.flush()
            await self.session.refresh(model)
        return model

    async def update(
        self, project_id: UUID, payload: WeightConfigUpdate, *, commit: bool = True
    ) -> WeightConfigModel | None:
        existing = await self.get_by_project_id(project_id)
        if existing is None:
            return None

        update_dict = payload.model_dump(exclude_unset=True)
        if "weights" in update_dict and update_dict["weights"] is not None:
            existing.weights = update_dict.pop("weights")
        if "knockout_rules" in update_dict and update_dict["knockout_rules"] is not None:
            existing.knockout_rules = update_dict.pop("knockout_rules")

        for key, value in update_dict.items():
            if value is not None:
                setattr(existing, key, value)

        existing.version += 1

        if commit:
            await self.session.commit()
            await self.session.refresh(existing)
        else:
            await self.session.flush()
            await self.session.refresh(existing)
        return existing
