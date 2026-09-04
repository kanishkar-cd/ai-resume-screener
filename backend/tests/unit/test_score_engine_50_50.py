"""
Unit Tests for Score Engine 50 / 50 Weightage Model:
- Required Skills: 50%
- Roles & Responsibilities: 50%
- Preferred Skills: 0%
- Total = 100%
"""
import pytest
from types import SimpleNamespace

from app.schemas.scoring import ComponentScoreDetail, ComponentScores
from app.schemas.weight_config import WeightDistribution, WeightConfigCreate
from app.services.scoring.weight_calculation_service import (
    DEFAULT_WEIGHTS,
    COMPONENT_WEIGHTS,
    WeightCalculationService,
    validate_weights,
)


def _build_test_components(
    req_score: float = 0.0,
    resp_score: float = 0.0,
    pref_score: float = 0.0,
) -> ComponentScores:
    return ComponentScores(
        skills=ComponentScoreDetail(
            score=req_score,
            matched_items=["Python"] if req_score > 0 else [],
            missing_items=[] if req_score == 100.0 else ["FastAPI"],
            explanation="required skills",
        ),
        responsibilities=ComponentScoreDetail(
            score=resp_score,
            matched_items=["API development"] if resp_score > 0 else [],
            missing_items=[] if resp_score == 100.0 else ["DevOps"],
            explanation="responsibilities",
        ),
        preferred_skills=ComponentScoreDetail(
            score=pref_score,
            matched_items=["Docker"] if pref_score > 0 else [],
            missing_items=[] if pref_score == 100.0 else ["Kubernetes"],
            explanation="preferred skills",
        ),
        projects=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation="projects (evidence only)"),
        experience=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation="experience (evidence only)"),
        education=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation="education (evidence only)"),
        certifications=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation="certifications (evidence only)"),
        languages=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation="languages (evidence only)"),
    )


def test_50_50_default_weights_definition():
    """Verify DEFAULT_WEIGHTS is strictly 50/50 and sums to 100%."""
    assert DEFAULT_WEIGHTS["required_skills"] == 50.0
    assert DEFAULT_WEIGHTS["responsibilities"] == 50.0
    assert DEFAULT_WEIGHTS["preferred_skills"] == 0.0
    assert DEFAULT_WEIGHTS["projects"] == 0.0
    assert DEFAULT_WEIGHTS["experience"] == 0.0
    assert DEFAULT_WEIGHTS["education"] == 0.0
    assert DEFAULT_WEIGHTS["certifications"] == 0.0
    assert DEFAULT_WEIGHTS["languages"] == 0.0
    assert sum(DEFAULT_WEIGHTS.values()) == 100.0
    validate_weights(DEFAULT_WEIGHTS)


def test_50_50_both_categories_active():
    """When both Required Skills and Responsibilities are active, effective weights are 50% and 50%."""
    comp = _build_test_components(req_score=80.0, resp_score=60.0)
    weighted, raw_total, weighted_total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "responsibilities"}
    )
    assert eff_weights["required_skills"] == 50.0
    assert eff_weights["responsibilities"] == 50.0
    assert eff_weights["preferred_skills"] == 0.0
    # Expected: (80.0 * 0.50) + (60.0 * 0.50) = 40.0 + 30.0 = 70.0
    assert weighted.skills == 40.0
    assert weighted.responsibilities == 30.0
    assert weighted_total == 70.0


def test_50_50_responsibilities_absent_redistributes_to_100_percent_skills():
    """When responsibilities are absent from the JD, Required Skills receives 100% weight."""
    comp = _build_test_components(req_score=85.0, resp_score=0.0)
    weighted, raw_total, weighted_total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills"}
    )
    assert eff_weights["required_skills"] == 100.0
    assert eff_weights["responsibilities"] == 0.0
    assert weighted_total == 85.0


def test_50_50_skills_absent_redistributes_to_100_percent_responsibilities():
    """When skills are absent from the JD, Responsibilities receives 100% weight."""
    comp = _build_test_components(req_score=0.0, resp_score=90.0)
    weighted, raw_total, weighted_total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"responsibilities"}
    )
    assert eff_weights["responsibilities"] == 100.0
    assert eff_weights["required_skills"] == 0.0
    assert weighted_total == 90.0


def test_50_50_safeguard_zero_skills():
    """Candidate with 0% required skills is capped at the 35% ceiling."""
    comp = _build_test_components(req_score=0.0, resp_score=100.0)
    weighted, raw_total, weighted_total, eff_weights = WeightCalculationService.calculate(
        comp, applicable_categories={"required_skills", "responsibilities"}
    )
    # 0 * 0.5 + 100 * 0.5 = 50.0, but capped at 35.0 by safeguard
    assert weighted_total <= 35.0


def test_50_50_schema_defaults():
    """WeightDistribution schema defaults to 50/50/0."""
    dist = WeightDistribution()
    assert dist.required_skills == 50.0
    assert dist.responsibilities == 50.0
    assert dist.preferred_skills == 0.0
    config_create = WeightConfigCreate()
    assert config_create.weights.required_skills == 50.0
    assert config_create.weights.responsibilities == 50.0
    assert config_create.weights.preferred_skills == 0.0
