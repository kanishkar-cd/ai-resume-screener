from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.weight_config import WeightConfigModel
from app.schemas.weight_config import WeightConfigCreate, WeightConfigUpdate


class WeightConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_project_id(self, project_id: UUID) -> WeightConfigModel | None:
        return await self.session.scalar(
            select(WeightConfigModel).where(WeightConfigModel.project_id == project_id)
        )

    async def upsert(
        self,
        project_id: UUID,
        payload: WeightConfigCreate | WeightConfigUpdate | dict[str, Any],
        *,
        commit: bool = True,
        refresh: bool = True,
    ) -> WeightConfigModel:
        if isinstance(payload, (WeightConfigCreate, WeightConfigUpdate)):
            values = payload.model_dump(exclude_unset=True, mode="json")
        else:
            values = dict(payload)

        # Convert weights to dict if it's a Pydantic model
        if "weights" in values and hasattr(values["weights"], "model_dump"):
            values["weights"] = values["weights"].model_dump()

        model = await self.get_by_project_id(project_id)
        if model is None:
            if "weights" not in values:
                values["weights"] = {
                    "skills": 40.0,
                    "experience": 25.0,
                    "projects": 15.0,
                    "education": 10.0,
                    "certifications": 5.0,
                    "languages": 5.0,
                }
            if "passing_score" not in values or values["passing_score"] is None:
                values["passing_score"] = 60.0

            db_valid_keys = {c.name for c in WeightConfigModel.__table__.columns}
            model_values = {k: v for k, v in values.items() if k in db_valid_keys and v is not None}
            model_values["project_id"] = project_id
            model = WeightConfigModel(**model_values)
            self.session.add(model)
        else:
            for field, value in values.items():
                if value is not None and hasattr(model, field) and field not in ("id", "project_id", "created_at"):
                    setattr(model, field, value)

        try:
            if commit:
                await self.session.commit()
            else:
                await self.session.flush()
        except SQLAlchemyError:
            await self.session.rollback()
            raise

        if refresh:
            await self.session.refresh(model)
        return model

    async def create(
        self,
        project_id: UUID,
        *,
        passing_score: float = 60.0,
        min_experience_years: float = 0.0,
        weights: dict[str, float] | None = None,
        **kwargs: Any,
    ) -> WeightConfigModel:
        payload = {
            "passing_score": passing_score,
            "min_experience_years": min_experience_years,
            "weights": weights or {},
            **kwargs,
        }
        return await self.upsert(project_id, payload, commit=True, refresh=True)

    async def delete_by_project_id(self, project_id: UUID) -> bool:
        result = await self.session.execute(
            delete(WeightConfigModel).where(WeightConfigModel.project_id == project_id)
        )
        await self.session.commit()
        return bool(result.rowcount)

    create_or_update = upsert
