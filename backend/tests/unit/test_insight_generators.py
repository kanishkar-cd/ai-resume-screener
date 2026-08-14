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


def test_not_applicable_components_are_not_strengths_or_weaknesses() -> None:
    extracted = SimpleNamespace(candidate_name="Jane Doe", designation=None)
    normalized = SimpleNamespace(job_titles=[], experience=[])
    score = SimpleNamespace(
        component_scores={
            "skills": {"score": 42.31, "matched_items": [], "missing_items": [], "explanation": "Matched required skills."},
            "experience": {"score": 100, "matched_items": ["3 months"], "missing_items": [], "explanation": "Candidate experience is 3 months against 0 required months."},
            "projects": {"score": 15.38, "matched_items": [], "missing_items": [], "explanation": "Matched project evidence."},
            "education": {"score": 100, "matched_items": [], "missing_items": [], "explanation": "Education meets the configured requirement."},
            "certifications": {"score": 100, "matched_items": [], "missing_items": [], "explanation": "No specific certification requirements configured (N/A)."},
            "languages": {"score": 100, "matched_items": [], "missing_items": [], "explanation": "No specific language requirements configured (N/A)."},
        },
        weighted_scores={"skills": 26.04, "experience": 0, "projects": 3.55, "education": 15.38, "certifications": 0, "languages": 0},
        raw_total_score=52.56, weighted_total_score=44.97, penalty_total=0,
        bonus_total=15, final_score=59.97, confidence=91.67,
        recommendation=RecommendationLevelEnum.CONSIDER, is_knocked_out=False,
        knockout_reason=None,
    )
    insight = InsightBuilder().build(uuid4(), uuid4(), extracted, normalized, score)
    assert insight.strengths == ["Education scored 100.00%."]
    assert insight.weaknesses == ["Skills scored 42.31%.", "Projects scored 15.38%."]
    assert "Experience: No JD requirement" in insight.score_explanation
    assert "Certifications: No JD requirement" in insight.score_explanation
    assert "Languages: No JD requirement" in insight.score_explanation
    assert "recommendation threshold of 50.00" in insight.recommendation_reason
