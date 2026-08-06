from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentModel, DocumentTypeEnum
from app.models.extracted_info import ExtractedResumeModel
from app.models.insights import CandidateInsightModel
from app.models.normalized_info import NormalizedResumeModel
from app.models.parsed_document import ParsedDocumentModel
from app.models.ranking import CandidateRankingModel
from app.models.scoring import CandidateScoreModel
from app.schemas.insights import CandidateInsightCreate, PipelineStageStatus


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_insight(self, document_id: UUID, insight_data: CandidateInsightCreate | dict[str, Any]) -> CandidateInsightModel:
        data = CandidateInsightCreate.model_validate(insight_data)
        model = await self.get_insight(document_id)
        values = data.model_dump()
        if model is None:
            model = CandidateInsightModel(**values)
            self.session.add(model)
        else:
            values.pop("document_id", None)
            for field, value in values.items(): setattr(model, field, value)
        try: await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        await self.session.refresh(model)
        return model

    async def get_insight(self, document_id: UUID) -> CandidateInsightModel | None:
        return await self.session.scalar(select(CandidateInsightModel).where(CandidateInsightModel.document_id == document_id))

    async def get_pipeline_stage_counts(self, project_id: UUID) -> PipelineStageStatus:
        document_ids = list((await self.session.scalars(select(DocumentModel.id).where(DocumentModel.project_id == project_id, DocumentModel.document_type == DocumentTypeEnum.RESUME, DocumentModel.deleted_at.is_(None)))).all())
        total = len(document_ids)
        async def count(model: Any) -> int:
            if not document_ids: return 0
            return int(await self.session.scalar(select(func.count()).select_from(model).where(model.document_id.in_(document_ids))) or 0)
        return PipelineStageStatus(
            total_candidates=total, candidates_ingested=total,
            candidates_parsed=await count(ParsedDocumentModel), candidates_extracted=await count(ExtractedResumeModel),
            candidates_normalized=await count(NormalizedResumeModel), candidates_scored=await count(CandidateScoreModel),
            candidates_ranked=await count(CandidateRankingModel),
        )

    async def get_skill_frequencies(self, project_id: UUID, top_n: int = 10) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        scores = list((await self.session.scalars(select(CandidateScoreModel).where(CandidateScoreModel.project_id == project_id))).all())
        matched: Counter[str] = Counter()
        missing: Counter[str] = Counter()
        for score in scores:
            skills = (score.component_scores or {}).get("skills", {})
            matched.update(skills.get("matched_items", []))
            missing.update(skills.get("missing_items", []))
        denominator = len(scores)
        def rows(counter: Counter[str]) -> list[dict[str, Any]]:
            return [{"skill_name": skill, "frequency_count": count, "percentage": round(count / denominator * 100, 2) if denominator else 0} for skill, count in counter.most_common(top_n)]
        return rows(matched), rows(missing)

    async def get_campaign_export_rows(self, project_id: UUID) -> list[dict[str, Any]]:
        statement = select(CandidateRankingModel, CandidateScoreModel, ExtractedResumeModel).join(CandidateScoreModel, CandidateScoreModel.id == CandidateRankingModel.candidate_score_id).outerjoin(ExtractedResumeModel, ExtractedResumeModel.document_id == CandidateRankingModel.document_id).where(CandidateRankingModel.project_id == project_id).order_by(CandidateRankingModel.rank_position.asc())
        result = []
        for ranking, score, extracted in (await self.session.execute(statement)).all():
            skills = (score.component_scores or {}).get("skills", {})
            result.append({
                "rank": ranking.rank_position, "document_id": str(ranking.document_id),
                "candidate_name": extracted.candidate_name if extracted and extracted.candidate_name else "Anonymous Candidate",
                "email": extracted.email if extracted else None, "final_score": float(ranking.final_score),
                "recommendation": ranking.recommendation.value, "confidence": float(ranking.confidence),
                "skills_score": float(score.skills_score), "experience_score": float(score.experience_score),
                "matched_skills": skills.get("matched_items", []), "missing_skills": skills.get("missing_items", []),
                "is_knocked_out": score.is_knocked_out, "knockout_reason": score.knockout_reason,
                "created_at": ranking.created_at,
            })
        return result

    async def get_project_timing(self, project_id: UUID, project_created_at: Any) -> tuple[float, Any]:
        last_document = await self.session.scalar(select(func.max(DocumentModel.updated_at)).where(DocumentModel.project_id == project_id))
        last_ranking = await self.session.scalar(select(func.max(CandidateRankingModel.updated_at)).where(CandidateRankingModel.project_id == project_id))
        last_updated = max([value for value in (project_created_at, last_document, last_ranking) if value is not None])
        return max(0.0, (last_updated - project_created_at).total_seconds()), last_updated
