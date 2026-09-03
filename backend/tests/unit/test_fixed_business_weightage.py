"""
Unit tests for fixed business weightage calculation with proportional redistribution
for genuinely absent JD categories only.
"""
from types import SimpleNamespace
import pytest

from app.schemas.scoring import ComponentScoreDetail, ComponentScores
from app.services.scoring.weight_calculation_service import (
    DEFAULT_WEIGHTS,
    WeightCalculationService,
    validate_weights,
)


def _build_components(
    req_score: float = 0.0,
    pref_score: float = 0.0,
    resp_score: float = 0.0,
    proj_score: float = 0.0,
    req_matched: list[str] | None = None,
    req_missing: list[str] | None = None,
    pref_matched: list[str] | None = None,
    pref_missing: list[str] | None = None,
    resp_matched: list[str] | None = None,
    resp_missing: list[str] | None = None,
    proj_matched: list[str] | None = None,
    proj_missing: list[str] | None = None,
    pref_explanation: str = "preferred skills",
    proj_explanation: str = "project requirements",
    resp_explanation: str = "responsibilities",
    req_explanation: str = "required skills",
) -> ComponentScores:
    return ComponentScores(
        skills=ComponentScoreDetail(
            score=req_score,
            matched_items=req_matched if req_matched is not None else (["Skill"] if req_score > 0 else []),
            missing_items=req_missing if req_missing is not None else ([] if req_score == 100.0 else ["MissingSkill"]),
            explanation=req_explanation,
        ),
        preferred_skills=ComponentScoreDetail(
            score=pref_score,
            matched_items=pref_matched if pref_matched is not None else (["PrefSkill"] if pref_score > 0 else []),
            missing_items=pref_missing if pref_missing is not None else ([] if pref_score == 100.0 else ["MissingPref"]),
            explanation=pref_explanation,
        ),
        responsibilities=ComponentScoreDetail(
            score=resp_score,
            matched_items=resp_matched if resp_matched is not None else (["Resp"] if resp_score > 0 else []),
            missing_items=resp_missing if resp_missing is not None else ([] if resp_score == 100.0 else ["MissingResp"]),
            explanation=resp_explanation,
        ),
        projects=ComponentScoreDetail(
            score=proj_score,
            matched_items=proj_matched if proj_matched is not None else (["Proj"] if proj_score > 0 else []),
            missing_items=proj_missing if proj_missing is not None else ([] if proj_score == 100.0 else ["MissingProj"]),
            explanation=proj_explanation,
        ),
        experience=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="experience"),
        education=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="education"),
        certifications=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="certifications"),
        languages=ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="languages"),
    )


def test_1_all_categories_present():
    """Test 1: All categories present in JD -> weights remain 40 / 15 / 20 / 25."""
    comp = _build_components(req_score=100.0, pref_score=100.0, resp_score=100.0, proj_score=100.0)
    _, _, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "preferred_skills", "responsibilities", "projects"}
    )
    assert eff_weights["required_skills"] == 40.0
    assert eff_weights["preferred_skills"] == 15.0
    assert eff_weights["responsibilities"] == 20.0
    assert eff_weights["projects"] == 25.0
    assert sum(eff_weights[c] for c in ("required_skills", "preferred_skills", "responsibilities", "projects")) == 100.0


def test_2_preferred_skills_absent():
    """
    Test 2: Preferred Skills absent.
    Active total: 40 + 20 + 25 = 85.
    Required: 40/85 = 47.0588%, Resp: 20/85 = 23.5294%, Proj: 25/85 = 29.4118%.
    """
    comp = _build_components(req_score=100.0, resp_score=100.0, proj_score=100.0)
    _, _, _, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "responsibilities", "projects"}
    )
    assert pytest.approx(eff_weights["required_skills"], rel=1e-4) == 47.0588
    assert pytest.approx(eff_weights["responsibilities"], rel=1e-4) == 23.5294
    assert pytest.approx(eff_weights["projects"], rel=1e-4) == 29.4118
    assert eff_weights["preferred_skills"] == 0.0
    assert pytest.approx(sum(eff_weights.values()), abs=1e-3) == 100.0


def test_3_projects_absent():
    """
    Test 3: Projects absent.
    Active total: 40 + 15 + 20 = 75.
    Required: 40/75 = 53.3333%, Preferred: 15/75 = 20.0%, Resp: 20/75 = 26.6667%.
    """
    comp = _build_components(req_score=100.0, pref_score=100.0, resp_score=100.0)
    _, _, _, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "preferred_skills", "responsibilities"}
    )
    assert pytest.approx(eff_weights["required_skills"], rel=1e-4) == 53.3333
    assert pytest.approx(eff_weights["preferred_skills"], rel=1e-4) == 20.0
    assert pytest.approx(eff_weights["responsibilities"], rel=1e-4) == 26.6667
    assert eff_weights["projects"] == 0.0
    assert pytest.approx(sum(eff_weights.values()), abs=1e-3) == 100.0


def test_4_responsibilities_absent():
    """
    Test 4: Responsibilities absent.
    Active total: 40 + 15 + 25 = 80.
    Required: 40/80 = 50.0%, Preferred: 15/80 = 18.75%, Proj: 25/80 = 31.25%.
    """
    comp = _build_components(req_score=100.0, pref_score=100.0, proj_score=100.0)
    _, _, _, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "preferred_skills", "projects"}
    )
    assert pytest.approx(eff_weights["required_skills"], rel=1e-4) == 50.0
    assert pytest.approx(eff_weights["preferred_skills"], rel=1e-4) == 18.75
    assert pytest.approx(eff_weights["projects"], rel=1e-4) == 31.25
    assert eff_weights["responsibilities"] == 0.0
    assert pytest.approx(sum(eff_weights.values()), abs=1e-3) == 100.0


def test_5_only_required_skills():
    """Test 5: Only Required Skills present -> Required Skills = 100%."""
    comp = _build_components(req_score=100.0)
    _, _, _, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills"}
    )
    assert eff_weights["required_skills"] == 100.0
    assert eff_weights["preferred_skills"] == 0.0
    assert eff_weights["responsibilities"] == 0.0
    assert eff_weights["projects"] == 0.0


def test_6_only_preferred_skills():
    """Test 6: Only Preferred Skills present -> Preferred Skills = 100%."""
    comp = _build_components(pref_score=100.0)
    _, _, _, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"preferred_skills"}
    )
    assert eff_weights["preferred_skills"] == 100.0
    assert eff_weights["required_skills"] == 0.0


def test_7_only_responsibilities():
    """Test 7: Only Responsibilities present -> Responsibilities = 100%."""
    comp = _build_components(resp_score=100.0)
    _, _, _, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"responsibilities"}
    )
    assert eff_weights["responsibilities"] == 100.0
    assert eff_weights["required_skills"] == 0.0


def test_8_only_projects():
    """Test 8: Only Projects present -> Projects = 100%."""
    comp = _build_components(proj_score=100.0)
    _, _, _, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"projects"}
    )
    assert eff_weights["projects"] == 100.0
    assert eff_weights["required_skills"] == 0.0


def test_9_multiple_categories_absent():
    """
    Test 9: Multiple categories absent (Preferred Skills and Responsibilities absent).
    Active: Required Skills (40) + Projects (25) = 65.
    Required: 40/65 = 61.5385%, Projects: 25/65 = 38.4615%.
    """
    comp = _build_components(req_score=100.0, proj_score=100.0)
    _, _, _, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "projects"}
    )
    assert pytest.approx(eff_weights["required_skills"], rel=1e-4) == 61.5385
    assert pytest.approx(eff_weights["projects"], rel=1e-4) == 38.4615
    assert eff_weights["preferred_skills"] == 0.0
    assert eff_weights["responsibilities"] == 0.0
    assert pytest.approx(sum(eff_weights.values()), abs=1e-3) == 100.0


def test_10_all_categories_absent_safe_handling():
    """Test 10: All categories absent -> safe handling, no division by zero, score is 0.0."""
    comp = _build_components()
    weighted, raw, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories=set()
    )
    assert total == 0.0
    assert raw == 0.0
    assert all(w == 0.0 for w in eff_weights.values())


def test_11_category_exists_but_candidate_scores_zero_does_not_redistribute():
    """
    Test 11: Category exists in JD, but candidate scores 0.
    Category must remain active at its configured weight; NO redistribution.
    """
    comp = _build_components(
        req_score=0.0,
        req_matched=[],
        req_missing=["Python", "FastAPI"],
        pref_score=0.0,
        pref_matched=[],
        pref_missing=["AWS", "Docker"],
        resp_score=100.0,
        proj_score=100.0,
    )
    # All 4 categories are present in JD
    _, _, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "preferred_skills", "responsibilities", "projects"}
    )
    # Weights must NOT be redistributed
    assert eff_weights["required_skills"] == 40.0
    assert eff_weights["preferred_skills"] == 15.0
    assert eff_weights["responsibilities"] == 20.0
    assert eff_weights["projects"] == 25.0
    # Final score: (0 * 0.40) + (0 * 0.15) + (100 * 0.20) + (100 * 0.25) = 45.0
    assert total == 45.0


def test_12_different_item_counts_do_not_alter_effective_weights():
    """Test 12: Changing item counts does not change effective weights."""
    comp_a = _build_components(
        req_score=100.0,
        req_matched=["Python", "FastAPI"],
        resp_score=100.0,
        resp_matched=[f"Resp {i}" for i in range(8)],
        proj_score=100.0,
        pref_score=100.0,
    )
    _, _, _, eff_a = WeightCalculationService.calculate(comp_a)
    assert eff_a["required_skills"] == 40.0
    assert eff_a["responsibilities"] == 20.0
    assert eff_a["projects"] == 25.0
    assert eff_a["preferred_skills"] == 15.0


def test_13_preferred_skill_bonus_not_added_to_final_score():
    """Test 13: Preferred skills contribute strictly via their effective weight, no external +2 bonus."""
    comp = _build_components(req_score=100.0, pref_score=100.0, resp_score=100.0, proj_score=100.0)
    final = WeightCalculationService.final_score(bonus_total=10.0, components=comp)
    assert final == 100.0


def test_14_end_to_end_score_calculation_with_redistribution():
    """
    Test 14: Section 8 example:
    Required Skills score  = 75
    Preferred Skills score = N/A (absent)
    Responsibilities score = 50
    Projects score         = 80

    Active weights: 40/85, 20/85, 25/85.
    Expected: (75 * 40/85) + (50 * 20/85) + (80 * 25/85)
            = 35.2941 + 11.7647 + 23.5294 = 70.5882 -> 70.59.
    """
    comp = _build_components(
        req_score=75.0,
        pref_score=0.0,
        resp_score=50.0,
        proj_score=80.0,
        pref_matched=[],
        pref_missing=[],
        pref_explanation="No preferred skills configured (N/A).",
    )
    _, _, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "responsibilities", "projects"}
    )
    assert total == 70.59
    assert WeightCalculationService.final_score(
        components=comp, applicable_categories={"required_skills", "responsibilities", "projects"}
    ) == 70.59


def test_15_inactive_preferred_skills_score_weight_contribution_zero():
    """Backend Test A: Inactive Preferred Skills has weight=0, score=0, contribution=0."""
    comp = _build_components(
        req_score=100.0,
        pref_score=0.0,
        resp_score=100.0,
        proj_score=100.0,
        pref_matched=[],
        pref_missing=[],
        pref_explanation="No preferred skills configured (N/A).",
    )
    weighted, _, _, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "responsibilities", "projects"}
    )
    assert eff_weights["preferred_skills"] == 0.0
    assert weighted.preferred_skills == 0.0
    assert comp.preferred_skills.score == 0.0


def test_16_active_preferred_skills_with_zero_matches():
    """Backend Test B: Active Preferred Skills with zero matches has weight=15, score=0, contribution=0."""
    comp = _build_components(
        req_score=100.0,
        pref_score=0.0,
        resp_score=100.0,
        proj_score=100.0,
        pref_matched=[],
        pref_missing=["AWS", "Docker"],
        pref_explanation="Matched 0 of 2 preferred skills.",
    )
    weighted, _, _, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "preferred_skills", "responsibilities", "projects"}
    )
    assert eff_weights["preferred_skills"] == 15.0
    assert comp.preferred_skills.score == 0.0
    assert weighted.preferred_skills == 0.0


def test_17_active_preferred_skills_with_all_matches():
    """Backend Test C: Active Preferred Skills with all matches has weight=15, score=100, contribution=15."""
    comp = _build_components(
        req_score=100.0,
        pref_score=100.0,
        resp_score=100.0,
        proj_score=100.0,
        pref_matched=["AWS", "Docker"],
        pref_missing=[],
        pref_explanation="Matched 2 of 2 preferred skills.",
    )
    weighted, _, _, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "preferred_skills", "responsibilities", "projects"}
    )
    assert eff_weights["preferred_skills"] == 15.0
    assert comp.preferred_skills.score == 100.0
    assert weighted.preferred_skills == 15.0


def test_18_inactive_certifications_score_weight_contribution_zero():
    """Backend Test D: Inactive Certifications has weight=0, score=0, contribution=0."""
    comp = _build_components(
        req_score=100.0,
        pref_score=100.0,
        resp_score=100.0,
        proj_score=100.0,
    )
    # Certifications has 0 score when inactive
    comp.certifications.score = 0.0
    weighted, _, _, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "preferred_skills", "responsibilities", "projects"}
    )
    assert eff_weights.get("certifications", 0.0) == 0.0
    assert weighted.certifications == 0.0
    assert comp.certifications.score == 0.0


def test_19_inactive_categories_do_not_participate_in_final_score():
    """Backend Test E: Inactive categories do not participate in final weighted score."""
    # When both preferred_skills and projects are inactive, active are skills (40/60) and resp (20/60)
    comp = _build_components(
        req_score=90.0,
        resp_score=60.0,
        pref_score=0.0,
        proj_score=0.0,
    )
    _, _, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "responsibilities"}
    )
    # 90 * (40/60) + 60 * (20/60) = 60.0 + 20.0 = 80.0
    assert total == 80.0
    assert eff_weights["preferred_skills"] == 0.0
    assert eff_weights["projects"] == 0.0


def test_20_active_categories_use_actual_calculated_score():
    """Backend Test F: Active categories continue using their actual calculated score."""
    comp = _build_components(
        req_score=80.0,
        pref_score=60.0,
        resp_score=70.0,
        proj_score=90.0,
    )
    _, _, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "preferred_skills", "responsibilities", "projects"}
    )
    # 80 * 0.40 + 60 * 0.15 + 70 * 0.20 + 90 * 0.25 = 32 + 9 + 14 + 22.5 = 77.5
    assert total == 77.5
    assert eff_weights["required_skills"] == 40.0
    assert eff_weights["preferred_skills"] == 15.0
    assert eff_weights["responsibilities"] == 20.0
    assert eff_weights["projects"] == 25.0


def test_21_component_scoring_service_returns_zero_for_absent_categories():
    """Test that ComponentScoringService directly scores absent categories as 0.0."""
    from app.services.scoring.component_scoring_service import ComponentScoringService
    svc = ComponentScoringService()
    
    # Resume with some skills but no certifications, no preferred skills, no degrees
    resume = SimpleNamespace(
        skills=["Python"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )
    # Job with only required skills
    job = SimpleNamespace(
        required_skills=["Python"],
        skills=["Python"],
        preferred_skills=[],
        responsibilities=[],
        project_requirements=[],
        keywords=[],
        experience_requirements=[],
        degree_requirements=[],
        qualifications=[],
        certifications=[],
    )
    comp_scores = svc.score(resume, job, config=None)
    assert comp_scores.preferred_skills.score == 0.0
    assert comp_scores.certifications.score == 0.0
    assert comp_scores.projects.score == 0.0
    assert comp_scores.responsibilities.score == 0.0
    assert comp_scores.education.score == 0.0
    assert comp_scores.languages.score == 0.0
    # Active skill is matched -> 100.0
    assert comp_scores.skills.score == 100.0

