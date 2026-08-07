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
        experience=ComponentScoreDetail(score=score, missing_items=experience_missing or [], explanation="test"),
        projects=detail(), education=detail(), certifications=detail(), languages=detail(),
    )


def test_weights_penalty_bonus_caps_and_final_formula() -> None:
    config = SimpleNamespace(
        skills_weight=40, experience_weight=25, projects_weight=15, education_weight=10,
        certifications_weight=5, languages_weight=5, mandatory_skills=["Python", "SQL", "Docker", "AWS"],
        preferred_skills=[f"S{i}" for i in range(10)], knockout_rules=[], min_experience_years=10,
        required_degree="Bachelor of Engineering",
    )
    components = _components(80, ["Python", "SQL", "Docker", "AWS"], ["120 months"])
    weighted, raw, total = WeightCalculationService.calculate(components, config)
    penalties, _ = PenaltyService.calculate(components, config)
    resume = SimpleNamespace(skills=[f"S{i}" for i in range(10)], experience=[{"duration_months": 200}], education=[{"degree": "Master of Science"}])
    job = SimpleNamespace(skills=[], experience_requirements=[{"minimum_months": 120}], degree_requirements=[])
    bonuses, _ = BonusService.calculate(resume, job, config, components)
    assert raw == 80 and total == 80 and sum(weighted.model_dump().values()) == 80
    assert penalties == 30 and bonuses == 15
    assert max(0, min(100, total - penalties + bonuses)) == 65


def test_knockout_confidence_and_recommendation_thresholds() -> None:
    config = SimpleNamespace(mandatory_skills=["Python"], knockout_rules=[{"rule_type": "MISSING_MANDATORY_SKILL", "enabled": True}])
    knocked, reason = WeightCalculationService.knockout(_components(missing_skills=["Python"]), config)
    assert knocked and "Python" in reason
    extracted = SimpleNamespace(**{name: "x" for name in ConfidenceService.FIELDS})
    assert ConfidenceService.calculate(extracted) == 100
    assert RecommendationService.recommend(90, 70) == RecommendationLevel.SHORTLIST
    assert RecommendationService.recommend(75, 70) == RecommendationLevel.REVIEW
    assert RecommendationService.recommend(60, 70) == RecommendationLevel.CONSIDER
    assert RecommendationService.recommend(40, 70) == RecommendationLevel.REJECT

    assert RecommendationService.recommend(100, 70, True) == RecommendationLevel.REJECT

