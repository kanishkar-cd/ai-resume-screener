"""
Target Weight Model Unit Tests (45 / 40 / 15)

Verifies:
- Test 1: All three categories present (45/40/15 -> 100%)
- Test 2: Preferred Skills absent (45/40 -> 52.9412% / 47.0588%)
- Test 3: Responsibilities absent (45/15 -> 75% / 25%)
- Test 4: Only Required Skills present (100%)
- Test 5: Preferred exists but candidate has 0 match (15% remains, not redistributed)
- Test 6: Candidate has required skill only in project (project evidence matches skill)
- Test 7: Candidate responsibility appears only in experience
- Test 8: Certification supports a skill (AWS Certified Developer supports AWS; no independent cert score)
- Test 9: Old weights (30/25/25/15/5) cannot appear
- Test 10: Schema and runtime consistency
- Test 11: Custom configuration (50/30/20 overrides default 45/40/15 at runtime)
- Test 12: Score range (0 <= final_score <= 100)
- Bonus Safeguard Test: Required skill protection prevents candidate with 0% required skills from high match score
"""
import pytest
from types import SimpleNamespace

from app.schemas.scoring import ComponentScoreDetail, ComponentScores
from app.schemas.weight_config import WeightDistribution, WeightConfigCreate
from app.services.scoring.weight_calculation_service import (
    DEFAULT_WEIGHTS,
    WeightCalculationService,
    validate_weights,
)
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.matching_service import (
    DeterministicRequirementMatcher,
    EvidenceBuilder,
    RequirementBuilder,
    is_entity_compatible,
    ALLOWED_EVIDENCE_MAP,
)
from app.schemas.matching import RequirementKind, MatchStatus


def _build_test_components(
    req_score: float = 0.0,
    resp_score: float = 0.0,
    pref_score: float = 0.0,
    req_matched: list[str] | None = None,
    req_missing: list[str] | None = None,
    resp_matched: list[str] | None = None,
    resp_missing: list[str] | None = None,
    pref_matched: list[str] | None = None,
    pref_missing: list[str] | None = None,
) -> ComponentScores:
    return ComponentScores(
        skills=ComponentScoreDetail(
            score=req_score,
            matched_items=req_matched if req_matched is not None else (["Python"] if req_score > 0 else []),
            missing_items=req_missing if req_missing is not None else ([] if req_score == 100.0 else ["FastAPI"]),
            explanation="required skills",
        ),
        responsibilities=ComponentScoreDetail(
            score=resp_score,
            matched_items=resp_matched if resp_matched is not None else (["API development"] if resp_score > 0 else []),
            missing_items=resp_missing if resp_missing is not None else ([] if resp_score == 100.0 else ["DevOps"]),
            explanation="responsibilities",
        ),
        preferred_skills=ComponentScoreDetail(
            score=pref_score,
            matched_items=pref_matched if pref_matched is not None else (["Docker"] if pref_score > 0 else []),
            missing_items=pref_missing if pref_missing is not None else ([] if pref_score == 100.0 else ["Kubernetes"]),
            explanation="preferred skills",
        ),
        projects=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation="projects (evidence only)"),
        experience=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation="experience (evidence only)"),
        education=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation="education (evidence only)"),
        certifications=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation="certifications (evidence only)"),
        languages=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation="languages (evidence only)"),
    )


def test_1_all_three_categories_present():
    """Test 1: All three categories present -> Required=45, Responsibilities=40, Preferred=15. Total=100%."""
    comp = _build_test_components(req_score=100.0, resp_score=100.0, pref_score=100.0)
    weighted_schema, raw_total, weighted_total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "responsibilities", "preferred_skills"}
    )
    assert eff_weights["required_skills"] == 45.0
    assert eff_weights["responsibilities"] == 40.0
    assert eff_weights["preferred_skills"] == 15.0
    assert eff_weights["projects"] == 0.0
    assert eff_weights["certifications"] == 0.0
    assert pytest.approx(sum(eff_weights.values()), abs=1e-4) == 100.0
    assert weighted_total == 100.0


def test_2_preferred_skills_absent():
    """
    Test 2: Preferred Skills absent.
    Active base total: 45 + 40 = 85.
    Expected effective weights:
    Required = 45 / 85 * 100 = 52.9412%
    Responsibilities = 40 / 85 * 100 = 47.0588%
    Total = 100%.
    """
    comp = _build_test_components(req_score=100.0, resp_score=100.0, pref_score=0.0)
    _, _, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "responsibilities"}
    )
    assert pytest.approx(eff_weights["required_skills"], rel=1e-4) == 52.9412
    assert pytest.approx(eff_weights["responsibilities"], rel=1e-4) == 47.0588
    assert eff_weights["preferred_skills"] == 0.0
    assert pytest.approx(sum(eff_weights.values()), abs=1e-4) == 100.0
    assert total == 100.0


def test_3_responsibilities_absent():
    """
    Test 3: Responsibilities absent.
    Active base total: 45 + 15 = 60.
    Expected:
    Required = 45 / 60 * 100 = 75.0%
    Preferred = 15 / 60 * 100 = 25.0%
    Total = 100%.
    """
    comp = _build_test_components(req_score=100.0, resp_score=0.0, pref_score=100.0)
    _, _, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "preferred_skills"}
    )
    assert eff_weights["required_skills"] == 75.0
    assert eff_weights["preferred_skills"] == 25.0
    assert eff_weights["responsibilities"] == 0.0
    assert pytest.approx(sum(eff_weights.values()), abs=1e-4) == 100.0
    assert total == 100.0


def test_4_only_required_skills_present():
    """
    Test 4: Only Required Skills present.
    Required = 100%. Valid normalization because it is the only active scored category.
    """
    comp = _build_test_components(req_score=80.0, resp_score=0.0, pref_score=0.0)
    _, _, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills"}
    )
    assert eff_weights["required_skills"] == 100.0
    assert eff_weights["responsibilities"] == 0.0
    assert eff_weights["preferred_skills"] == 0.0
    assert pytest.approx(sum(eff_weights.values()), abs=1e-4) == 100.0
    assert total == 80.0


def test_5_preferred_exists_but_candidate_zero_matches():
    """
    Test 5: Preferred exists in JD but candidate has 0 preferred matches.
    Preferred remains active at 15%.
    Its weight must NOT be redistributed.
    Contribution = 0 * 15% = 0.
    """
    comp = _build_test_components(
        req_score=100.0,
        resp_score=80.0,
        pref_score=0.0,
        pref_matched=[],
        pref_missing=["Docker"],
    )
    weighted, _, total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "responsibilities", "preferred_skills"}
    )
    # Weight must not be transferred
    assert eff_weights["preferred_skills"] == 15.0
    assert eff_weights["required_skills"] == 45.0
    assert eff_weights["responsibilities"] == 40.0
    assert weighted.preferred_skills == 0.0
    # Expected total: 100 * 0.45 + 80 * 0.40 + 0 * 0.15 = 45 + 32 = 77.0
    assert total == 77.0


def test_6_candidate_has_required_skill_only_in_project():
    """
    Test 6: Candidate has required skill only in project.
    JD requires Python. Resume has skills: Java, and project: 'Developed the backend using Python.'
    Python should receive relevant evidence from the project and match.
    """
    resume = SimpleNamespace(
        skills=["Java"],
        experience=[],
        projects=[{
            "name": "Backend Service",
            "description": "Developed the backend using Python and Flask.",
            "technologies": ["Python", "Flask"],
        }],
        certifications=[],
        summary="",
    )
    job = SimpleNamespace(required_skills=["Python"], skills=["Python"], responsibilities=[], preferred_skills=[])
    service = ComponentScoringService()
    scores = service.score(resume, job, config=None, projects=resume.projects)

    assert "Python" in scores.skills.matched_items
    assert scores.skills.score == 100.0


def test_7_candidate_responsibility_appears_only_in_experience():
    """
    Test 7: Candidate responsibility appears only in experience.
    JD: 'Design and develop REST APIs.'
    Resume: Work experience: 'Designed and maintained REST APIs using FastAPI.'
    Expected: Strong responsibilities match.
    """
    resume = SimpleNamespace(
        skills=["Python"],
        experience=[{
            "title": "Backend Engineer",
            "description": "Designed and maintained REST APIs using FastAPI for microservices.",
            "responsibilities": ["Designed and maintained REST APIs using FastAPI."],
        }],
        projects=[],
        certifications=[],
        summary="",
    )
    job = SimpleNamespace(
        required_skills=["Python"],
        skills=["Python"],
        responsibilities=["Design and develop REST APIs."],
        preferred_skills=[],
    )
    service = ComponentScoringService()
    scores = service.score(resume, job, config=None)
    assert scores.responsibilities.score >= 50.0


def test_8_certification_supports_a_skill():
    """
    Test 8: Certification supports a skill.
    JD: AWS
    Resume: Certification: AWS Certified Developer
    Expected:
    - Certification can provide evidence for Required Skill AWS.
    - Certification must NOT independently add another separate score category.
    """
    resume = SimpleNamespace(
        skills=["Python"],
        certifications=[{"name": "AWS Certified Developer - Associate", "title": "AWS Certified Developer"}],
        experience=[],
        projects=[],
        summary="",
    )
    job = SimpleNamespace(
        required_skills=["AWS", "Python"],
        skills=["AWS", "Python"],
        responsibilities=[],
        preferred_skills=[],
    )
    service = ComponentScoringService()
    scores = service.score(resume, job, config=None)

    assert "AWS" in scores.skills.matched_items or any("aws" in m.lower() for m in scores.skills.matched_items)
    assert scores.skills.score == 100.0

    # In WeightCalculationService, certifications has 0% weight
    app_cats = WeightCalculationService.applicable_categories(job)
    assert "certifications" not in app_cats or app_cats.get("certifications", False) is False
    _, _, _, eff_weights = WeightCalculationService.calculate(scores, applicable_categories=app_cats)
    assert eff_weights.get("certifications", 0.0) == 0.0


def test_9_old_weights_cannot_appear():
    """
    Test 9: Old weights cannot appear.
    Verify that old values (30/25/25/15/5) do not influence runtime scoring:
    DEFAULT_WEIGHTS must strictly have 45 / 40 / 15 and 0 for all others.
    """
    assert DEFAULT_WEIGHTS["required_skills"] == 45.0
    assert DEFAULT_WEIGHTS["responsibilities"] == 40.0
    assert DEFAULT_WEIGHTS["preferred_skills"] == 15.0
    assert DEFAULT_WEIGHTS["projects"] == 0.0
    assert DEFAULT_WEIGHTS["certifications"] == 0.0
    assert DEFAULT_WEIGHTS["experience"] == 0.0
    assert DEFAULT_WEIGHTS["education"] == 0.0
    assert DEFAULT_WEIGHTS["languages"] == 0.0
    assert sum(DEFAULT_WEIGHTS.values()) == 100.0


def test_10_schema_and_runtime_consistency():
    """
    Test 10: Schema and runtime consistency.
    Verify that API / schema defaults do not advertise one model while engine executes another.
    """
    schema_dist = WeightDistribution()
    assert schema_dist.required_skills == 45.0
    assert schema_dist.responsibilities == 40.0
    assert schema_dist.preferred_skills == 15.0
    assert schema_dist.projects == 0.0
    assert schema_dist.certifications == 0.0

    config_create = WeightConfigCreate()
    assert config_create.weights.required_skills == 45.0
    assert config_create.weights.responsibilities == 40.0
    assert config_create.weights.preferred_skills == 15.0


def test_11_custom_configuration():
    """
    Test 11: Custom configuration.
    Set: Required = 50, Responsibilities = 30, Preferred = 20.
    Verify the actual runtime final score uses 50/30/20 and not default 45/40/15.
    """
    custom_cfg = SimpleNamespace(
        weights={
            "required_skills": 50.0,
            "responsibilities": 30.0,
            "preferred_skills": 20.0,
        }
    )
    comp = _build_test_components(req_score=100.0, resp_score=50.0, pref_score=100.0)
    weighted, _, total, eff_weights = WeightCalculationService.calculate(
        comp, config=custom_cfg, applicable_categories={"required_skills", "responsibilities", "preferred_skills"}
    )
    assert eff_weights["required_skills"] == 50.0
    assert eff_weights["responsibilities"] == 30.0
    assert eff_weights["preferred_skills"] == 20.0
    # Expected: 100 * 0.50 + 50 * 0.30 + 100 * 0.20 = 50 + 15 + 20 = 85.0
    assert total == 85.0


def test_12_score_range():
    """
    Test 12: Score range.
    Verify 0 <= final_score <= 100 across multiple score combinations.
    """
    test_cases = [
        (0.0, 0.0, 0.0),
        (100.0, 100.0, 100.0),
        (50.0, 75.0, 25.0),
        (33.33, 66.67, 99.99),
        (0.0, 100.0, 100.0),
        (100.0, 0.0, 0.0),
    ]
    for r_score, resp_score, p_score in test_cases:
        comp = _build_test_components(req_score=r_score, resp_score=resp_score, pref_score=p_score)
        _, _, total, _ = WeightCalculationService.calculate(
            comp, applicable_categories={"required_skills", "responsibilities", "preferred_skills"}
        )
        final = WeightCalculationService.final_score(components=comp, applicable_categories={"required_skills", "responsibilities", "preferred_skills"})
        assert 0.0 <= total <= 100.0
        assert 0.0 <= final <= 100.0


def test_required_skill_protection_safeguard():
    """
    Required Skill Protection Safeguard:
    A candidate with 0% required skill match, but 100% responsibilities and 100% preferred skills
    must not receive an unrealistically high match score (e.g. 55%).
    The safeguard must cap the final score to <= SAFEGUARD_ZERO_SKILLS_MAX_SCORE (35.0).
    """
    comp = _build_test_components(
        req_score=0.0,
        req_matched=[],
        req_missing=["Python", "FastAPI"],
        resp_score=100.0,
        pref_score=100.0,
    )
    _, _, total, _ = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "responsibilities", "preferred_skills"}
    )
    # Without safeguard: 0 * 0.45 + 100 * 0.40 + 100 * 0.15 = 55.0
    # With safeguard: score is capped to 35.0
    assert total <= 35.0
    assert total == 35.0
