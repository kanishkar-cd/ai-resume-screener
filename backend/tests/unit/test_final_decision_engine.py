from types import SimpleNamespace

from app.schemas.scoring import ComponentScoreDetail, ComponentScores, RecommendationLevel
from app.services.scoring import (
    BonusService, ConfidenceService, PenaltyService, RecommendationService,
    WeightCalculationService,
)


def _components(score: float = 80, missing_skills: list[str] | None = None, experience_missing: list[str] | None = None) -> ComponentScores:
    detail = lambda value=score: ComponentScoreDetail(score=value, explanation="test")
    return ComponentScores(
        skills=ComponentScoreDetail(score=score, missing_items=missing_skills or [], explanation="test"),
        responsibilities=detail(),
        experience=ComponentScoreDetail(score=score, missing_items=experience_missing or [], explanation="test"),
        projects=detail(), preferred_skills=detail(), education=detail(), certifications=detail(), languages=detail(),
    )


def test_weights_penalty_bonus_caps_and_final_formula() -> None:
    config = SimpleNamespace(
        skills_weight=40, experience_weight=25, projects_weight=15, education_weight=10,
        certifications_weight=5, languages_weight=5, mandatory_skills=["Python", "SQL", "Docker", "AWS"],
        preferred_skills=[f"S{i}" for i in range(10)], knockout_rules=[], min_experience_years=10,
        required_degree="Bachelor of Engineering",
    )
    components = _components(80, ["Python", "SQL", "Docker", "AWS"], ["120 months"])
    weighted, raw, total, _ = WeightCalculationService.calculate(components, config)
    penalties, _ = PenaltyService.calculate(components, config)
    resume = SimpleNamespace(skills=[f"S{i}" for i in range(10)], experience=[{"duration_months": 200}], education=[{"degree": "Master of Science"}])
    job = SimpleNamespace(skills=[], experience_requirements=[{"minimum_months": 120}], degree_requirements=[])
    bonuses, _ = BonusService.calculate(resume, job, config, components)
    assert raw == 80 and total == 80
    assert penalties == 0.0 and bonuses == 15
    assert WeightCalculationService.final_score(total, penalties, bonuses) == 95.0



def test_knockout_confidence_and_recommendation_thresholds() -> None:
    config = SimpleNamespace(mandatory_skills=["Python"], knockout_rules=[{"rule_type": "MISSING_MANDATORY_SKILL", "enabled": True}])
    knocked, reason = WeightCalculationService.knockout(_components(missing_skills=["Python"]), config)
    assert knocked and "Python" in reason
    extracted = SimpleNamespace(**{name: "x" for name in ConfidenceService.FIELDS})
    assert ConfidenceService.calculate(extracted) == 100
    assert RecommendationService.recommend(90, 70, use_absolute_thresholds=True) == RecommendationLevel.SHORTLIST
    assert RecommendationService.recommend(75, 70, use_absolute_thresholds=True) == RecommendationLevel.REVIEW
    assert RecommendationService.recommend(60, 70, use_absolute_thresholds=True) == RecommendationLevel.CONSIDER
    assert RecommendationService.recommend(40, 70, use_absolute_thresholds=True) == RecommendationLevel.REJECT

    assert RecommendationService.recommend(100, 70, True) == RecommendationLevel.REJECT


def test_knockout_matching_is_case_insensitive_and_reason_is_deduplicated() -> None:
    config = SimpleNamespace(
        mandatory_skills=["JavaScript", "javascript", "Python"],
        knockout_rules=[{"rule_type": "MISSING_MANDATORY_SKILL", "enabled": True}],
    )
    knocked, reason = WeightCalculationService.knockout(
        _components(missing_skills=["JavaScript", "javascript"]), config
    )
    assert knocked is True
    assert reason == "Missing mandatory skills: JavaScript"


def test_na_categories_redistribute_weight_to_applicable_criteria() -> None:
    config = SimpleNamespace(
        skills_weight=40, experience_weight=25, projects_weight=15,
        education_weight=10, certifications_weight=5, languages_weight=5,
    )
    components = _components(80)
    weighted, raw, total, _ = WeightCalculationService.calculate(
        components, config, {"skills", "projects", "education"}
    )
    # Skills (80) + Projects (80) normalized to 100% active weight -> total = 80.0
    assert total == 80.0
    assert weighted.experience == 0
    assert weighted.certifications == 0
    assert weighted.languages == 0


def test_applicable_categories_exclude_unconfigured_experience_certifications_and_languages() -> None:
    job = SimpleNamespace(
        skills=["Python"], keywords=["API"], degree_requirements=["Bachelor's Degree"],
        experience_requirements=[{"minimum_months": 0}],
    )
    config = SimpleNamespace(
        mandatory_skills=[], min_experience_years=0, required_degree=None,
        required_certifications=[], required_languages=[],
    )
    app_cats = WeightCalculationService.applicable_categories(job, config)
    assert "skills" in app_cats or "required_skills" in app_cats
    assert "education" in app_cats
    assert "projects" not in app_cats
    assert "certifications" not in app_cats
    assert "languages" not in app_cats


def test_knockout_does_not_destroy_merit_score() -> None:
    assert WeightCalculationService.final_score(55.75, 0, 0) == 55.75
