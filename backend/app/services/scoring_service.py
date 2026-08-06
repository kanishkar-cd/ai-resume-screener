from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppException, InternalServerException
from app.models.document import DocumentModel, DocumentTypeEnum
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.normalization_repository import NormalizationRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.scoring_repository import ScoringRepository
from app.repositories.weight_config_repository import WeightConfigRepository
from app.schemas.scoring import CandidateScoreCreate, CandidateScoreRead, ProjectScoringRead
from app.services.document_service import DocumentNotFoundException
from app.services.project_service import ProjectNotFoundException
from app.services.scoring import (
    BonusService, ComponentScoringService, ConfidenceService, PenaltyService,
    RecommendationService, WeightCalculationService,
)

logger = structlog.get_logger(__name__)


class WeightConfigMissingException(AppException):
    status_code = 400
    error_code = "WEIGHT_CONFIG_MISSING"
    default_message = "The project requires a weight configuration before scoring."


class JobDescriptionMissingException(AppException):
    status_code = 400
    error_code = "JOB_DESCRIPTION_MISSING"
    default_message = "The project requires a normalized job description before scoring."


class NormalizedResumeMissingException(AppException):
    status_code = 400
    error_code = "NORMALIZED_RESUME_MISSING"
    default_message = "The resume must be normalized before scoring."


class DocumentProjectMismatchException(AppException):
    status_code = 422
    error_code = "DOCUMENT_PROJECT_MISMATCH"
    default_message = "The resume does not belong to the requested project."


class CandidateScoreNotFoundException(AppException):
    status_code = 404
    error_code = "CANDIDATE_SCORE_NOT_FOUND"
    default_message = "No candidate score exists for this document."


class ScoringFailedException(AppException):
    status_code = 500
    error_code = "SCORING_EXECUTION_FAILED"
    default_message = "Candidate scoring failed."


class ScoringEngineFacade:
    def __init__(
        self, projects: ProjectRepository, documents: DocumentRepository,
        normalizations: NormalizationRepository, extractions: ExtractionRepository,
        weight_configs: WeightConfigRepository, scores: ScoringRepository,
    ) -> None:
        self.projects, self.documents = projects, documents
        self.normalizations, self.extractions = normalizations, extractions
        self.weight_configs, self.scores = weight_configs, scores
        self.components = ComponentScoringService()

    async def score_project(self, project_id: UUID) -> ProjectScoringRead:
        config, job = await self._load_project_context(project_id)
        try:
            resumes, _ = await self.documents.list_resumes_by_project(project_id, 1, 10000)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve project resumes.") from exc
        results = [await self._score(document, config, job) for document in resumes]
        return ProjectScoringRead(project_id=project_id, total_evaluated=len(results), scores=results)

    async def score_document(self, project_id: UUID, document_id: UUID) -> CandidateScoreRead:
        config, job = await self._load_project_context(project_id)
        document = await self._get_document(document_id)
        if document.project_id != project_id: raise DocumentProjectMismatchException()
        if document.document_type != DocumentTypeEnum.RESUME:
            raise DocumentProjectMismatchException("Only project resumes can be scored.")
        return await self._score(document, config, job)

    async def get_project_scores(self, project_id: UUID) -> list[CandidateScoreRead]:
        await self._verify_project(project_id)
        try: models = await self.scores.get_project_scores(project_id)
        except SQLAlchemyError as exc: raise InternalServerException("Unable to retrieve project scores.") from exc
        return [CandidateScoreRead.model_validate(model) for model in models]

    async def get_document_score(self, document_id: UUID) -> CandidateScoreRead:
        await self._get_document(document_id)
        try: model = await self.scores.get_document_score(document_id)
        except SQLAlchemyError as exc: raise InternalServerException("Unable to retrieve candidate score.") from exc
        if model is None: raise CandidateScoreNotFoundException()
        return CandidateScoreRead.model_validate(model)

    async def _load_project_context(self, project_id: UUID) -> tuple[Any, Any]:
        await self._verify_project(project_id)
        try:
            config = await self.weight_configs.get_by_project_id(project_id)
            job_document = await self.documents.get_job_description_by_project(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve scoring configuration.") from exc
        if config is None: raise WeightConfigMissingException()
        if job_document is None: raise JobDescriptionMissingException()
        try: job = await self.normalizations.get_job_description_by_document_id(job_document.id)
        except SQLAlchemyError as exc: raise InternalServerException("Unable to retrieve normalized job description.") from exc
        if job is None: raise JobDescriptionMissingException()
        return config, job

    async def _score(self, document: DocumentModel, config: Any, job: Any) -> CandidateScoreRead:
        try:
            resume = await self.normalizations.get_resume_by_document_id(document.id)
            extracted = await self.extractions.get_resume_by_document_id(document.id)
            if resume is None or extracted is None: raise NormalizedResumeMissingException()
            components = self.components.score(resume, job, config, extracted.projects)
            weighted, raw_total, weighted_total = WeightCalculationService.calculate(components, config)
            knocked_out, knockout_reason = WeightCalculationService.knockout(components, config)
            penalty_total, penalties = PenaltyService.calculate(components, config)
            bonus_total, bonuses = BonusService.calculate(resume, job, config, components)
            final_score = 0.0 if knocked_out else round(max(0, min(100, weighted_total - penalty_total + bonus_total)), 2)
            confidence = ConfidenceService.calculate(extracted)
            recommendation = RecommendationService.recommend(final_score, float(config.passing_score), knocked_out)
            model = await self.scores.upsert_score(CandidateScoreCreate(
                document_id=document.id, project_id=document.project_id,
                component_scores=components, weighted_scores=weighted,
                raw_total_score=raw_total, weighted_total_score=weighted_total,
                penalty_total=penalty_total, bonus_total=bonus_total, final_score=final_score,
                confidence=confidence, recommendation=recommendation,
                is_knocked_out=knocked_out, knockout_reason=knockout_reason,
                penalty_summary=penalties, bonus_summary=bonuses,
                weight_config_version=config.version,
            ))
        except AppException: raise
        except Exception as exc:
            logger.exception("candidate_scoring_failed", document_id=str(document.id))
            raise ScoringFailedException() from exc
        return CandidateScoreRead.model_validate(model)

    async def _verify_project(self, project_id: UUID) -> None:
        try: project = await self.projects.get_by_id(project_id)
        except SQLAlchemyError as exc: raise InternalServerException("Unable to retrieve project.") from exc
        if project is None: raise ProjectNotFoundException()

    async def _get_document(self, document_id: UUID) -> DocumentModel:
        try: document = await self.documents.get_document(document_id)
        except SQLAlchemyError as exc: raise InternalServerException("Unable to retrieve document.") from exc
        if document is None: raise DocumentNotFoundException()
        return document
