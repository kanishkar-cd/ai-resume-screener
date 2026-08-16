import math
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppException, InternalServerException
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.ranking_repository import RankingRepository
from app.repositories.scoring_repository import ScoringRepository
from app.schemas.ranking import (
    CandidateRankingRead, ProjectLeaderboardRead, ProjectRankingListRead,
    ProjectStatisticsRead, RankingComputationRead, RankingSortField, RankingSortOrder,
)
from app.schemas.scoring import RecommendationLevel
from app.services.project_service import ProjectNotFoundException
from app.services.ranking import RankingAlgorithm

logger = structlog.get_logger(__name__)


class NoScoredCandidatesException(AppException):
    status_code = 400
    error_code = "NO_SCORED_CANDIDATES"
    default_message = "The project has no scored candidates to rank."


class InvalidRankingFilterException(AppException):
    status_code = 422
    error_code = "INVALID_RANKING_FILTER"
    default_message = "The ranking filters are invalid."


class RankingExecutionFailedException(AppException):
    status_code = 500
    error_code = "RANKING_EXECUTION_FAILED"
    default_message = "Candidate ranking failed."


class RankingService:
    def __init__(self, projects: ProjectRepository, documents: DocumentRepository, scores: ScoringRepository, rankings: RankingRepository) -> None:
        self.projects, self.documents, self.scores, self.rankings = projects, documents, scores, rankings

    async def _verify_project(self, project_id: UUID) -> Any:
        try:
            project = await self.projects.get_by_id(project_id)
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to retrieve project.") from exc
        if project is None:
            raise ProjectNotFoundException()
        return project

    async def compute_project_rankings(self, project_id: UUID, force_rescore: bool = False) -> RankingComputationRead:
        logger.info("[RANK] ranking started", project_id=str(project_id), force_rescore=force_rescore)
        project = await self._verify_project(project_id)
        exp_level = (
            (project.metadata_json or {}).get("experience_level")
            or (project.metadata_json or {}).get("required_experience_level")
            or "FRESHER"
        ) if project else "FRESHER"

        try:
            scores = await self.scores.get_project_scores(project_id)
            resumes, _ = await self.documents.list_resumes_by_project(project_id, 1, 10000)
            resume_doc_ids = {doc.id for doc in resumes}
            scored_doc_ids = {s.document_id for s in scores} if scores else set()

            is_stale = force_rescore or not scores or (len(resume_doc_ids) > 0 and len(scored_doc_ids) < len(resume_doc_ids))

            if not is_stale and scores:
                from app.repositories.normalization_repository import NormalizationRepository
                from app.services.matching_service import MATCHING_ENGINE_VERSION
                from app.services.scoring_service import compute_score_fingerprint

                norm_repo = NormalizationRepository(self.scores.session)
                jd_document = await self.documents.get_job_description_by_project(project_id)
                jd_norm = await norm_repo.get_job_description_by_document_id(jd_document.id) if jd_document else None

                jd_skills = (getattr(jd_norm, "required_skills", None) or (jd_norm.data_json.get("required_skills") if jd_norm and isinstance(getattr(jd_norm, "data_json", None), dict) else [])) if jd_norm else []
                if len(jd_skills) > 10 or (len(jd_skills) <= 6 and any(float(getattr(s, "skills_score", 0) or 0) < 90.0 for s in scores)):
                    is_stale = True

                if not is_stale:
                    project_obj = await self.projects.get_by_id(project_id)
                    exp_level = getattr(project_obj, "experience_level", None) if project_obj else None
                    for s in scores:
                        stored_ver = getattr(s, "engine_version", None)
                        stored_fp = getattr(s, "score_fingerprint", None)
                        if stored_ver != MATCHING_ENGINE_VERSION or not stored_fp:
                            is_stale = True
                            break

                        r_norm = await norm_repo.get_resume_by_document_id(s.document_id)
                        current_fp = compute_score_fingerprint(
                            MATCHING_ENGINE_VERSION, jd_norm, r_norm, exp_level
                        )
                        if stored_fp != current_fp:
                            is_stale = True
                            break

            if is_stale:
                logger.info("[RANK] Stale or missing scores detected; auto-scoring project", project_id=str(project_id))
                try:
                    from app.repositories.extraction_repository import ExtractionRepository
                    from app.repositories.normalization_repository import NormalizationRepository
                    from app.services.scoring_service import ScoringEngineFacade

                    scoring_facade = ScoringEngineFacade(
                        self.projects, self.documents, NormalizationRepository(self.scores.session),
                        ExtractionRepository(self.scores.session),
                        self.scores,
                    )
                    # Pass update_rankings=False to prevent infinite recursion loop
                    await scoring_facade.score_project(project_id, update_rankings=False)
                    self.scores.session.expire_all()
                    scores = await self.scores.get_project_scores(project_id)
                except Exception as exc:
                    logger.error("[RANK] auto_scoring_failed", project_id=str(project_id), error=str(exc), exc_info=True)

            if not scores:
                raise NoScoredCandidatesException("No candidates have been scored for this project yet. Please score candidates before computing rankings.")

            candidates = []
            for score in scores:
                document = await self.documents.get_document(score.document_id)
                if document is not None:
                    candidates.append((score, document.created_at))
            if not candidates:
                raise NoScoredCandidatesException("No candidate documents found for scoring records.")

            existing = await self.rankings.get_existing_rankings(project_id)
            previous = {ranking.document_id: ranking.rank_position for ranking in existing}
            computed = RankingAlgorithm.compute(candidates, previous)
            await self.rankings.bulk_upsert_rankings(project_id, computed)
        except AppException: raise
        except SQLAlchemyError as exc:
            raise InternalServerException("Unable to persist candidate rankings.") from exc
        except Exception as exc:
            raise RankingExecutionFailedException() from exc
        logger.info(
            "[RANK] ranking completed",
            project_id=str(project_id),
            candidate_count=len(computed),
        )
        return RankingComputationRead(project_id=project_id, total_ranked=len(computed), message="Candidate rankings computed successfully.")

    async def list_rankings(
        self, project_id: UUID, *, page: int, page_size: int,
        recommendation: RecommendationLevel | None, min_score: float | None,
        max_score: float | None, is_knocked_out: bool | None, search: str | None,
        sort_by: RankingSortField, order: RankingSortOrder,
    ) -> ProjectRankingListRead:
        await self._verify_project(project_id)
        if min_score is not None and max_score is not None and min_score > max_score:
            raise InvalidRankingFilterException("min_score cannot exceed max_score.")
        try:
            await self.compute_project_rankings(project_id)
        except Exception as exc:
            logger.error("[RANK] auto_freshness_compute_failed", project_id=str(project_id), error=str(exc), exc_info=True)
        self.rankings.session.expire_all()
        filters = {"recommendation": recommendation, "min_score": min_score, "max_score": max_score, "is_knocked_out": is_knocked_out}
        try: rows, total = await self.rankings.list_rankings(project_id, filters, search.strip() if search else None, page, page_size, sort_by, order)
        except SQLAlchemyError as exc: raise InternalServerException("Unable to retrieve rankings.") from exc
        return ProjectRankingListRead(items=[CandidateRankingRead.model_validate(row) for row in rows], total=total, page=page, page_size=page_size, total_pages=math.ceil(total / page_size))

    async def get_leaderboard(self, project_id: UUID, limit: int) -> ProjectLeaderboardRead:
        await self._verify_project(project_id)
        try: rows = await self.rankings.get_top_n_leaderboard(project_id, limit)
        except SQLAlchemyError as exc: raise InternalServerException("Unable to retrieve leaderboard.") from exc
        return ProjectLeaderboardRead(project_id=project_id, top_n=limit, candidates=[CandidateRankingRead.model_validate(row) for row in rows])

    async def get_statistics(self, project_id: UUID) -> ProjectStatisticsRead:
        await self._verify_project(project_id)
        try: data = await self.rankings.get_project_statistics(project_id)
        except SQLAlchemyError as exc: raise InternalServerException("Unable to retrieve ranking statistics.") from exc
        return ProjectStatisticsRead(project_id=project_id, **data)

    async def _verify_project(self, project_id: UUID) -> None:
        try: project = await self.projects.get_by_id(project_id)
        except SQLAlchemyError as exc: raise InternalServerException("Unable to retrieve project.") from exc
        if project is None: raise ProjectNotFoundException()
