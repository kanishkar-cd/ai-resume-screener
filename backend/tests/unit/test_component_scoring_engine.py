from types import SimpleNamespace

import pytest

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


def test_required_skills_are_case_insensitive_and_deduplicated() -> None:
    service = ComponentScoringService()
    detail = service._match(
        ["javascript", "PYTHON", "sql"],
        ["JavaScript", "javascript", "Python", "SQL", "sql"],
        "required skills",
    )
    assert detail.score == 100
    assert detail.matched_items == ["JavaScript", "Python", "SQL"]
    assert detail.missing_items == []


def test_preferred_skills_are_case_insensitive_and_deduplicated() -> None:
    from app.services.scoring.bonus_service import BonusService

    resume = SimpleNamespace(
        skills=["react.JS"], experience=[], education=[]
    )
    job = SimpleNamespace(skills=[], experience_requirements=[], degree_requirements=[])
    config = SimpleNamespace(
        preferred_skills=["React.js", "REACT.JS"], min_experience_years=0,
        required_degree=None,
    )
    total, items = BonusService.calculate(
        resume, job, config,
        ComponentScoringService().score(
            SimpleNamespace(skills=[], experience=[], education=[], certifications=[], languages=[]),
            SimpleNamespace(skills=[], experience_requirements=[], degree_requirements=[], keywords=[]),
            SimpleNamespace(mandatory_skills=[], min_experience_years=0, required_degree=None, required_certifications=[]),
        ),
    )
    assert total == 2
    assert items[0].description == "Matched preferred skills: React.js"


@pytest.mark.parametrize(
    ("required", "candidate"),
    [
        ("Bachelor's Degree", "Bachelor of Engineering"),
        ("Bachelor's Degree", "Bachelor of Technology"),
        ("B.E.", "Bachelor's Degree"),
        ("B.Tech", "Bachelor's Degree"),
    ],
)
def test_bachelors_degree_equivalence(required: str, candidate: str) -> None:
    assert ComponentScoringService._education_score([candidate], required) == 100



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
    weighted_scores, raw_total, weighted_total, _ = WeightCalculationService.calculate(scores, config)
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


def test_or_alternative_skills_group_matching_and_50_mark_calculation() -> None:
    """
    Test generic AND/OR requirements:
    "Python or Java or JavaScript", "Docker", "PostgreSQL / MySQL"
    - Total 3 requirement groups.
    - Matching 'Python' satisfies Group 1 (1/3).
    - Matching 'Docker' satisfies Group 2 (2/3).
    - Candidate has no DB skill (missing Group 3).
    - Skill score = 2/3 * 100 = 66.67%.
    - Deterministic 50-mark contribution = 66.67% of 50 = 33.33 marks.
    """
    from app.services.scoring.weight_calculation_service import WeightCalculationService

    service = ComponentScoringService()
    job_reqs = ["Python or Java or JavaScript", "Docker", "PostgreSQL / MySQL"]

    # Candidate 1: Has Java, Docker, MySQL -> 100% match (3/3 groups satisfied)
    c1_resume = SimpleNamespace(skills=["Java", "Docker", "MySQL"], experience=[], education=[], certifications=[], languages=[])
    c1_job = SimpleNamespace(skills=[], required_skills=job_reqs, experience_requirements=[], degree_requirements=[], keywords=[])
    c1_config = SimpleNamespace(mandatory_skills=[], min_experience_years=0, required_degree=None, required_certifications=[])

    c1_scores = service.score(c1_resume, c1_job, c1_config)
    assert c1_scores.skills.score == 100.0
    assert len(c1_scores.skills.matched_items) == 3
    assert c1_scores.skills.missing_items == []
    # 100% skill score converts to exactly 50.0 marks out of 50
    assert (c1_scores.skills.score / 100.0) * 50.0 == 50.0

    # Candidate 2: Has Python only (satisfies 1 of 3 groups)
    c2_resume = SimpleNamespace(skills=["Python"], experience=[], education=[], certifications=[], languages=[])
    c2_scores = service.score(c2_resume, c1_job, c1_config)
    assert c2_scores.skills.score == 33.33
    assert c2_scores.skills.matched_items == ["Python"]
    assert len(c2_scores.skills.missing_items) == 2
    # 33.33% skill score converts to 16.66 marks out of 50
    assert round((c2_scores.skills.score / 100.0) * 50.0, 2) == 16.66


def test_6_out_of_12_required_skills_equals_25_out_of_50() -> None:
    """Requirement test: 6/12 required skills = 25/50 skill match score."""
    service = ComponentScoringService()
    req_skills = [f"Skill_{i}" for i in range(12)]
    candidate_skills = [f"Skill_{i}" for i in range(6)]

    resume = SimpleNamespace(skills=candidate_skills, experience=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=req_skills, skills=[], experience_requirements=[], degree_requirements=[], keywords=[])
    config = SimpleNamespace(mandatory_skills=[], min_experience_years=0, required_degree=None, required_certifications=[])

    scores = service.score(resume, job, config)
    assert scores.skills.score == 50.0  # 6/12 * 100
    deterministic_50 = (scores.skills.score / 100.0) * 50.0
    assert deterministic_50 == 25.0


def test_preferred_skills_do_not_increase_deterministic_skill_score() -> None:
    """Requirement test: Preferred skills must not increase the deterministic skill score."""
    service = ComponentScoringService()
    req_skills = ["Skill_A", "Skill_B"]
    pref_skills = ["Bonus_X", "Bonus_Y", "Bonus_Z"]

    # Candidate has 1 required skill + 3 preferred skills
    resume = SimpleNamespace(skills=["Skill_A", "Bonus_X", "Bonus_Y", "Bonus_Z"], experience=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=req_skills, preferred_skills=pref_skills, skills=[], experience_requirements=[], degree_requirements=[], keywords=[])
    config = SimpleNamespace(mandatory_skills=[], min_experience_years=0, required_degree=None, required_certifications=[])

    scores = service.score(resume, job, config)
    assert scores.skills.score == 50.0  # 1/2 required skills matched = 50%
    deterministic_50 = (scores.skills.score / 100.0) * 50.0
    assert deterministic_50 == 25.0


def test_languages_ignored_when_jd_has_no_language_requirement() -> None:
    """Requirement test: Ignore languages unless JD explicitly requires them."""
    from app.services.scoring.weight_calculation_service import WeightCalculationService

    job = SimpleNamespace(skills=["Python"], experience_requirements=[], degree_requirements=[], keywords=[])
    config_no_lang = SimpleNamespace(mandatory_skills=[], required_languages=[], min_experience_years=0, required_degree=None, required_certifications=[])
    
    categories = WeightCalculationService.applicable_categories(job, config_no_lang)
    assert "languages" not in categories


def test_final_score_is_exact_sum_of_skill_and_ai_relevance_without_fallback_40_50() -> None:
    """Requirement test: Final score must be exactly skill_score + ai_relevance_score with no default 40/50 fallback."""
    from app.services.scoring.weight_calculation_service import WeightCalculationService
    from app.schemas.scoring import ComponentScoreDetail, ComponentScores

    # 1. Skill score 25/50 + AI relevance 35/50 = 60/100
    comp_score_50 = ComponentScoringService()._match(["A"], ["A", "B"], "skills")  # 50% = 25/50
    evidence_detail = ComponentScoreDetail(score=70.0, matched_items=[], missing_items=[], explanation="70% = 35/50")
    components = ComponentScores(
        skills=comp_score_50, experience=evidence_detail, projects=evidence_detail,
        education=evidence_detail, certifications=evidence_detail, languages=evidence_detail,
    )

    final = WeightCalculationService.final_score(0, 0, 0, components=components)
    assert final == 60.0  # 25 + 35

    # 2. Assert no static 40/50 or default fallback scores are injected
    zero_detail = ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation="0%")
    zero_components = ComponentScores(
        skills=zero_detail, experience=zero_detail, projects=zero_detail,
        education=zero_detail, certifications=zero_detail, languages=zero_detail,
    )
    zero_final = WeightCalculationService.final_score(0, 0, 0, components=zero_components)
    assert zero_final == 0.0


def test_ai_relevance_with_all_some_and_no_applicable_categories() -> None:
    """Test AI Relevance calculation with all categories, some N/A, and all N/A categories."""
    from app.services.scoring.weight_calculation_service import WeightCalculationService
    from app.schemas.scoring import ComponentScoreDetail, ComponentScores

    skill_detail = ComponentScoreDetail(score=100.0, matched_items=["Python"], missing_items=[], explanation="Matched 1 skill.")  # 50/50
    exp_detail = ComponentScoreDetail(score=80.0, matched_items=["24 months"], missing_items=[], explanation="24 months matched")
    proj_detail = ComponentScoreDetail(score=60.0, matched_items=["Docker"], missing_items=[], explanation="Docker matched")
    na_detail = ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="No specific requirement configured (N/A).")

    components = ComponentScores(
        skills=skill_detail,
        experience=exp_detail,
        projects=proj_detail,
        education=na_detail,
        certifications=na_detail,
        languages=na_detail,
    )

    # 1. All evidence categories required: experience=80, projects=60, education=100, certs=100, langs=100 -> avg = 88.0 -> evidence marks = 44.0 -> final = 50 + 44 = 94.0
    all_categories = {"skills", "experience", "projects", "education", "certifications", "languages"}
    score_all = WeightCalculationService.final_score(0, 0, 0, components=components, applicable_categories=all_categories)
    assert score_all == 94.0

    # 2. Some categories N/A: only experience and projects required. avg = (80 + 60) / 2 = 70.0 -> evidence marks = 35.0 -> final = 50 + 35 = 85.0
    some_categories = {"skills", "experience", "projects"}
    score_some = WeightCalculationService.final_score(0, 0, 0, components=components, applicable_categories=some_categories)
    assert score_some == 85.0

    # 3. All evidence categories N/A: only skills required. applicable_evidence = empty -> evidence marks = 0.0 -> final = 50.0 + 0.0 = 50.0
    no_evidence_categories = {"skills"}
    score_none = WeightCalculationService.final_score(0, 0, 0, components=components, applicable_categories=no_evidence_categories)
    assert score_none == 50.0


def test_global_50_50_reconciliation_and_projects_inclusion() -> None:
    """Verify that projects genuinely contribute, 0 projects score 0, and 50+50 reconciles strictly to 100."""
    from app.services.scoring.weight_calculation_service import WeightCalculationService
    from app.services.scoring.component_scoring_service import ComponentScoringService
    from types import SimpleNamespace

    service = ComponentScoringService()

    # JD with required skills and keywords
    job = SimpleNamespace(
        skills=["Python", "FastAPI", "React"],
        required_skills=["Python", "FastAPI", "React"],
        experience_requirements=[{"minimum_months": 24}],
        degree_requirements=["Bachelor of Technology"],
        keywords=["Docker"],
    )
    config = SimpleNamespace(
        mandatory_skills=[],
        min_experience_years=2,
        required_degree="Bachelor of Technology",
        required_certifications=[],
        required_languages=[],
    )

    # Candidate A: Has projects matching Docker and FastAPI
    cand_a_resume = SimpleNamespace(
        skills=["Python", "FastAPI"],
        experience=[{"duration_months": 24}],
        education=[{"degree": "Bachelor of Technology"}],
        certifications=[],
        languages=[],
    )
    cand_a_projects = [
        {"name": "Microservices", "technologies": ["Docker", "FastAPI"], "description": "Built cloud backend"}
    ]
    scores_a = service.score(cand_a_resume, job, config, cand_a_projects)
    assert scores_a.skills.score == pytest.approx(66.67, 0.01) # 2 of 3 skills
    assert scores_a.projects.score == 100.0 # matched Docker
    assert scores_a.experience.score == 100.0
    assert scores_a.education.score == 100.0

    app_cats = WeightCalculationService.applicable_categories(job, config)
    final_a = WeightCalculationService.final_score(0, 0, 0, components=scores_a, applicable_categories=app_cats)
    
    skill_50_a = (scores_a.skills.score / 100.0) * 50.0
    evidence_50_a = (sum([scores_a.experience.score, scores_a.projects.score, scores_a.education.score]) / 3.0 / 100.0) * 50.0
    assert final_a == pytest.approx(round(skill_50_a + evidence_50_a, 2), 0.01)

    # Candidate B: Has 0 projects -> projects score must be 0 (no artificial 100)
    cand_b_resume = SimpleNamespace(
        skills=["Python"],
        experience=[{"duration_months": 12}],
        education=[{"degree": "High School"}], # below required B.Tech (rank 1 vs 3)
        certifications=[],
        languages=[],
    )
    scores_b = service.score(cand_b_resume, job, config, [])
    assert scores_b.projects.score == 0.0
    assert "No candidate projects found." in scores_b.projects.explanation
    assert scores_b.education.score == 50.0 # non-qualifying degree (rank 1 vs rank 3)
    assert scores_b.experience.score == 50.0 # 12 of 24 months

    final_b = WeightCalculationService.final_score(0, 0, 0, components=scores_b, applicable_categories=app_cats)
    skill_50_b = (scores_b.skills.score / 100.0) * 50.0
    evidence_50_b = (sum([scores_b.experience.score, scores_b.projects.score, scores_b.education.score]) / 3.0 / 100.0) * 50.0
    assert final_b == pytest.approx(round(skill_50_b + evidence_50_b, 2), 0.01)





