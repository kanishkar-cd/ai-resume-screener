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
        MAP_REC = {
            "STRONG_MATCH": "SHORTLIST",
            "RECOMMENDED": "REVIEW",
            "NEEDS_REVIEW": "CONSIDER",
            "NOT_RECOMMENDED": "REJECT",
            "SHORTLIST": "SHORTLIST",
            "REVIEW": "REVIEW",
            "CONSIDER": "CONSIDER",
            "REJECT": "REJECT",
        }
        for position, (score, _) in enumerate(ordered, start=1):
            previous = previous_ranks.get(score.document_id)
            rec_str = str(getattr(score.recommendation, "value", score.recommendation))
            mapped_rec = MAP_REC.get(rec_str, "CONSIDER")
            rankings.append(CandidateRankingCreate(
                document_id=score.document_id, candidate_score_id=score.id,
                rank_position=position,
                percentile=round((total - position + 1) / total * 100, 2),
                final_score=float(score.final_score),
                skills_score=float(score.skills_score),
                experience_score=float(score.experience_score),
                recommendation=mapped_rec,
                confidence=float(score.confidence), previous_rank=previous,
                rank_change=(previous - position) if previous is not None else 0,
            ))
        return rankings
