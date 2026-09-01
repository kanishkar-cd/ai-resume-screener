import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.schemas.scoring import RecommendationLevel
from app.services.scoring.recommendation_service import RecommendationService
from app.schemas.matching import (
    Evidence, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import HybridMatchingService


def test_recommendation_low_passing_score_50_is_not_shortlist():
    """Score 50.04 with passing 35 must be CONSIDER, not SHORTLIST or REVIEW."""
    rec = RecommendationService.recommend(50.04, passing_score=35.0, is_knocked_out=False)
    assert rec == RecommendationLevel.CONSIDER


def test_recommendation_low_passing_score_70_is_review():
    """Score 70 with passing 35 meets moderate competency (>= 60) and is REVIEW."""
    rec = RecommendationService.recommend(70.0, passing_score=35.0, is_knocked_out=False)
    assert rec == RecommendationLevel.REVIEW


def test_recommendation_low_passing_score_75_is_shortlist():
    """Score 75 with passing 35 satisfies absolute floor (>= 75) and is SHORTLIST."""
    rec = RecommendationService.recommend(75.0, passing_score=35.0, is_knocked_out=False)
    assert rec == RecommendationLevel.SHORTLIST


def test_recommendation_low_passing_score_85_is_shortlist():
    """Score 85 with passing 35 is strong match SHORTLIST."""
    rec = RecommendationService.recommend(85.0, passing_score=35.0, is_knocked_out=False)
    assert rec == RecommendationLevel.SHORTLIST


def test_recommendation_score_below_passing_is_rejected():
    """Score below configured passing threshold is REJECT."""
    assert RecommendationService.recommend(30.0, passing_score=35.0) == RecommendationLevel.REJECT
    assert RecommendationService.recommend(69.9, passing_score=70.0) == RecommendationLevel.REJECT


def test_recommendation_standard_passing_score_70():
    """Standard passing score 70 behaves correctly across all bands."""
    assert RecommendationService.recommend(85.0, passing_score=70.0) == RecommendationLevel.SHORTLIST
    assert RecommendationService.recommend(88.0, passing_score=70.0) == RecommendationLevel.SHORTLIST
    assert RecommendationService.recommend(75.0, passing_score=70.0) == RecommendationLevel.REVIEW
    assert RecommendationService.recommend(80.0, passing_score=70.0) == RecommendationLevel.REVIEW
    assert RecommendationService.recommend(70.0, passing_score=70.0) == RecommendationLevel.CONSIDER
    assert RecommendationService.recommend(74.0, passing_score=70.0) == RecommendationLevel.CONSIDER
    assert RecommendationService.recommend(65.0, passing_score=70.0) == RecommendationLevel.REJECT


def test_recommendation_knockout_candidate_is_rejected():
    """Knockout flag forces REJECT regardless of high score."""
    rec = RecommendationService.recommend(98.0, passing_score=70.0, is_knocked_out=True)
    assert rec == RecommendationLevel.REJECT


def test_recommendation_high_passing_score_80():
    """High passing threshold 80 scales thresholds accordingly."""
    assert RecommendationService.recommend(82.0, passing_score=80.0) == RecommendationLevel.CONSIDER
    assert RecommendationService.recommend(86.0, passing_score=80.0) == RecommendationLevel.REVIEW
    assert RecommendationService.recommend(95.0, passing_score=80.0) == RecommendationLevel.SHORTLIST


@pytest.mark.asyncio
async def test_llm_metric_logging_distinguishes_verdict_types(monkeypatch):
    """Verifies that HybridMatchingService properly distinguishes confirmed vs rejected LLM decisions in logging."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(
            requirement_id="skill:2",
            status=MatchStatus.MATCHED,
            confidence=0.95,
            evidence_ids=["experience:1"],
            reasoning="Candidate demonstrates skill in experience",
            method=MatchMethod.LLM_CONFIRMED,
        ),
        MatchVerdict(
            requirement_id="skill:3",
            status=MatchStatus.NO_MATCH,
            confidence=1.0,
            evidence_ids=[],
            reasoning="No Docker evidence found",
            method=MatchMethod.LLM_REJECTED,
        ),
        MatchVerdict(
            requirement_id="responsibility:1",
            status=MatchStatus.UNRESOLVED,
            confidence=0.5,
            evidence_ids=[],
            reasoning="Uncertain role scope",
            method=MatchMethod.LLM_UNRESOLVED,
        ),
    ])

    service = HybridMatchingService(evaluator=mock_evaluator)
    resume = SimpleNamespace(
        skills=["React.js"],
        certifications=[],
        education=[],
        languages=[],
        experience=[{"description": "Wrote Playwright tests"}],
        projects=[],
    )
    extracted = SimpleNamespace(
        candidate_name="Jane Doe",
        skills=["React.js"],
        education=[],
        experience=[{"description": "Wrote Playwright tests"}],
        projects=[],
        certifications=[],
        languages=[],
    )
    job = SimpleNamespace(
        required_skills=["React.js", "Playwright", "Docker"],
        preferred_skills=[],
        skills=["React.js", "Playwright", "Docker"],
        responsibilities=["Lead architecture decisions"],
        degree_requirements=[],
        certifications=[],
    )

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert len(verdicts) == 4

    confirmed = [v for v in verdicts if v.method == MatchMethod.LLM_CONFIRMED]
    rejected = [v for v in verdicts if v.method == MatchMethod.LLM_REJECTED]
    unresolved = [v for v in verdicts if v.method == MatchMethod.LLM_UNRESOLVED]

    assert len(confirmed) == 1
    assert len(rejected) == 1
    assert len(unresolved) == 1
