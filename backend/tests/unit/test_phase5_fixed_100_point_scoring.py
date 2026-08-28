import pytest
from types import SimpleNamespace
from app.schemas.scoring import ComponentScoreDetail, ComponentScores
from app.services.scoring.weight_calculation_service import COMPONENT_WEIGHTS, WeightCalculationService
from app.services.scoring.component_scoring_service import ComponentScoringService


def test_1_perfect_candidate():
    components = ComponentScores(
        skills=ComponentScoreDetail(score=100.0, matched_items=["React"], missing_items=[], explanation="All skills matched"),
        responsibilities=ComponentScoreDetail(score=100.0, matched_items=["Resp1"], missing_items=[], explanation="All responsibilities met"),
        projects=ComponentScoreDetail(score=100.0, matched_items=["Proj1"], missing_items=[], explanation="All projects met"),
        preferred_skills=ComponentScoreDetail(score=100.0, matched_items=["Docker"], missing_items=[], explanation="All preferred skills matched"),
        experience=ComponentScoreDetail(score=100.0, matched_items=["60 months"], missing_items=[], explanation="Experience met"),
        certifications=ComponentScoreDetail(score=100.0, matched_items=["AWS Cert"], missing_items=[], explanation="Cert met"),
        education=ComponentScoreDetail(score=100.0, matched_items=["B.Tech"], missing_items=[], explanation="Degree met"),
        languages=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="N/A"),
    )
    score = WeightCalculationService.final_score(0, 0, 0, components=components)
    assert score == 100.0


def test_2_required_skills_only():
    components = ComponentScores(
        skills=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        responsibilities=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        projects=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        preferred_skills=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        experience=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        certifications=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        education=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        languages=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
    )
    score = WeightCalculationService.final_score(0, 0, 0, components=components)
    assert score == 30.0  # Exactly 30% contribution


def test_3_responsibilities_only():
    components = ComponentScores(
        skills=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        responsibilities=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        projects=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        preferred_skills=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        experience=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        certifications=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        education=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        languages=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
    )
    score = WeightCalculationService.final_score(0, 0, 0, components=components)
    assert score == 25.0  # Exactly 25% contribution


def test_4_projects_only():
    components = ComponentScores(
        skills=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        responsibilities=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        projects=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        preferred_skills=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        experience=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        certifications=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        education=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        languages=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
    )
    score = WeightCalculationService.final_score(0, 0, 0, components=components)
    assert score == 20.0  # Exactly 20% contribution


def test_5_preferred_skills_only():
    components = ComponentScores(
        skills=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        responsibilities=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        projects=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        preferred_skills=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        experience=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        certifications=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        education=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        languages=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
    )
    score = WeightCalculationService.final_score(0, 0, 0, components=components)
    assert score == 15.0  # Exactly 15% contribution


def test_6_experience_only():
    components = ComponentScores(
        skills=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        responsibilities=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        projects=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        preferred_skills=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        experience=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        certifications=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        education=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        languages=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
    )
    score = WeightCalculationService.final_score(0, 0, 0, components=components)
    assert score == 5.0  # Exactly 5% contribution


def test_7_certifications_only():
    components = ComponentScores(
        skills=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        responsibilities=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        projects=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        preferred_skills=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        experience=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        certifications=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        education=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        languages=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
    )
    score = WeightCalculationService.final_score(0, 0, 0, components=components)
    assert score == 3.0  # Exactly 3% contribution


def test_8_education_only():
    components = ComponentScores(
        skills=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        responsibilities=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        projects=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        preferred_skills=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        experience=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        certifications=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
        education=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        languages=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation=""),
    )
    score = WeightCalculationService.final_score(0, 0, 0, components=components)
    assert score == 2.0  # Exactly 2% contribution


def test_9_example_calculation_section_13():
    # Example from Prompt:
    # Required Skills = 80%, Responsibilities = 80%, Projects = 75%, Preferred Skills = 50%, Experience = 100%, Certifications = N/A, Education = 100%
    # Applicable weights: 30 + 25 + 20 + 15 + 5 + 2 = 97
    # Raw contribution: 24 + 20 + 15 + 7.5 + 5 + 2 = 73.5
    # Normalized: 73.5 / 97 * 100 = 75.77
    components = ComponentScores(
        skills=ComponentScoreDetail(score=80.0, matched_items=[], missing_items=[], explanation=""),
        responsibilities=ComponentScoreDetail(score=80.0, matched_items=[], missing_items=[], explanation=""),
        projects=ComponentScoreDetail(score=75.0, matched_items=[], missing_items=[], explanation=""),
        preferred_skills=ComponentScoreDetail(score=50.0, matched_items=[], missing_items=[], explanation=""),
        experience=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        certifications=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="N/A"),
        education=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        languages=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="N/A"),
    )
    applicable = {"required_skills", "responsibilities", "projects", "preferred_skills", "experience", "education"}
    score = WeightCalculationService.final_score(0, 0, 0, components=components, applicable_categories=applicable)
    assert score == 75.77


def test_10_na_projects_certifications_education():
    # JD has only Skills (30), Responsibilities (25), Preferred Skills (15), Experience (5) = 75 total applicable
    components = ComponentScores(
        skills=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        responsibilities=ComponentScoreDetail(score=80.0, matched_items=[], missing_items=[], explanation=""),
        projects=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="N/A"),
        preferred_skills=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        experience=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        certifications=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="N/A"),
        education=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="N/A"),
        languages=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="N/A"),
    )
    applicable = {"required_skills", "responsibilities", "preferred_skills", "experience"}
    # Raw: (100*0.30) + (80*0.25) + (100*0.15) + (100*0.05) = 30 + 20 + 15 + 5 = 70.0
    # Normalized: 70.0 / 75 * 100 = 93.33
    score = WeightCalculationService.final_score(0, 0, 0, components=components, applicable_categories=applicable)
    assert score == 93.33


def test_11_bounds_clamping():
    components = ComponentScores(
        skills=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        responsibilities=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        projects=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        preferred_skills=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        experience=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        certifications=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        education=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
        languages=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation=""),
    )
    score = WeightCalculationService.final_score(150.0, 0, 0, components=components)
    assert 0.0 <= score <= 100.0
