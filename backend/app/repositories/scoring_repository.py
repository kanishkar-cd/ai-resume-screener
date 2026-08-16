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

    async def upsert_score(self, score_data: CandidateScoreCreate | dict[str, Any], *, commit: bool = True, refresh: bool = True) -> CandidateScoreModel:
        score = CandidateScoreCreate.model_validate(score_data)
        values = score.model_dump(mode="json")
        values["document_id"] = UUID(values["document_id"])
        values["project_id"] = UUID(values["project_id"])
        rec_map = {
            "SHORTLIST": RecommendationLevelEnum.STRONG_MATCH,
            "REVIEW": RecommendationLevelEnum.RECOMMENDED,
            "CONSIDER": RecommendationLevelEnum.NEEDS_REVIEW,
            "REJECT": RecommendationLevelEnum.NOT_RECOMMENDED,
            "STRONG_MATCH": RecommendationLevelEnum.STRONG_MATCH,
            "RECOMMENDED": RecommendationLevelEnum.RECOMMENDED,
            "NEEDS_REVIEW": RecommendationLevelEnum.NEEDS_REVIEW,
            "NOT_RECOMMENDED": RecommendationLevelEnum.NOT_RECOMMENDED,
        }
        rec_val = values["recommendation"]
        rec_str = rec_val.value if hasattr(rec_val, "value") else str(rec_val)
        values["recommendation"] = rec_map.get(rec_str, RecommendationLevelEnum.NEEDS_REVIEW)



        components = values["component_scores"]

        values.update({f"{name}_score": detail["score"] for name, detail in components.items()})

        # Remove optional schema-only helper fields before constructing DB ORM model
        db_valid_keys = {c.name for c in CandidateScoreModel.__table__.columns}
        model_values = {k: v for k, v in values.items() if k in db_valid_keys}

        from datetime import UTC, datetime
        now = datetime.now(UTC)

        model = await self.get_document_score(values["document_id"])
        if model is None:
            model_values["created_at"] = now
            model_values["updated_at"] = now
            model = CandidateScoreModel(**model_values)
            self.session.add(model)
        else:
            model_values.pop("document_id", None)
            if not getattr(model, "created_at", None):
                model.created_at = now
            model.updated_at = now
            for field, value in model_values.items():
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
