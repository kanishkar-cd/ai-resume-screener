"""
Unit tests for fixed business weightage calculation with proportional redistribution
for genuinely absent JD categories only, aligned with the authoritative 45 / 40 / 15 model.
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
    """Test 1: All scored categories present in JD -> weights remain 45 / 40 / 15."""
    comp = _build_components(req_score=100.0, pref_score=100.0, resp_score=100.0, proj_score=100.0)
    _, _, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "preferred_skills", "responsibilities"}
    )
    assert eff_weights["required_skills"] == 45.0
    assert eff_weights["preferred_skills"] == 15.0
    assert eff_weights["responsibilities"] == 40.0
    assert eff_weights["projects"] == 0.0
    assert sum(eff_weights[c] for c in ("required_skills", "preferred_skills", "responsibilities")) == 100.0


def test_2_preferred_skills_absent():
    """
    Test 2: Preferred Skills absent.
    Active total: 45 + 40 = 85.
    Required: 45/85 = 52.9412%, Resp: 40/85 = 47.0588%.
    """
    comp = _build_components(req_score=100.0, resp_score=100.0, proj_score=100.0)
    _, _, _, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "responsibilities"}
    )
    assert pytest.approx(eff_weights["required_skills"], rel=1e-4) == 52.9412
    assert pytest.approx(eff_weights["responsibilities"], rel=1e-4) == 47.0588
    assert eff_weights["preferred_skills"] == 0.0
    assert pytest.approx(sum(eff_weights.values()), abs=1e-3) == 100.0


def test_3_responsibilities_absent():
    """
    Test 3: Responsibilities absent.
    Active total: 45 + 15 = 60.
    Required: 45/60 = 75.0%, Preferred: 15/60 = 25.0%.
    """
    comp = _build_components(req_score=100.0, pref_score=100.0, resp_score=100.0)
    _, _, _, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "preferred_skills"}
    )
    assert pytest.approx(eff_weights["required_skills"], rel=1e-4) == 75.0
    assert pytest.approx(eff_weights["preferred_skills"], rel=1e-4) == 25.0
    assert eff_weights["responsibilities"] == 0.0
    assert pytest.approx(sum(eff_weights.values()), abs=1e-3) == 100.0


def test_4_only_required_skills():
    """Test 4: Only Required Skills present -> Required Skills = 100%."""
    comp = _build_components(req_score=100.0)
    _, _, _, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills"}
    )
    assert eff_weights["required_skills"] == 100.0
    assert eff_weights["preferred_skills"] == 0.0
    assert eff_weights["responsibilities"] == 0.0
    assert eff_weights["projects"] == 0.0


def test_5_all_categories_absent_safe_handling():
    """Test 5: All categories absent -> safe handling, no division by zero, score is 0.0."""
    comp = _build_components()
    weighted, raw, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories=set()
    )
    assert total == 0.0
    assert raw == 0.0
    assert all(w == 0.0 for w in eff_weights.values())


def test_6_category_exists_but_candidate_scores_zero_does_not_redistribute():
    """
    Test 6: Category exists in JD, but candidate scores 0.
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
    _, _, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "preferred_skills", "responsibilities"}
    )
    # Weights must NOT be redistributed
    assert eff_weights["required_skills"] == 45.0
    assert eff_weights["preferred_skills"] == 15.0
    assert eff_weights["responsibilities"] == 40.0
    # Capped by safeguard when required skills is 0%
    assert total <= 35.0


def test_7_different_item_counts_do_not_alter_effective_weights():
    """Test 7: Changing item counts does not change effective weights."""
    comp_a = _build_components(
        req_score=100.0,
        req_matched=["Python", "FastAPI"],
        resp_score=100.0,
        resp_matched=[f"Resp {i}" for i in range(8)],
        proj_score=100.0,
        pref_score=100.0,
    )
    _, _, _, eff_a = WeightCalculationService.calculate(
        comp_a, applicable_categories={"required_skills", "responsibilities", "preferred_skills"}
    )
    assert eff_a["required_skills"] == 45.0
    assert eff_a["responsibilities"] == 40.0
    assert eff_a["preferred_skills"] == 15.0


def test_8_preferred_skill_bonus_not_added_to_final_score():
    """Test 8: Preferred skills contribute strictly via their effective weight, no external +2 bonus."""
    comp = _build_components(req_score=100.0, pref_score=100.0, resp_score=100.0, proj_score=100.0)
    final = WeightCalculationService.final_score(bonus_total=10.0, components=comp)
    assert final == 100.0


def test_9_end_to_end_score_calculation_with_redistribution():
    """
    Test 9: End to end calculation with redistribution:
    Required Skills score  = 75
    Preferred Skills score = N/A (absent)
    Responsibilities score = 50

    Active weights: 45/85 (52.9412%), 40/85 (47.0588%).
    Expected: (75 * 45/85) + (50 * 40/85)
            = 39.7059 + 23.5294 = 63.2353 -> 63.24.
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
        comp, applicable_categories={"required_skills", "responsibilities"}
    )
    assert total == 63.24
    assert WeightCalculationService.final_score(
        components=comp, applicable_categories={"required_skills", "responsibilities"}
    ) == 63.24


def test_10_active_preferred_skills_with_zero_matches():
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
    weighted, _, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "preferred_skills", "responsibilities"}
    )
    assert eff_weights["preferred_skills"] == 15.0
    assert comp.preferred_skills.score == 0.0
    assert weighted.preferred_skills == 0.0
    # 100 * 0.45 + 100 * 0.40 + 0 * 0.15 = 85.0
    assert total == 85.0


def test_11_active_preferred_skills_with_all_matches():
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
        comp, applicable_categories={"required_skills", "preferred_skills", "responsibilities"}
    )
    assert eff_weights["preferred_skills"] == 15.0
    assert comp.preferred_skills.score == 100.0
    assert weighted.preferred_skills == 15.0


def test_12_inactive_categories_do_not_participate_in_final_score():
    """Backend Test E: Inactive categories do not participate in final weighted score."""
    comp = _build_components(
        req_score=90.0,
        resp_score=60.0,
        pref_score=0.0,
        proj_score=0.0,
    )
    _, _, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "responsibilities"}
    )
    # 90 * (45/85) + 60 * (40/85) = 47.647 + 28.235 = 75.88
    assert total == 75.88
    assert eff_weights["preferred_skills"] == 0.0
    assert eff_weights["projects"] == 0.0


def test_13_active_categories_use_actual_calculated_score():
    """Backend Test F: Active categories continue using their actual calculated score."""
    comp = _build_components(
        req_score=80.0,
        pref_score=60.0,
        resp_score=70.0,
        proj_score=90.0,
    )
    _, _, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "preferred_skills", "responsibilities"}
    )
    # 80 * 0.45 + 70 * 0.40 + 60 * 0.15 = 36 + 28 + 9 = 73.0
    assert total == 73.0
    assert eff_weights["required_skills"] == 45.0
    assert eff_weights["responsibilities"] == 40.0
    assert eff_weights["preferred_skills"] == 15.0
    assert eff_weights["projects"] == 0.0
