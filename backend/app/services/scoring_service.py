import hashlib
import json
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
from app.schemas.scoring import (
    CandidateScoreCreate, CandidateScoreRead, CategoryBreakdownItem,
    ComponentScoreDetail, ComponentScores, ProjectScoringRead, WeightedScores,
)
from app.services.document_service import DocumentNotFoundException
from app.services.project_service import ProjectNotFoundException
from app.services.scoring import (
    BonusService, ComponentScoringService, ConfidenceService, PenaltyService,
    RecommendationService, WeightCalculationService,
)
from app.services.matching_service import EvidenceBuilder, HybridMatchingService, MATCHING_ENGINE_VERSION, RequirementBuilder
from app.services.pipeline.canonical_dictionaries import RULESET_VERSION

logger = structlog.get_logger(__name__)


def compute_score_fingerprint(
    engine_version: str,
    jd_data: Any,
    resume_data: Any,
    experience_level: str,
    weight_config_version: int = 1,
) -> str:
    jd_dict = getattr(jd_data, "data_json", None) if not isinstance(jd_data, dict) else jd_data
    if jd_dict is None:
        jd_dict = getattr(jd_data, "__dict__", str(jd_data or ""))
    resume_dict = getattr(resume_data, "data_json", None) if not isinstance(resume_data, dict) else resume_data
    if resume_dict is None:
        resume_dict = getattr(resume_data, "__dict__", str(resume_data or ""))

    jd_str = json.dumps(jd_dict, sort_keys=True, default=str) if isinstance(jd_dict, dict) else str(jd_dict)
    resume_str = json.dumps(resume_dict, sort_keys=True, default=str) if isinstance(resume_dict, dict) else str(resume_dict)

    raw = f"{engine_version}::{jd_str}::{resume_str}::{str(experience_level).upper()}::{weight_config_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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

    async def score_project(self, project_id: UUID, update_rankings: bool = True) -> ProjectScoringRead:
        logger.info("[SCORE] scoring started", project_id=str(project_id), update_rankings=update_rankings)
        project = await self.projects.get_by_id(project_id)
        exp_level = (
            (project.metadata_json or {}).get("experience_level")
            or (project.metadata_json or {}).get("required_experience_level")
            or "FRESHER"
        ) if project else "FRESHER"
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
                experience_level=exp_level,
            )
            for document in resumes
        ]

        try:
            await self.scores.session.commit()
        except SQLAlchemyError as exc:
            logger.error("[SCORE] commit_failed_rollback", error=str(exc), exc_info=True)
            await self.scores.session.rollback()

        if update_rankings:
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
        project = await self.projects.get_by_id(project_id)
        exp_level = (
            (project.metadata_json or {}).get("experience_level")
            or (project.metadata_json or {}).get("required_experience_level")
            or "FRESHER"
        ) if project else "FRESHER"
        job = await self._load_project_context(project_id)
        document = await self._get_document(document_id)
        if document.project_id != project_id: raise DocumentProjectMismatchException()
        if document.document_type != DocumentTypeEnum.RESUME:
            raise DocumentProjectMismatchException("Only project resumes can be scored.")
        return await self._score(document, job, experience_level=exp_level)

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

        skills_list = getattr(job, "required_skills", None) or (job.data_json.get("required_skills") if isinstance(getattr(job, "data_json", None), dict) else [])
        if getattr(job, "ruleset_version", None) != RULESET_VERSION or not skills_list or len(skills_list) < 6 or len(skills_list) > 10:
            logger.info("[SCORE] Stale or unpopulated job description detected, auto-refreshing JD extraction and normalization", project_id=str(project_id))
            from app.repositories.parsed_document_repository import ParsedDocumentRepository
            from app.repositories.extracted_jd_repository import ExtractedJDRepository
            from app.services.jd_extraction_service import JDExtractionService
            from app.services.jd_normalization_service import JDNormalizationService

            session = self.documents.session
            extracted_jd_repo = ExtractedJDRepository(session)
            jd_extractor = JDExtractionService(
                self.documents,
                ParsedDocumentRepository(session),
                extracted_jd_repo,
            )
            jd_normalizer = JDNormalizationService(
                self.documents,
                extracted_jd_repo,
                self.normalizations,
            )
            try:
                await jd_extractor.extract_document(job_document.id)
            except Exception as exc:
                logger.warning("auto_reextract_skipped", document_id=str(job_document.id), error=str(exc))
            await jd_normalizer.normalize_document(job_document.id)
            await self.scores.session.commit()
            job = await self.normalizations.get_job_description_by_document_id(job_document.id)

        if not getattr(job, "required_skills", None) and not getattr(job, "skills", None):
            raise JobDescriptionMissingException("Job description contains no extractable skill requirements for scoring.")

        return job

    async def _score(
        self, document: DocumentModel, job: Any,
        resume: Any = None, extracted: Any = None,
        experience_level: str | None = None,
    ) -> CandidateScoreRead:
        try:
            if resume is None:
                resume = await self.normalizations.get_resume_by_document_id(document.id)
            if extracted is None:
                extracted = await self.extractions.get_resume_by_document_id(document.id)
            if resume is None or extracted is None: raise NormalizedResumeMissingException()
            try:
                scoring_extracted, match_verdicts = await self.hybrid_matching.match(
                    job, resume, extracted, config=None, experience_level=experience_level
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
            from app.schemas.matching import NormalizedMatchResult
            if isinstance(scoring_extracted, NormalizedMatchResult):
                final_score = round(max(0.0, min(100.0, float(scoring_extracted.final_match_score))), 2)
                is_fresher_formula = scoring_extracted.profile.jd_required_level == "FRESHER"
                rel_exp_score = scoring_extracted.relevant_experience_score if scoring_extracted.relevant_experience_score is not None else 0.0

                components = ComponentScores(
                    skills=ComponentScoreDetail(
                        score=scoring_extracted.required_skills_score,
                        matched_items=scoring_extracted.matched_required_skills,
                        missing_items=scoring_extracted.missing_required_skills,
                        explanation=f"Required Skills match: {scoring_extracted.required_skills_score}% ({len(scoring_extracted.matched_required_skills)} matched).",
                    ),
                    experience=ComponentScoreDetail(
                        score=rel_exp_score,
                        matched_items=[f"{scoring_extracted.profile.total_experience_months} months"],
                        missing_items=[],
                        explanation=f"Candidate level: {scoring_extracted.profile.candidate_level} ({scoring_extracted.profile.total_experience_months} months). JD Required Level: {scoring_extracted.profile.jd_required_level}.",
                    ),
                    projects=ComponentScoreDetail(
                        score=scoring_extracted.responsibility_score,
                        matched_items=[r.responsibility for r in scoring_extracted.responsibility_details if (r.status.value if hasattr(r.status, "value") else str(r.status)) == "MATCHED"],
                        missing_items=[r.responsibility for r in scoring_extracted.responsibility_details if (r.status.value if hasattr(r.status, "value") else str(r.status)) != "MATCHED"],
                        explanation=f"Responsibilities / Projects match: {scoring_extracted.responsibility_score}%.",
                    ),
                    education=ComponentScoreDetail(
                        score=100.0,
                        matched_items=[str(d.get("degree", "")) if isinstance(d, dict) else str(getattr(d, "degree", "")) for d in (scoring_extracted.profile.education or []) if (isinstance(d, dict) and d.get("degree")) or (not isinstance(d, dict) and getattr(d, "degree", None))],
                        missing_items=[],
                        explanation="Education provided for candidate profile (0% score weight).",
                    ),
                    certifications=ComponentScoreDetail(
                        score=scoring_extracted.preferred_skills_score,
                        matched_items=scoring_extracted.matched_preferred_skills,
                        missing_items=scoring_extracted.missing_preferred_skills,
                        explanation=f"Preferred Skills match: {scoring_extracted.preferred_skills_score}%.",
                    ),
                    languages=ComponentScoreDetail(
                        score=scoring_extracted.job_title_score,
                        matched_items=[scoring_extracted.profile.resume_job_title] if scoring_extracted.profile.resume_job_title else [],
                        missing_items=[],
                        explanation=f"Job Title / Role Relevance: {scoring_extracted.job_title_score}%.",
                    ),
                )

                if is_fresher_formula:
                    effective_weights = {"skills": 45.0, "projects": 35.0, "certifications": 10.0, "languages": 10.0, "experience": 0.0, "education": 0.0}
                    weighted = WeightedScores(
                        skills=round(scoring_extracted.required_skills_score * 0.45, 2),
                        projects=round(scoring_extracted.responsibility_score * 0.35, 2),
                        certifications=round(scoring_extracted.preferred_skills_score * 0.10, 2),
                        languages=round(scoring_extracted.job_title_score * 0.10, 2),
                        experience=0.0,
                        education=0.0,
                    )
                else:
                    effective_weights = {"skills": 40.0, "projects": 35.0, "certifications": 10.0, "languages": 5.0, "experience": 10.0, "education": 0.0}
                    weighted = WeightedScores(
                        skills=round(scoring_extracted.required_skills_score * 0.40, 2),
                        projects=round(scoring_extracted.responsibility_score * 0.35, 2),
                        certifications=round(scoring_extracted.preferred_skills_score * 0.10, 2),
                        languages=round(scoring_extracted.job_title_score * 0.05, 2),
                        experience=round(rel_exp_score * 0.10, 2),
                        education=0.0,
                    )

                raw_total = final_score
                weighted_total = final_score
                penalty_total = 0.0
                bonus_total = 0.0
                penalties = []
                bonuses = []
                knocked_out = False
                knockout_reason = None
                applicable_categories = {"skills", "projects", "certifications", "languages"} if is_fresher_formula else {"skills", "projects", "certifications", "languages", "experience"}
            else:
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

            fingerprint = compute_score_fingerprint(
                MATCHING_ENGINE_VERSION, job, resume, experience_level or "FRESHER"
            )

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
                engine_version=MATCHING_ENGINE_VERSION,
                score_fingerprint=fingerprint,
            ), commit=False, refresh=False)
            logger.info(
                "[SCORE] candidate scored",
                project_id=str(document.project_id),
                document_id=str(document.id),
                final_score=final_score,
                component_scores=component_values,
                recommendation=recommendation.value if hasattr(recommendation, "value") else str(recommendation),
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
