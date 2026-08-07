from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.models.scoring import RecommendationLevelEnum
from app.services.insights import InsightBuilder


def test_deterministic_insight_builder() -> None:
    extracted = SimpleNamespace(candidate_name="Jane Doe", designation="Backend Engineer")
    normalized = SimpleNamespace(job_titles=["Backend Engineer"], experience=[{"duration_months": 72}])
    score = SimpleNamespace(
        component_scores={
            "skills": {"score": 90, "matched_items": ["Python"], "missing_items": ["Docker"]},
            "experience": {"score": 85, "matched_items": [], "missing_items": []},
            "projects": {"score": 50, "matched_items": [], "missing_items": []},
            "education": {"score": 100, "matched_items": [], "missing_items": []},
            "certifications": {"score": 40, "matched_items": [], "missing_items": []},
            "languages": {"score": 100, "matched_items": [], "missing_items": []},
        },
        weighted_scores={"skills": 36, "experience": 21.25, "projects": 7.5, "education": 10, "certifications": 2, "languages": 5},
        raw_total_score=77.5, weighted_total_score=81.75, penalty_total=5,
        bonus_total=2, final_score=78.75, confidence=91.67,
        recommendation=RecommendationLevelEnum.REVIEW, is_knocked_out=False,

        knockout_reason=None,
    )
    insight = InsightBuilder().build(uuid4(), uuid4(), extracted, normalized, score, SimpleNamespace(rank_position=2))
    assert "Jane Doe" in insight.summary and "ranked #2" in insight.summary
    assert insight.matched_skills == ["Python"] and insight.missing_skills == ["Docker"]
    assert any("Skills" in item for item in insight.strengths)
    assert any("Certifications" in item for item in insight.weaknesses)
    assert insight.improvement_suggestions[0] == "Develop demonstrable proficiency in Docker."
    assert "Weighted total 81.75" in insight.score_explanation
