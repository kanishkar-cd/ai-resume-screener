import pytest
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.scoring import RecommendationLevel
from app.services.insights.generators import (
    COMPONENT_LABELS, ImprovementGenerator, InsightBuilder, StrengthGenerator, WeaknessGenerator,
)


def test_component_labels_contract_consistency():
    """Verify that all valid scoring component names are explicitly mapped in COMPONENT_LABELS."""
    expected_components = [
        "skills",
        "required_skills",
        "preferred_skills",
        "responsibilities",
        "projects",
        "experience",
        "education",
        "certifications",
        "languages",
    ]
    for comp in expected_components:
        assert comp in COMPONENT_LABELS
        assert COMPONENT_LABELS[comp] != ""

    assert COMPONENT_LABELS["preferred_skills"] == "Preferred Skills"
    assert COMPONENT_LABELS["responsibilities"] == "Responsibilities"


def test_strength_and_weakness_generators_with_preferred_skills():
    """Verify that StrengthGenerator and WeaknessGenerator consume preferred_skills without KeyError."""
    component_scores = {
        "skills": {"score": 85.0, "explanation": "Strong skills"},
        "preferred_skills": {"score": 30.0, "explanation": "Matched 3 of 10 preferred skills"},
        "responsibilities": {"score": 90.0, "explanation": "Demonstrated responsibilities"},
        "projects": {"score": 80.0, "explanation": "Good projects"},
        "experience": {"score": 100.0, "explanation": "Full experience"},
        "education": {"score": 100.0, "explanation": "Degree matched"},
    }

    strengths = StrengthGenerator.generate(component_scores)
    # Skills, Responsibilities, Projects, Experience, Education are strengths
    assert any("Responsibilities scored 90.00%." in s for s in strengths)
    assert not any("Preferred Skills" in s for s in strengths)

    weaknesses = WeaknessGenerator.generate(component_scores)
    # Preferred skills (30.0%) is a weakness
    assert any("Preferred Skills scored 30.00%." in w for w in weaknesses)
    assert not any("preferred_skills" in w for w in weaknesses)  # Must use canonical label


def test_insight_builder_end_to_end_with_preferred_skills():
    """Verify that InsightBuilder builds CandidateInsightCreate without KeyError when preferred_skills is present."""
    builder = InsightBuilder()
    doc_id = uuid4()
    proj_id = uuid4()

    extracted = SimpleNamespace(
        candidate_name="Ravi Menon",
        designation="Senior Web Developer",
    )
    normalized = SimpleNamespace(
        job_titles=["Senior Web Developer"],
        experience=[{"duration_months": 60}],
    )
    score = SimpleNamespace(
        final_score=79.02,
        skills_score=90.91,
        is_knocked_out=False,
        knockout_reason=None,
        passing_score=70.0,
        recommendation=RecommendationLevel.SHORTLIST,
        component_scores={
            "skills": {"score": 90.91, "matched_items": ["React.js", "Node.js"], "missing_items": ["AWS"], "explanation": "Matched 10 of 11"},
            "preferred_skills": {"score": 30.0, "matched_items": ["IoT"], "missing_items": ["Docker"], "explanation": "Matched 3 of 10"},
            "responsibilities": {"score": 62.50, "matched_items": [], "missing_items": [], "explanation": "Demonstrated 5 of 8"},
            "education": {"score": 100.0, "matched_items": ["B.Tech"], "missing_items": [], "explanation": "Degree matches"},
            "projects": {"score": 100.0, "matched_items": [], "missing_items": [], "explanation": "No specific project requirements (N/A)"},
            "experience": {"score": 100.0, "matched_items": [], "missing_items": [], "explanation": "Experience 60 months against 0 required (N/A)"},
            "certifications": {"score": 100.0, "matched_items": [], "missing_items": [], "explanation": "No specific certifications (N/A)"},
        },
    )

    insight = builder.build(doc_id, proj_id, extracted, normalized, score)
    assert insight.document_id == doc_id
    assert insight.project_id == proj_id
    assert any("Preferred Skills scored 30.00%." in w for w in insight.weaknesses)
    assert "preferred skills" in "\n".join(insight.improvement_suggestions).casefold()
