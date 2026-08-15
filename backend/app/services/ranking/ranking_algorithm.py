from datetime import datetime
from typing import Any
from uuid import UUID

from app.schemas.ranking import CandidateRankingCreate


class RankingAlgorithm:
    RECOMMENDATION_PRIORITY = {
        "SHORTLIST": 0,
        "REVIEW": 1,
        "CONSIDER": 2,
        "REJECT": 3,
    }

    @staticmethod
    def compute(
        candidates: list[tuple[Any, datetime]], previous_ranks: dict[UUID, int] | None = None,
    ) -> list[CandidateRankingCreate]:
        previous_ranks = previous_ranks or {}
        ordered = sorted(candidates, key=lambda item: (
            -float(item[0].final_score),
            item[1],
            str(item[0].document_id),
        ))
        total = len(ordered)
        rankings = []
        for position, (score, _) in enumerate(ordered, start=1):
            previous = previous_ranks.get(score.document_id)
            rankings.append(CandidateRankingCreate(
                document_id=score.document_id, candidate_score_id=score.id,
                rank_position=position,
                percentile=round((total - position + 1) / total * 100, 2),
                final_score=float(score.final_score), recommendation=score.recommendation.value,
                confidence=float(score.confidence), previous_rank=previous,
                rank_change=(previous - position) if previous is not None else 0,
            ))
        return rankings
