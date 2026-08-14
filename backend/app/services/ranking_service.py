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

    async def compute_project_rankings(self, project_id: UUID) -> RankingComputationRead:
        logger.info("[RANK] ranking started", project_id=str(project_id))
        await self._verify_project(project_id)
        try:
            scores = await self.scores.get_project_scores(project_id)
            if not scores:
                # If project scores haven't been generated yet, attempt auto-scoring via ScoringEngineFacade
                try:
                    from app.repositories.extraction_repository import ExtractionRepository
                    from app.repositories.normalization_repository import NormalizationRepository
                    from app.repositories.weight_config_repository import WeightConfigRepository
                    from app.services.scoring_service import ScoringEngineFacade

                    scoring_facade = ScoringEngineFacade(
                        self.projects, self.documents, NormalizationRepository(self.scores.session),
                        ExtractionRepository(self.scores.session), WeightConfigRepository(self.scores.session),
                        self.scores,
                    )
                    await scoring_facade.score_project(project_id)
                    scores = await self.scores.get_project_scores(project_id)
                except Exception as exc:
                    logger.warning("[RANK] auto_scoring_failed", project_id=str(project_id), error=str(exc))

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
