from types import SimpleNamespace

from app.schemas.scoring import ComponentScores
from app.services.scoring.component_scoring_service import ComponentScoringService


def test_component_engine_formulas_and_boundaries() -> None:
    resume = SimpleNamespace(
        skills=["Python", "Docker"], experience=[{"duration_months": 36}],
        education=[{"degree": "Master of Science"}], certifications=["AWS"], languages=["English"],
    )
    job = SimpleNamespace(
        skills=["Python", "PostgreSQL"], experience_requirements=[{"minimum_months": 48}],
        degree_requirements=["Bachelor of Engineering"], keywords=["Docker"],
    )
    config = SimpleNamespace(mandatory_skills=[], min_experience_years=3, required_degree=None, required_certifications=["AWS"])
    scores = ComponentScoringService().score(resume, job, config, [{"technologies": ["Docker"], "name": "Platform"}])
    assert scores.skills.score == 50 and scores.skills.missing_items == ["PostgreSQL"]
    assert scores.experience.score == 75
    assert scores.education.score == 100
    assert scores.projects.score == 100
    assert scores.certifications.score == 100
    assert scores.languages.score == 100


def test_no_requirement_component_scores_one_hundred() -> None:
    resume = SimpleNamespace(skills=[], experience=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(skills=[], experience_requirements=[], degree_requirements=[], keywords=[])
    config = SimpleNamespace(mandatory_skills=[], min_experience_years=0, required_degree=None, required_certifications=[])
    scores = ComponentScoringService().score(resume, job, config)
    assert all(getattr(scores, name).score == 100 for name in ComponentScores.model_fields)



def test_stage5_deterministic_scoring_matching_and_bounds() -> None:
    from app.services.scoring.weight_calculation_service import WeightCalculationService
    from app.services.scoring.recommendation_service import RecommendationService

    resume = SimpleNamespace(
        skills=["Python", "FastAPI", "Docker", "PostgreSQL"],
        experience=[{"duration_months": 24}],
        education=[{"degree": "Bachelor of Technology"}],
        certifications=["AWS Certified Cloud Practitioner"],
        languages=["English"],
    )
    job = SimpleNamespace(
        skills=["Python", "FastAPI", "Docker", "Kubernetes"],
        experience_requirements=[{"minimum_months": 24}],
        degree_requirements=["Bachelor of Technology"],
        keywords=["Docker"],
    )
    config = SimpleNamespace(
        skills_weight=40,
        experience_weight=20,
        projects_weight=15,
        education_weight=15,
        certifications_weight=10,
        languages_weight=0,
        mandatory_skills=["Python"],
        min_experience_years=2,
        required_degree="Bachelor of Technology",
        required_certifications=["AWS Certified Cloud Practitioner"],
        knockout_rules=[],
    )

    scores = ComponentScoringService().score(
        resume, job, config, [{"name": "Web App", "technologies": ["Docker", "FastAPI"]}]
    )

    # 1. Exact vs Partial matching
    assert scores.skills.matched_items == ["Python", "FastAPI", "Docker"]
    assert scores.skills.missing_items == ["Kubernetes"]
    assert scores.skills.score == 75.0

    # 2. Experience & Education exact match
    assert scores.experience.score == 100.0
    assert scores.education.score == 100.0

    # 3. Weighted total score calculation using project weight configuration
    weighted_scores, raw_total, weighted_total = WeightCalculationService.calculate(scores, config)
    assert 0 <= raw_total <= 100
    assert 0 <= weighted_total <= 100

    # 4. Recommendation thresholds testing (>=85 SHORTLIST, 70-84 REVIEW, 50-69 CONSIDER, <50 REJECT)
    from app.schemas.scoring import RecommendationLevel
    assert RecommendationService.recommend(88.0, use_absolute_thresholds=True) == RecommendationLevel.SHORTLIST
    assert RecommendationService.recommend(78.0, use_absolute_thresholds=True) == RecommendationLevel.REVIEW
    assert RecommendationService.recommend(60.0, use_absolute_thresholds=True) == RecommendationLevel.CONSIDER
    assert RecommendationService.recommend(45.0, use_absolute_thresholds=True) == RecommendationLevel.REJECT
    assert RecommendationService.recommend(90.0, is_knocked_out=True, use_absolute_thresholds=True) == RecommendationLevel.REJECT


def test_stage5_recommendation_enum_and_summary_fields() -> None:
    from app.schemas.scoring import RecommendationLevel, CandidateScoreCreate, ComponentScoreDetail, ComponentScores, WeightedScores

    # 1. Recommendation enum values check
    assert RecommendationLevel.SHORTLIST.value == "SHORTLIST"
    assert RecommendationLevel.REVIEW.value == "REVIEW"
    assert RecommendationLevel.CONSIDER.value == "CONSIDER"
    assert RecommendationLevel.REJECT.value == "REJECT"

    # 2. Populated summary fields check
    detail = ComponentScoreDetail(score=100, matched_items=["Python"], missing_items=["Go"], explanation="Matched 1 skill.")
    components = ComponentScores(skills=detail, experience=detail, projects=detail, education=detail, certifications=detail, languages=detail)
    weighted = WeightedScores(skills=40, experience=20, projects=15, education=15, certifications=10, languages=0)

    score_data = CandidateScoreCreate(
        document_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        component_scores=components,
        weighted_scores=weighted,
        raw_total_score=100,
        weighted_total_score=100,
        penalty_total=0,
        bonus_total=0,
        final_score=100,
        confidence=100,
        recommendation=RecommendationLevel.SHORTLIST,
        weight_config_version=1,
        matched_skills=["Python"],
        missing_skills=["Go"],
        strengths=["Skills: Matched 1 skill."],
        weaknesses=[],
    )

    assert score_data.recommendation == RecommendationLevel.SHORTLIST
    assert score_data.matched_skills == ["Python"]
    assert score_data.missing_skills == ["Go"]
    assert score_data.strengths == ["Skills: Matched 1 skill."]
    assert score_data.weaknesses == []



