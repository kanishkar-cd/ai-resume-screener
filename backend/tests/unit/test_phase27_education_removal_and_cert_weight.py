from types import SimpleNamespace
import pytest

from app.schemas.scoring import ComponentScoreDetail, ComponentScores
from app.services.matching_service import EvidenceBuilder, RequirementBuilder, RequirementKind
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.weight_calculation_service import COMPONENT_WEIGHTS, WeightCalculationService
from app.services.scoring.bonus_service import BonusService


def test_1_education_not_built_as_requirement():
    """Verify RequirementBuilder omits degree_requirements."""
    job = SimpleNamespace(
        required_skills=["Python", "FastAPI"],
        preferred_skills=[],
        experience_requirements=[],
        degree_requirements=["Bachelor's Degree in Computer Science"],
        certifications=[],
        project_requirements=[],
        responsibilities=[],
    )
    reqs = RequirementBuilder.build(job, config=None)
    kinds = [r.kind for r in reqs]
    assert RequirementKind.DEGREE not in kinds, "Degree requirement should not be built"


def test_2_education_not_built_as_evidence():
    """Verify EvidenceBuilder omits education entries."""
    extracted = SimpleNamespace(
        education=[{"degree": "B.Tech Computer Science", "institution": "Top College"}],
        skills=["Python", "FastAPI"],
        experience=[],
        projects=[],
        certifications=[],
        summary="Experienced backend engineer",
    )
    evidence = EvidenceBuilder.build(extracted)
    kinds = [e.kind for e in evidence]
    assert "education" not in kinds, "Education evidence should not be built"


def test_3_education_component_score_is_zero_and_disabled():
    """Verify ComponentScoringService produces score 0.0 with disabled explanation for education."""
    scorer = ComponentScoringService()
    resume = SimpleNamespace(
        skills=["Python"],
        education=[{"degree": "PhD Computer Science"}],
        experience=[],
        projects=[],
        certifications=[],
        languages=[],
    )
    job = SimpleNamespace(
        required_skills=["Python"],
        degree_requirements=["Bachelor's Degree"],
        responsibilities=[],
    )
    comps = scorer.score(resume, job, config=None)
    assert comps.education.score == 0.0
    assert "disabled" in comps.education.explanation.lower()


def test_4_and_5_and_6_weights_structure():
    """Verify COMPONENT_WEIGHTS has education=0%, certifications=5%, and total sum=100%."""
    assert COMPONENT_WEIGHTS["education"] == 0.0, "Education weight must be 0%"
    assert COMPONENT_WEIGHTS["certifications"] == 5.0, "Certification weight must be 5%"
    assert COMPONENT_WEIGHTS["required_skills"] == 30.0
    assert COMPONENT_WEIGHTS["responsibilities"] == 25.0
    assert COMPONENT_WEIGHTS["projects"] == 20.0
    assert COMPONENT_WEIGHTS["preferred_skills"] == 15.0
    assert COMPONENT_WEIGHTS["experience"] == 5.0
    assert sum(COMPONENT_WEIGHTS.values()) == 100.0, "Total active weights must equal 100%"


def test_7_and_8_education_matching_vs_missing_score_neutrality():
    """Verify a candidate with matching education vs missing/wrong education gets the EXACT same score."""
    job = SimpleNamespace(
        required_skills=["Python"],
        skills=["Python"],
        degree_requirements=["Master's Degree"],
        responsibilities=[],
        experience_requirements=[],
        preferred_skills=[],
        certifications=[],
        project_requirements=[],
    )
    c1_resume = SimpleNamespace(
        skills=["Python"],
        education=[{"degree": "Master's Degree in CS"}],
        experience=[],
        projects=[],
        certifications=[],
        languages=[],
    )
    c2_resume = SimpleNamespace(
        skills=["Python"],
        education=[],  # Missing education
        experience=[],
        projects=[],
        certifications=[],
        languages=[],
    )

    scorer = ComponentScoringService()
    comps1 = scorer.score(c1_resume, job, config=None)
    comps2 = scorer.score(c2_resume, job, config=None)

    weighted1, _, _, _ = WeightCalculationService.calculate(comps1, config=None)
    weighted2, _, _, _ = WeightCalculationService.calculate(comps2, config=None)

    final1 = WeightCalculationService.final_score(weighted1, components=comps1)
    final2 = WeightCalculationService.final_score(weighted2, components=comps2)

    assert final1 == final2, f"Candidate with matching education ({final1}) must equal candidate with missing education ({final2})"
    assert comps1.education.score == 0.0
    assert comps2.education.score == 0.0


def test_9_certification_score_contributes_up_to_5_points():
    """Verify 100% certification score contributes exactly 5 points to weighted total."""
    comps = ComponentScores(
        skills=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        responsibilities=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        projects=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        preferred_skills=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        experience=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        education=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        certifications=ComponentScoreDetail(score=100.0, matched_items=["AWS Certified Architect"], missing_items=[], explanation=""),
        languages=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
    )

    weighted, _, _, effective_weights = WeightCalculationService.calculate(comps, config=None)
    assert effective_weights["certifications"] == 5.0
    assert weighted.certifications == 5.0


def test_10_existing_non_education_matching_unchanged():
    """Verify skills, experience, projects, and certifications scoring remain functional."""
    job = SimpleNamespace(
        required_skills=["Python", "FastAPI"],
        preferred_skills=["Docker"],
        certifications=["AWS Certified Developer"],
        experience_requirements=[],
        responsibilities=[],
        project_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["Python", "FastAPI", "Docker"],
        certifications=["AWS Certified Developer"],
        education=[{"degree": "Bachelor of Technology"}],
        experience=[],
        projects=[],
        languages=[],
    )
    scorer = ComponentScoringService()
    comps = scorer.score(resume, job, config=None)

    assert comps.skills.score == 100.0
    assert comps.preferred_skills.score == 100.0
    assert comps.certifications.score == 100.0
    assert comps.education.score == 0.0
