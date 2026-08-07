from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scoring import CandidateScoreModel, RecommendationLevelEnum
from app.schemas.scoring import CandidateScoreCreate


class ScoringRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_score(self, score_data: CandidateScoreCreate | dict[str, Any]) -> CandidateScoreModel:
        score = CandidateScoreCreate.model_validate(score_data)
        values = score.model_dump(mode="json")
        values["document_id"] = UUID(values["document_id"])
        values["project_id"] = UUID(values["project_id"])
        values["recommendation"] = RecommendationLevelEnum(values["recommendation"])
        components = values["component_scores"]
        values.update({f"{name}_score": detail["score"] for name, detail in components.items()})
        model = await self.get_document_score(values["document_id"])
        if model is None:
            model = CandidateScoreModel(**values)
            self.session.add(model)
        else:
            values.pop("document_id")
            for field, value in values.items(): setattr(model, field, value)
        try:
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        await self.session.refresh(model)
        return model

    async def get_project_scores(self, project_id: UUID) -> list[CandidateScoreModel]:
        result = await self.session.scalars(select(CandidateScoreModel).where(CandidateScoreModel.project_id == project_id).order_by(CandidateScoreModel.created_at.asc()))
        return list(result.all())

    async def get_document_score(self, document_id: UUID) -> CandidateScoreModel | None:
        return await self.session.scalar(select(CandidateScoreModel).where(CandidateScoreModel.document_id == document_id))

    async def delete_project_scores(self, project_id: UUID) -> bool:
        result = await self.session.execute(delete(CandidateScoreModel).where(CandidateScoreModel.project_id == project_id))
        await self.session.commit()
        return bool(result.rowcount)

    create_or_update = upsert_score
    list_by_project_id = get_project_scores
    get_by_document_id = get_document_score
