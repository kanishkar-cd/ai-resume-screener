from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.schemas.scoring import RecommendationLevel
from app.services.ranking.ranking_algorithm import RankingAlgorithm


def test_ranking_algorithm_sorts_strictly_by_final_score_descending() -> None:
    doc_a = uuid4()
    doc_b = uuid4()
    doc_c = uuid4()
    now = datetime.now(timezone.utc)

    cand_a = (SimpleNamespace(
        document_id=doc_a, id=uuid4(), final_score=85.0,
        is_knocked_out=True, recommendation=RecommendationLevel.REJECT, confidence=0.5,
    ), now)

    cand_b = (SimpleNamespace(
        document_id=doc_b, id=uuid4(), final_score=72.0,
        is_knocked_out=False, recommendation=RecommendationLevel.SHORTLIST, confidence=0.9,
    ), now)

    cand_c = (SimpleNamespace(
        document_id=doc_c, id=uuid4(), final_score=95.0,
        is_knocked_out=False, recommendation=RecommendationLevel.REVIEW, confidence=0.8,
    ), now)

    rankings = RankingAlgorithm.compute([cand_a, cand_b, cand_c])

    # Candidate C (95.0) -> Position 1
    # Candidate A (85.0) -> Position 2 (even though knocked out / REJECT)
    # Candidate B (72.0) -> Position 3
    assert len(rankings) == 3
    assert rankings[0].document_id == doc_c
    assert rankings[0].rank_position == 1
    assert rankings[0].final_score == 95.0

    assert rankings[1].document_id == doc_a
    assert rankings[1].rank_position == 2
    assert rankings[1].final_score == 85.0

    assert rankings[2].document_id == doc_b
    assert rankings[2].rank_position == 3
    assert rankings[2].final_score == 72.0


def test_higher_final_match_score_ranks_above_lower_score() -> None:
    doc_high = uuid4()
    doc_low = uuid4()
    now = datetime.now(timezone.utc)

    high_score_cand = (SimpleNamespace(
        document_id=doc_high, id=uuid4(), final_score=88.50,
        is_knocked_out=False, recommendation=RecommendationLevel.REVIEW, confidence=0.95,
    ), now)

    low_score_cand = (SimpleNamespace(
        document_id=doc_low, id=uuid4(), final_score=64.20,
        is_knocked_out=False, recommendation=RecommendationLevel.SHORTLIST, confidence=0.95,
    ), now)

    rankings = RankingAlgorithm.compute([low_score_cand, high_score_cand])

    assert rankings[0].document_id == doc_high
    assert rankings[0].rank_position == 1
    assert rankings[1].document_id == doc_low
    assert rankings[1].rank_position == 2
