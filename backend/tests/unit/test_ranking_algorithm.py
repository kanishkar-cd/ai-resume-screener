from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.models.scoring import RecommendationLevelEnum
from app.services.ranking.ranking_algorithm import RankingAlgorithm


def _score(final: float, skills: float, experience: float, confidence: float, knocked_out: bool = False, recommendation: RecommendationLevelEnum | None = None):
    return SimpleNamespace(id=uuid4(), document_id=uuid4(), final_score=final, skills_score=skills, experience_score=experience, confidence=confidence, recommendation=recommendation or (RecommendationLevelEnum.REJECT if knocked_out else RecommendationLevelEnum.REVIEW), is_knocked_out=knocked_out)



def test_five_tier_ranking_order_and_history() -> None:
    now = datetime.now(UTC)
    final = _score(95, 50, 50, 50)
    skills = _score(90, 90, 50, 50)
    experience = _score(90, 80, 90, 50)
    confidence = _score(90, 80, 80, 90)
    earlier = _score(90, 80, 80, 80)
    later = _score(90, 80, 80, 80)
    candidates = [(later, now), (earlier, now - timedelta(days=1)), (confidence, now), (experience, now), (skills, now), (final, now)]
    previous = {final.document_id: 3, earlier.document_id: 1}
    ranked = RankingAlgorithm.compute(candidates, previous)
    # Under NEW contract: final (95) comes first; candidates with equal 90 scores follow by timestamp (earlier before later)
    assert ranked[0].document_id == final.document_id
    assert ranked[0].rank_position == 1
    assert ranked[0].final_score == 95.0
    assert ranked[0].previous_rank == 3 and ranked[0].rank_change == 2
    # Check earlier (created at now - 1 day) comes before later (created at now) among equal score 90 items
    earlier_idx = next(i for i, r in enumerate(ranked) if r.document_id == earlier.document_id)
    later_idx = next(i for i, r in enumerate(ranked) if r.document_id == later.document_id)
    assert earlier_idx < later_idx
    assert ranked[earlier_idx].previous_rank == 1 and ranked[earlier_idx].rank_change == (1 - (earlier_idx + 1))


def test_percentile_math_for_cohorts() -> None:
    now = datetime.now(UTC)
    ranked = RankingAlgorithm.compute([(_score(100 - index, 0, 0, 0), now) for index in range(4)])
    assert [item.percentile for item in ranked] == [100, 75, 50, 25]
    assert RankingAlgorithm.compute([(_score(50, 0, 0, 0), now)])[0].percentile == 100


def test_candidates_rank_strictly_by_final_score_descending() -> None:
    now = datetime.now(UTC)
    cand1 = _score(95, 95, 95, 95, knocked_out=True)
    cand2 = _score(72, 70, 70, 70)
    cand3 = _score(58, 58, 58, 58)
    cand4 = _score(40, 40, 40, 40)
    ranked = RankingAlgorithm.compute(
        [(cand1, now), (cand2, now), (cand3, now), (cand4, now)]
    )
    assert [item.document_id for item in ranked] == [
        cand1.document_id, cand2.document_id,
        cand3.document_id, cand4.document_id,
    ]


def test_pure_final_score_sorting_independent_of_legacy_recommendation() -> None:
    now = datetime.now(UTC)
    shortlist = _score(85, 0, 0, 0, recommendation=RecommendationLevelEnum.SHORTLIST)
    review = _score(90, 0, 0, 0, recommendation=RecommendationLevelEnum.REVIEW)
    consider = _score(95, 0, 0, 0, recommendation=RecommendationLevelEnum.CONSIDER)
    score_reject = _score(99, 0, 0, 0, recommendation=RecommendationLevelEnum.REJECT)
    knocked = _score(100, 0, 0, 0, knocked_out=True)
    ranked = RankingAlgorithm.compute([
        (knocked, now), (score_reject, now), (consider, now),
        (review, now), (shortlist, now),
    ])
    assert [item.document_id for item in ranked] == [
        knocked.document_id, score_reject.document_id, consider.document_id,
        review.document_id, shortlist.document_id,
    ]
