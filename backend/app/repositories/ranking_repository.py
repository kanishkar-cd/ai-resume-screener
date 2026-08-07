from typing import Any
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extracted_info import ExtractedResumeModel
from app.models.ranking import CandidateRankingModel
from app.models.scoring import CandidateScoreModel, RecommendationLevelEnum
from app.schemas.ranking import CandidateRankingCreate, RankingSortField, RankingSortOrder


class RankingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_upsert_rankings(self, project_id: UUID, rankings: list[CandidateRankingCreate | dict[str, Any]]) -> bool:
        existing = {model.document_id: model for model in await self.get_existing_rankings(project_id)}
        for model in existing.values():
            model.rank_position += 1_000_000
        await self.session.flush()
        retained: set[UUID] = set()
        for item in rankings:
            data = CandidateRankingCreate.model_validate(item)
            values = data.model_dump()
            values["recommendation"] = RecommendationLevelEnum(data.recommendation.value)





            model = existing.get(data.document_id)
            if model is None:
                model = CandidateRankingModel(project_id=project_id, **values)
                self.session.add(model)
            else:
                for field, value in values.items(): setattr(model, field, value)
            retained.add(data.document_id)
        for document_id, model in existing.items():
            if document_id not in retained: await self.session.delete(model)
        try:
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        return True

    async def get_existing_rankings(self, project_id: UUID) -> list[CandidateRankingModel]:
        result = await self.session.scalars(select(CandidateRankingModel).where(CandidateRankingModel.project_id == project_id))
        return list(result.all())

    async def list_rankings(
        self, project_id: UUID, filters: dict[str, Any], search: str | None,
        page: int, page_size: int, sort_by: RankingSortField, order: RankingSortOrder,
    ) -> tuple[list[dict[str, Any]], int]:
        statement = self._base_query(project_id)
        conditions = self._conditions(filters, search)
        count_statement = select(func.count()).select_from(CandidateRankingModel).join(CandidateScoreModel, CandidateScoreModel.id == CandidateRankingModel.candidate_score_id).outerjoin(ExtractedResumeModel, ExtractedResumeModel.document_id == CandidateRankingModel.document_id).where(CandidateRankingModel.project_id == project_id, *conditions)
        total = int(await self.session.scalar(count_statement) or 0)
        sort_columns = {
            RankingSortField.RANK: CandidateRankingModel.rank_position,
            RankingSortField.SCORE: CandidateRankingModel.final_score,
            RankingSortField.SKILLS: CandidateScoreModel.skills_score,
            RankingSortField.EXPERIENCE: CandidateScoreModel.experience_score,
            RankingSortField.CONFIDENCE: CandidateRankingModel.confidence,
            RankingSortField.CREATED_AT: CandidateRankingModel.created_at,
        }
        column = sort_columns[sort_by]
        ordering = column.asc() if order == RankingSortOrder.ASC else column.desc()
        rows = (await self.session.execute(statement.where(*conditions).order_by(ordering, CandidateRankingModel.rank_position.asc()).offset((page - 1) * page_size).limit(page_size))).all()
        return [self._row(row) for row in rows], total

    async def get_top_n_leaderboard(self, project_id: UUID, limit: int = 10) -> list[dict[str, Any]]:
        rows = (await self.session.execute(self._base_query(project_id).order_by(CandidateRankingModel.rank_position.asc()).limit(limit))).all()
        return [self._row(row) for row in rows]

    async def get_project_statistics(self, project_id: UUID) -> dict[str, Any]:
        totals = (await self.session.execute(
            select(
                func.count(CandidateRankingModel.id), func.avg(CandidateRankingModel.final_score),
                func.max(CandidateRankingModel.final_score), func.min(CandidateRankingModel.final_score),
                func.avg(CandidateRankingModel.confidence),
                func.sum(case((CandidateScoreModel.is_knocked_out.is_(True), 1), else_=0)),
            ).join(CandidateScoreModel, CandidateScoreModel.id == CandidateRankingModel.candidate_score_id).where(CandidateRankingModel.project_id == project_id)
        )).one()
        distribution_rows = (await self.session.execute(
            select(CandidateRankingModel.recommendation, func.count(CandidateRankingModel.id)).where(CandidateRankingModel.project_id == project_id).group_by(CandidateRankingModel.recommendation)
        )).all()
        distribution = {recommendation.value: int(count) for recommendation, count in distribution_rows}
        return {
            "total_candidates": int(totals[0] or 0), "average_score": round(float(totals[1] or 0), 2),
            "highest_score": round(float(totals[2] or 0), 2), "lowest_score": round(float(totals[3] or 0), 2),
            "average_confidence": round(float(totals[4] or 0), 2), "knocked_out_count": int(totals[5] or 0),
            "recommendation_distribution": {
                "strong_match_count": distribution.get("STRONG_MATCH", 0),
                "recommended_count": distribution.get("RECOMMENDED", 0),
                "needs_review_count": distribution.get("NEEDS_REVIEW", 0),
                "not_recommended_count": distribution.get("NOT_RECOMMENDED", 0),
            },
        }

    @staticmethod
    def _base_query(project_id: UUID):
        return select(CandidateRankingModel, CandidateScoreModel, ExtractedResumeModel).join(CandidateScoreModel, CandidateScoreModel.id == CandidateRankingModel.candidate_score_id).outerjoin(ExtractedResumeModel, ExtractedResumeModel.document_id == CandidateRankingModel.document_id).where(CandidateRankingModel.project_id == project_id)

    @staticmethod
    def _conditions(filters: dict[str, Any], search: str | None) -> list[Any]:
        conditions = []
        if filters.get("recommendation") is not None:
            conditions.append(CandidateRankingModel.recommendation == RecommendationLevelEnum(filters["recommendation"].value))
        if filters.get("min_score") is not None: conditions.append(CandidateRankingModel.final_score >= filters["min_score"])
        if filters.get("max_score") is not None: conditions.append(CandidateRankingModel.final_score <= filters["max_score"])
        if filters.get("is_knocked_out") is not None: conditions.append(CandidateScoreModel.is_knocked_out == filters["is_knocked_out"])
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            conditions.append(or_(ExtractedResumeModel.candidate_name.ilike(pattern, escape="\\"), ExtractedResumeModel.email.ilike(pattern, escape="\\")))
        return conditions

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        ranking, score, extracted = row
        return {
            "id": ranking.id, "project_id": ranking.project_id, "document_id": ranking.document_id,
            "candidate_name": extracted.candidate_name if extracted and extracted.candidate_name else "Anonymous Candidate",
            "email": extracted.email if extracted else None, "rank_position": ranking.rank_position,
            "percentile": float(ranking.percentile), "final_score": float(ranking.final_score),
            "recommendation": ranking.recommendation.value, "confidence": float(ranking.confidence),
            "is_knocked_out": score.is_knocked_out, "skills_score": float(score.skills_score),
            "experience_score": float(score.experience_score), "previous_rank": ranking.previous_rank,
            "rank_change": ranking.rank_change, "created_at": ranking.created_at,
        }
