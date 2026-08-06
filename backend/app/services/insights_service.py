from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppException, InternalServerException
from app.repositories.analytics_repository import AnalyticsRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.normalization_repository import NormalizationRepository
from app.repositories.ranking_repository import RankingRepository
from app.repositories.scoring_repository import ScoringRepository
from app.schemas.insights import CandidateInsightsRead
from app.services.insights import InsightBuilder


class InsightsNotFoundException(AppException):
    status_code = 404
    error_code = "INSIGHTS_NOT_FOUND"
    default_message = "Complete candidate data is unavailable for insights."


class InsightService:
    def __init__(self, documents: DocumentRepository, extractions: ExtractionRepository, normalizations: NormalizationRepository, scores: ScoringRepository, rankings: RankingRepository, analytics: AnalyticsRepository) -> None:
        self.documents, self.extractions, self.normalizations = documents, extractions, normalizations
        self.scores, self.rankings, self.analytics = scores, rankings, analytics

    async def get_candidate_insights(self, document_id: UUID) -> CandidateInsightsRead:
        try:
            document = await self.documents.get_document(document_id)
            if document is None: raise InsightsNotFoundException()
            extracted = await self.extractions.get_resume_by_document_id(document_id)
            normalized = await self.normalizations.get_resume_by_document_id(document_id)
            score = await self.scores.get_document_score(document_id)
            if extracted is None or normalized is None or score is None: raise InsightsNotFoundException()
            rank = next((item for item in await self.rankings.get_existing_rankings(document.project_id) if item.document_id == document_id), None)
            data = InsightBuilder().build(document_id, document.project_id, extracted, normalized, score, rank)
            model = await self.analytics.get_or_create_insight(document_id, data)
        except AppException: raise
        except SQLAlchemyError as exc: raise InternalServerException("Unable to generate candidate insights.") from exc
        return CandidateInsightsRead.model_validate(model)
