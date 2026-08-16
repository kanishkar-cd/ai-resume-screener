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
from app.schemas.scoring import CandidateScoreCreate, CandidateScoreRead, CategoryBreakdownItem, ProjectScoringRead
from app.services.document_service import DocumentNotFoundException
from app.services.project_service import ProjectNotFoundException
from app.services.scoring import (
    BonusService, ComponentScoringService, ConfidenceService, PenaltyService,
    RecommendationService, WeightCalculationService,
)
from app.services.matching_service import EvidenceBuilder, HybridMatchingService, RequirementBuilder
from app.services.pipeline.canonical_dictionaries import RULESET_VERSION

logger = structlog.get_logger(__name__)


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
        scores: ScoringRepository,
        hybrid_matching: HybridMatchingService | None = None,
    ) -> None:
        self.projects, self.documents = projects, documents
        self.normalizations, self.extractions = normalizations, extractions
        self.scores = scores
        self.components = ComponentScoringService()
        self.hybrid_matching = hybrid_matching or HybridMatchingService()

    async def score_project(self, project_id: UUID) -> ProjectScoringRead:
        logger.info("[SCORE] scoring started", project_id=str(project_id))
        job = await self._load_project_context(project_id)
        try:
            resumes, _ = await self.documents.list_resumes_by_project(project_id, 1, 10000)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve project resumes.") from exc

        doc_ids = [doc.id for doc in resumes]
        logger.info(
            "[SCORE] candidate batch loaded",
            project_id=str(project_id),
            candidate_count=len(resumes),
        )
        try:
            norm_models = await self.normalizations.get_resumes_by_document_ids(doc_ids)
            ext_models = await self.extractions.get_resumes_by_document_ids(doc_ids)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve preloaded candidate records.") from exc

        norm_map = {n.document_id: n for n in norm_models}
        ext_map = {e.document_id: e for e in ext_models}

        results = [
            await self._score(
                document, job,
                resume=norm_map.get(document.id),
                extracted=ext_map.get(document.id),
            )
            for document in resumes
        ]

        try:
            from app.repositories.ranking_repository import RankingRepository
            from app.services.ranking_service import RankingService
            ranking_service = RankingService(
                self.projects, self.documents, self.scores,
                RankingRepository(self.scores.session)
            )
            await ranking_service.compute_project_rankings(project_id)
        except Exception as exc:
            logger.warning("[SCORE] auto_rank_update_failed", project_id=str(project_id), error=str(exc))

        logger.info(
            "[SCORE] scoring completed",
            project_id=str(project_id),
            candidate_count=len(results),
        )
        return ProjectScoringRead(project_id=project_id, total_evaluated=len(results), scores=results)

    async def score_document(self, project_id: UUID, document_id: UUID) -> CandidateScoreRead:
        job = await self._load_project_context(project_id)
        document = await self._get_document(document_id)
        if document.project_id != project_id: raise DocumentProjectMismatchException()
        if document.document_type != DocumentTypeEnum.RESUME:
            raise DocumentProjectMismatchException("Only project resumes can be scored.")
        return await self._score(document, job)

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

    async def _load_project_context(self, project_id: UUID) -> Any:
        await self._verify_project(project_id)
        try:
            job_document = await self.documents.get_job_description_by_project(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve job description document.") from exc
        if job_document is None: raise JobDescriptionMissingException()
        try: job = await self.normalizations.get_job_description_by_document_id(job_document.id)
        except SQLAlchemyError as exc: raise InternalServerException("Unable to retrieve normalized job description.") from exc
        if job is None: raise JobDescriptionMissingException()

        if getattr(job, "ruleset_version", None) != RULESET_VERSION or not getattr(job, "required_skills", None):
            logger.info("[SCORE] Stale or unpopulated job description detected, auto-refreshing JD extraction and normalization", project_id=str(project_id))
            from app.repositories.parsed_document_repository import ParsedDocumentRepository
            from app.repositories.extracted_jd_repository import ExtractedJDRepository
            from app.services.jd_extraction_service import JDExtractionService
            from app.services.jd_normalization_service import JDNormalizationService

            session = self.documents.session
            jd_extractor = JDExtractionService(
                self.documents,
                ParsedDocumentRepository(session),
                ExtractedJDRepository(session),
            )
            jd_normalizer = JDNormalizationService(
                self.documents,
                ExtractedJDRepository(session),
                self.normalizations,
            )
            await jd_extractor.extract_document(job_document.id)
            await jd_normalizer.normalize_document(job_document.id)
            job = await self.normalizations.get_job_description_by_document_id(job_document.id)

        if not getattr(job, "required_skills", None) and not getattr(job, "skills", None):
            raise JobDescriptionMissingException("Job description contains no extractable skill requirements for scoring.")

        return job

    async def _score(
        self, document: DocumentModel, job: Any,
        resume: Any = None, extracted: Any = None,
    ) -> CandidateScoreRead:
        try:
            if resume is None:
                resume = await self.normalizations.get_resume_by_document_id(document.id)
            if extracted is None:
                extracted = await self.extractions.get_resume_by_document_id(document.id)
            if resume is None or extracted is None: raise NormalizedResumeMissingException()
            try:
                scoring_extracted, match_verdicts = await self.hybrid_matching.match(
                    job, resume, extracted, config=None
                )
            except Exception as exc:
                logger.warning(
                    "hybrid_matching_fallback",
                    document_id=str(document.id),
                    error_type=type(exc).__name__,
                )
                scoring_extracted = extracted
                try:
                    requirements = RequirementBuilder.build(job, config=None)
                    evidence = EvidenceBuilder.build(extracted)
                    match_verdicts = []
                    for item in requirements:
                        verdict = self.hybrid_matching.matcher.match(item, resume, evidence)
                        verdict.reasoning = f"{verdict.reasoning} (AI review unavailable)."
                        match_verdicts.append(verdict)
                except Exception:
                    match_verdicts = []
            projects_for_scoring = getattr(scoring_extracted, "projects", None) or getattr(resume, "projects", None) or getattr(extracted, "projects", None)
            components = self.components.score(resume, job, config=None, projects=projects_for_scoring)
            applicable_categories = WeightCalculationService.applicable_categories(job, config=None)
            weighted, raw_total, weighted_total, effective_weights = WeightCalculationService.calculate(
                components, config=None, applicable_categories=applicable_categories
            )
            knocked_out, knockout_reason = WeightCalculationService.knockout(components, config=None)
            penalty_total, penalties = PenaltyService.calculate(components, config=None)
            bonus_total, bonuses = BonusService.calculate(resume, job, config=None, components=components)
            final_score = WeightCalculationService.final_score(
                weighted_total, penalty_total, bonus_total,
                components=components, applicable_categories=applicable_categories
            )
            confidence = ConfidenceService.calculate(extracted)
            passing_score = 70.0
            recommendation = RecommendationService.recommend(final_score, passing_score, knocked_out)
            component_values = {
                name: getattr(components, name).score
                for name in (
                    "skills", "experience", "projects", "education",
                    "certifications", "languages",
                )
            }
            matched_skills = list(components.skills.matched_items)
            missing_skills = list(components.skills.missing_items)

            strengths: list[str] = []
            weaknesses: list[str] = []

            for comp_name in ("skills", "experience", "projects", "education", "certifications"):
                comp_detail = getattr(components, comp_name, None)
                if comp_detail:
                    exp_lower = str(comp_detail.explanation or "").casefold()
                    is_na = "(n/a)" in exp_lower or (comp_name == "experience" and "against 0 required months" in exp_lower)
                    if not is_na:
                        if comp_detail.score >= 80.0 and comp_detail.explanation:
                            strengths.append(f"{comp_name.title()}: {comp_detail.explanation}")
                        elif comp_detail.score < 60.0 and comp_detail.explanation:
                            weaknesses.append(f"{comp_name.title()}: {comp_detail.explanation}")

            if penalties:
                for p in penalties:
                    if p.delta_points < 0:
                        weaknesses.append(f"Penalty: {p.description}")
            if bonuses:
                for b in bonuses:
                    if b.delta_points > 0:
                        strengths.append(f"Bonus: {b.description}")

            score_breakdown = [
                CategoryBreakdownItem(
                    category=name,
                    component_score=getattr(components, name).score,
                    effective_weight=effective_weights.get(name, 0.0),
                    contribution=getattr(weighted, name, 0.0),
                    is_applicable=name in applicable_categories,
                )
                for name in ("skills", "experience", "projects", "education", "certifications", "languages")
            ]

            model = await self.scores.upsert_score(CandidateScoreCreate(
                document_id=document.id, project_id=document.project_id,
                component_scores=components, weighted_scores=weighted,
                raw_total_score=raw_total, weighted_total_score=weighted_total,
                penalty_total=penalty_total, bonus_total=bonus_total, final_score=final_score,
                confidence=confidence, recommendation=recommendation,
                is_knocked_out=knocked_out, knockout_reason=knockout_reason,
                penalty_summary=penalties, bonus_summary=bonuses,
                passing_score=passing_score, effective_weights=effective_weights,
                score_breakdown=score_breakdown,
                weight_config_version=1,
                matched_skills=matched_skills,
                missing_skills=missing_skills,
                strengths=strengths,
                weaknesses=weaknesses,
                match_verdicts=match_verdicts,
            ), commit=False, refresh=False)
            logger.info(
                "[SCORE] candidate scored",
                project_id=str(document.project_id),
                document_id=str(document.id),
                final_score=final_score,
                component_scores=component_values,
                recommendation=recommendation.value,
                is_knocked_out=knocked_out,
            )
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
