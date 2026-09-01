import pytest
from types import SimpleNamespace
from uuid import uuid4

from app.models.scoring import RecommendationLevelEnum
from app.services.insights import InsightBuilder
from app.services.scoring.weight_calculation_service import WeightCalculationService


def test_phase5_meera_iyer_score_explanation_and_final_score():
    """Verify Meera Iyer evaluation produces direct 2.78/100 without 50+50 scoring."""
    doc_id = uuid4()
    proj_id = uuid4()

    extracted = SimpleNamespace(candidate_name="Meera Iyer", designation="Fresher")
    normalized = SimpleNamespace(job_titles=[], experience=[])
    score = SimpleNamespace(
        final_score=2.78,
        skills_score=0.0,
        is_knocked_out=False,
        knockout_reason=None,
        passing_score=50.0,
        recommendation=RecommendationLevelEnum.REJECT,
        component_scores={
            "skills": {"score": 0.0, "matched_items": [], "missing_items": ["React.js", "Node.js"], "explanation": "Matched 0 required skills."},
            "responsibilities": {"score": 0.0, "matched_items": [], "missing_items": ["Build APIs"], "explanation": "Matched 0 responsibilities."},
            "projects": {"score": 0.0, "matched_items": [], "missing_items": ["Web App"], "explanation": "No projects matched."},
            "preferred_skills": {"score": 0.0, "matched_items": [], "missing_items": ["Docker"], "explanation": "Matched 0 preferred skills."},
            "experience": {"score": 100.0, "matched_items": [], "missing_items": [], "explanation": "Candidate experience is 0 months against 0 required months (N/A)."},
            "certifications": {"score": 100.0, "matched_items": [], "missing_items": [], "explanation": "No specific certification requirements configured (N/A)."},
            "education": {"score": 100.0, "matched_items": ["B.Tech"], "missing_items": [], "explanation": "Education meets the configured requirement."},
        },
    )

    insight = InsightBuilder().build(doc_id, proj_id, extracted, normalized, score)

    # Must contain Overall Match: 2.78/100
    assert "Overall Match: 2.78/100." in insight.score_explanation
    # Must NOT contain obsolete 50 marks
    assert "50" not in insight.score_explanation
    assert "Deterministic Skill Match" not in insight.score_explanation
    assert "AI JD Relevance" not in insight.score_explanation


def test_phase5_aarav_kumar_score_explanation_and_final_score():
    """Verify Aarav Kumar evaluation produces direct 96.00/100 without 50+50 scoring."""
    doc_id = uuid4()
    proj_id = uuid4()

    extracted = SimpleNamespace(candidate_name="Aarav Kumar", designation="Senior Full Stack Engineer")
    normalized = SimpleNamespace(job_titles=["Senior Full Stack Engineer"], experience=[{"duration_months": 48}])
    score = SimpleNamespace(
        final_score=96.00,
        skills_score=100.0,
        is_knocked_out=False,
        knockout_reason=None,
        passing_score=60.0,
        recommendation=RecommendationLevelEnum.SHORTLIST,
        component_scores={
            "skills": {"score": 100.0, "matched_items": ["React.js", "Node.js"], "missing_items": [], "explanation": "Matched all required skills."},
            "responsibilities": {"score": 88.0, "matched_items": [], "missing_items": [], "explanation": "Matched responsibilities."},
            "projects": {"score": 37.0, "matched_items": [], "missing_items": [], "explanation": "Matched projects."},
            "preferred_skills": {"score": 100.0, "matched_items": ["Docker"], "missing_items": [], "explanation": "Matched preferred skills."},
            "experience": {"score": 100.0, "matched_items": [], "missing_items": [], "explanation": "Experience 48 months against 0 required (N/A)."},
            "certifications": {"score": 100.0, "matched_items": [], "missing_items": [], "explanation": "No specific certifications (N/A)."},
            "education": {"score": 100.0, "matched_items": ["B.Tech"], "missing_items": [], "explanation": "Education meets the requirement."},
        },
    )

    insight = InsightBuilder().build(doc_id, proj_id, extracted, normalized, score)

    assert "Overall Match: 96.00/100." in insight.score_explanation
    assert "50" not in insight.score_explanation
    assert "Deterministic Skill Match" not in insight.score_explanation
    assert "AI JD Relevance" not in insight.score_explanation
