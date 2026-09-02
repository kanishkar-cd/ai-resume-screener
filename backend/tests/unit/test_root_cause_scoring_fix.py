import pytest
from unittest.mock import MagicMock

from app.schemas.matching import Requirement, RequirementKind, Evidence
from app.schemas.scoring import ComponentScores, ComponentScoreDetail
from app.services.scoring.weight_calculation_service import WeightCalculationService, COMPONENT_WEIGHTS
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.matching_service import RequirementBuilder, EvidenceBuilder, EvidencePrefilter


@pytest.fixture(autouse=True)
def reset_eval_caches():
    ComponentScoringService.DEGREE_RANKS.clear()
    ComponentScoringService.DEGREE_RANKS.update({
        "high school": 1, "associate": 2, "diploma": 2,
        "bachelor": 3, "bachelor of science": 3, "bachelor of engineering": 3, "bachelor of technology": 3,
        "b.tech": 3, "btech": 3, "b.e.": 3, "be": 3, "b.sc": 3, "bsc": 3, "b.s.": 3, "bs": 3, "bca": 3, "b.com": 3,
        "master": 4, "master of science": 4, "master of engineering": 4, "master of technology": 4,
        "m.tech": 4, "mtech": 4, "m.e.": 4, "me": 4, "m.sc": 4, "msc": 4, "m.s.": 4, "ms": 4, "mca": 4, "mba": 4,
        "doctorate": 5, "phd": 5, "doctor of philosophy": 5,
    })


def test_1_experience_does_not_contribute_to_weighted_score():
    """Test 1: Changing experience duration alone does NOT change weighted total or final score."""
    service = ComponentScoringService()

    job = MagicMock(
        skills=["Python"],
        required_skills=["Python"],
        responsibilities=["Build REST API in Python"],
        project_requirements=["REST API"],
        preferred_skills=[],
        certifications=[],
        experience_requirements=[{"minimum_months": 36}],
        degree_requirements=[],
        required_degree=None,
        qualifications=[],
    )

    resume_1_yr = MagicMock(
        skills=["Python"],
        experience=[{"duration_months": 12, "title": "Developer", "description": "Built REST API in Python", "responsibilities": ["Build REST API in Python"]}],
        projects=[{"name": "REST API", "description": "Built REST API in Python"}],
        summary="",
        certifications=[],
        education=[],
    )

    resume_5_yr = MagicMock(
        skills=["Python"],
        experience=[{"duration_months": 60, "title": "Developer", "description": "Built REST API in Python", "responsibilities": ["Build REST API in Python"]}],
        projects=[{"name": "REST API", "description": "Built REST API in Python"}],
        summary="",
        certifications=[],
        education=[],
    )

    comp_1_yr = service.score(resume_1_yr, job, config=None)
    comp_5_yr = service.score(resume_5_yr, job, config=None)

    app_cats_1 = WeightCalculationService.applicable_categories(job, config=None)
    app_cats_5 = WeightCalculationService.applicable_categories(job, config=None)

    weighted_1, raw_1, weighted_tot_1, eff_weights_1 = WeightCalculationService.calculate(comp_1_yr, config=None, applicable_categories=app_cats_1)
    weighted_5, raw_5, weighted_tot_5, eff_weights_5 = WeightCalculationService.calculate(comp_5_yr, config=None, applicable_categories=app_cats_5)

    final_score_1 = WeightCalculationService.final_score(weighted_tot_1, components=comp_1_yr, applicable_categories=app_cats_1)
    final_score_5 = WeightCalculationService.final_score(weighted_tot_5, components=comp_5_yr, applicable_categories=app_cats_5)

    # Experience duration contribution must be 0.0
    assert weighted_1.experience == 0.0
    assert weighted_5.experience == 0.0
    assert eff_weights_1.get("experience") == 0.0
    assert eff_weights_5.get("experience") == 0.0

    # Final score must be identical despite 1 year vs 5 years experience
    assert final_score_1 == final_score_5


def test_2_base_component_weights():
    """Test 2: Verify base component weights match 30/25/25/15/0/5/0 totaling 100%."""
    assert COMPONENT_WEIGHTS["required_skills"] == 30.0
    assert COMPONENT_WEIGHTS["responsibilities"] == 25.0
    assert COMPONENT_WEIGHTS["projects"] == 25.0
    assert COMPONENT_WEIGHTS["preferred_skills"] == 15.0
    assert COMPONENT_WEIGHTS["experience"] == 0.0
    assert COMPONENT_WEIGHTS["certifications"] == 5.0
    assert COMPONENT_WEIGHTS["education"] == 0.0
    assert sum(COMPONENT_WEIGHTS.values()) == 100.0


def test_3_education_extraction_jd_and_resume():
    """Test 3: Verify JD education requirement and resume education evidence are extracted."""
    job = MagicMock(
        required_degree="Bachelor's in Computer Science",
        degree_requirements=["Bachelor's in Computer Science"],
        skills=["Python"],
    )
    extracted_resume = MagicMock(
        education=[{"degree": "Bachelor of Technology", "field": "Computer Science and Engineering", "institution": "XYZ Univ"}],
        skills=["Python"],
    )

    reqs = RequirementBuilder.build(job, config=None)
    deg_reqs = [r for r in reqs if r.kind == RequirementKind.DEGREE]
    assert len(deg_reqs) >= 1
    assert "Computer Science" in deg_reqs[0].text

    evs = EvidenceBuilder.build(extracted_resume)
    edu_evs = [e for e in evs if e.kind == "education"]
    assert len(edu_evs) >= 1
    assert "Bachelor of Technology" in edu_evs[0].text


def test_4_education_exact_equivalent_match():
    """Test 4: B.Tech in CSE satisfies Bachelor's in CS requirement with 100% score."""
    service = ComponentScoringService()
    job = MagicMock(required_degree="Bachelor's in Computer Science", degree_requirements=["Bachelor's in Computer Science"])
    resume = MagicMock(education=[{"degree": "B.Tech", "field": "Computer Science and Engineering", "institution": "XYZ Univ"}])

    detail = service._education_component(resume, job, config=None)
    assert detail.score == 100.0
    assert len(detail.matched_items) == 1
    assert detail.missing_items == []


def test_5_education_mismatch_field():
    """Test 5: Bachelor's in Mechanical Engineering gives partial match (50%) for CS degree requirement."""
    service = ComponentScoringService()
    job = MagicMock(required_degree="Bachelor's in Computer Science", degree_requirements=["Bachelor's in Computer Science"])
    resume = MagicMock(education=[{"degree": "Bachelor of Engineering", "field": "Mechanical Engineering", "institution": "XYZ Univ"}])

    detail = service._education_component(resume, job, config=None)
    assert detail.score == 50.0
    assert len(detail.missing_items) == 0


def test_6_education_degree_level_mismatch():
    """Test 6: Bachelor's degree gives partial match (50%) when Master's degree is required."""
    service = ComponentScoringService()
    job = MagicMock(required_degree="Master's in Computer Science", degree_requirements=["Master's in Computer Science"])
    resume = MagicMock(education=[{"degree": "Bachelor of Technology", "field": "Computer Science", "institution": "XYZ Univ"}])

    detail = service._education_component(resume, job, config=None)
    assert detail.score == 50.0


def test_7_education_component_scores_and_zero_weight():
    """Test 7: Verify Education component scores differ (100% vs 50%) while Education base weight remains 0.0%."""
    service = ComponentScoringService()
    job = MagicMock(
        skills=["Python"],
        required_skills=["Python"],
        responsibilities=[],
        project_requirements=[],
        preferred_skills=[],
        certifications=[],
        required_degree="Bachelor's in Computer Science",
        degree_requirements=["Bachelor's in Computer Science"],
    )

    resume_compat = MagicMock(
        skills=["Python"],
        education=[{"degree": "B.Tech", "field": "Computer Science", "institution": "XYZ"}],
        experience=[], projects=[], summary="", certifications=[],
    )

    resume_incompat = MagicMock(
        skills=["Python"],
        education=[{"degree": "Diploma", "field": "Civil Engineering", "institution": "ABC"}],
        experience=[], projects=[], summary="", certifications=[],
    )

    comp_c = service.score(resume_compat, job, config=None)
    comp_i = service.score(resume_incompat, job, config=None)

    assert comp_c.education.score == 100.0
    assert comp_i.education.score == 0.0
    assert COMPONENT_WEIGHTS["education"] == 0.0


def test_8_education_absent_from_jd():
    """Test 8: If JD has no education requirement, education category is inactive and weight is redistributed."""
    job = MagicMock(
        skills=["Python"],
        required_skills=["Python"],
        responsibilities=["APIs"],
        project_requirements=[],
        preferred_skills=[],
        certifications=[],
        required_degree=None,
        degree_requirements=[],
        qualifications=[],
    )

    cats = WeightCalculationService.applicable_categories(job, config=None)
    assert "education" not in cats

    comp = ComponentScores(
        skills=ComponentScoreDetail(score=100.0, matched_items=["Python"], missing_items=[], explanation="ok"),
        responsibilities=ComponentScoreDetail(score=100.0, matched_items=["APIs"], missing_items=[], explanation="ok"),
        projects=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="ok"),
        preferred_skills=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="ok"),
        experience=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="ok"),
        education=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="ok"),
        certifications=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="ok"),
        languages=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="ok"),
    )

    w, raw, wt, eff = WeightCalculationService.calculate(comp, config=None, applicable_categories=cats)
    assert eff.get("education") == 0.0
    assert abs(sum(eff.values()) - 100.0) < 0.05


def test_9_experience_evidence_still_supports_skills_and_responsibilities():
    """Test 9: Removing experience weight does NOT break experience text powering skills and responsibilities."""
    service = ComponentScoringService()
    job = MagicMock(
        required_skills=["Python", "FastAPI"],
        responsibilities=["Build microservices"],
        project_requirements=[], preferred_skills=[], certifications=[], degree_requirements=[],
    )
    resume = MagicMock(
        skills=[],
        experience=[{"title": "Backend Dev", "description": "Built microservices using Python and FastAPI"}],
        projects=[], summary="", certifications=[], education=[],
    )

    comp = service.score(resume, job, config=None)
    assert comp.skills.score == 100.0
    assert "Python" in comp.skills.matched_items
    assert "FastAPI" in comp.skills.matched_items


def test_10_weight_sum_for_all_combinations():
    """Test 10: Verify effective weights sum to 100.0% across all valid JD category combinations."""
    test_cases = [
        {"skills", "responsibilities", "projects", "education", "certifications", "preferred_skills"},
        {"skills", "responsibilities", "projects", "education", "certifications"},
        {"skills", "responsibilities", "projects", "education", "preferred_skills"},
        {"skills", "responsibilities", "projects", "preferred_skills", "certifications"},
        {"skills", "responsibilities", "projects", "education", "preferred_skills"},
    ]

    mock_comp = ComponentScores(
        skills=ComponentScoreDetail(score=80.0, matched_items=[], missing_items=[], explanation="ok"),
        responsibilities=ComponentScoreDetail(score=80.0, matched_items=[], missing_items=[], explanation="ok"),
        projects=ComponentScoreDetail(score=80.0, matched_items=[], missing_items=[], explanation="ok"),
        preferred_skills=ComponentScoreDetail(score=80.0, matched_items=[], missing_items=[], explanation="ok"),
        experience=ComponentScoreDetail(score=80.0, matched_items=[], missing_items=[], explanation="ok"),
        education=ComponentScoreDetail(score=80.0, matched_items=[], missing_items=[], explanation="ok"),
        certifications=ComponentScoreDetail(score=80.0, matched_items=[], missing_items=[], explanation="ok"),
        languages=ComponentScoreDetail(score=80.0, matched_items=[], missing_items=[], explanation="ok"),
    )

    for active_set in test_cases:
        weighted, raw_total, weighted_total, eff_weights = WeightCalculationService.calculate(
            mock_comp, config=None, applicable_categories=active_set
        )
        assert eff_weights.get("experience") == 0.0
        assert abs(sum(eff_weights.values()) - 100.0) < 0.05
