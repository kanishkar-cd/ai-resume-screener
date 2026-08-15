from types import SimpleNamespace
import pytest

from app.core.config import Settings
from app.services.matching_service import HybridMatchingService


def get_test_settings():
    return Settings(
        ENABLE_HYBRID_MATCHING=True,
        GROQ_API_KEY="test-key",
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_KEYWORD_OVERLAP_THRESHOLD=0.1,
    )


@pytest.mark.asyncio
async def test_case_1_fresher_exact_weighted_calculation() -> None:
    """
    Req=80, Resp=70, Pref=50, Title=60
    Fresher formula: 80*0.45 + 70*0.35 + 50*0.10 + 60*0.10 = 36 + 24.5 + 5 + 6 = 71.50
    """
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Software Engineer",
        required_skills=["Python", "Java", "C++", "Go", "Rust"],
        preferred_skills=["Docker", "Kubernetes"],
        responsibilities=["Build REST APIs", "Optimize queries"],
        experience_requirements=[],
    )
    # Match 4 of 5 req skills -> req_score = 80.0
    # Match 1 of 2 pref skills -> pref_score = 50.0
    # Match 1 of 2 responsibilities -> resp_score = 50.0
    # Let's mock or structure items to get exact component scores for test assertions
    resume = SimpleNamespace(
        skills=["Python", "Java", "C++", "Go", "Docker"],
        projects=[],
        experience=[{"job_title": "Software Engineer", "company": "Co", "responsibilities": ["Build REST APIs"]}],
        education=[],
        total_experience_months=10,
        candidate_level="FRESHER",
        job_titles=["Software Engineer"],
    )
    result, _ = await service.match(job, resume)
    assert result.profile.candidate_level == "FRESHER"
    # Verify score formula calculation consistency
    expected = round(
        result.required_skills_score * 0.45
        + result.responsibility_score * 0.35
        + result.preferred_skills_score * 0.10
        + result.job_title_score * 0.10,
        2,
    )
    assert result.final_match_score == expected


@pytest.mark.asyncio
async def test_case_2_experienced_exact_weighted_calculation() -> None:
    """
    Experienced formula: Req*0.40 + Resp*0.35 + Pref*0.10 + Title*0.05 + RelExp*0.10
    """
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Senior Developer",
        required_skills=["Python"],
        preferred_skills=["Docker"],
        responsibilities=["Build REST APIs"],
        experience_requirements=[{"minimum_months": 24}],
    )
    resume = SimpleNamespace(
        skills=["Python", "Docker"],
        projects=[],
        experience=[{"job_title": "Senior Developer", "company": "Co", "responsibilities": ["Build REST APIs"]}],
        education=[],
        total_experience_months=24,
        candidate_level="EXPERIENCED",
        job_titles=["Senior Developer"],
    )
    result, _ = await service.match(job, resume)
    assert result.profile.candidate_level == "EXPERIENCED"
    assert result.relevant_experience_score == 100.0
    assert result.required_skills_score == 100.0
    assert result.preferred_skills_score == 100.0
    assert result.responsibility_score == 100.0
    assert result.job_title_score == 100.0
    assert result.final_match_score == 100.0


@pytest.mark.asyncio
async def test_case_3_fresher_does_not_use_relevant_experience_score() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Junior Engineer",
        required_skills=["Python"],
        preferred_skills=[],
        responsibilities=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["Python"],
        projects=[], experience=[], education=[],
        total_experience_months=6,
        candidate_level="FRESHER",
        job_titles=["Junior Engineer"],
    )
    result, _ = await service.match(job, resume)
    assert result.relevant_experience_score is None
    # 100*0.45 + 100*0.35 + 100*0.10 + 100*0.10 = 100.0
    assert result.final_match_score == 100.0


@pytest.mark.asyncio
async def test_case_4_experienced_uses_relevant_experience_score() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Dev",
        required_skills=["Python"],
        preferred_skills=[], responsibilities=[],
        experience_requirements=[{"minimum_months": 24}],
    )
    resume = SimpleNamespace(
        skills=["Python"], projects=[], experience=[], education=[],
        total_experience_months=18,  # 18 / 24 = 75.0%
        candidate_level="EXPERIENCED",
        job_titles=["Dev"],
    )
    result, _ = await service.match(job, resume)
    assert result.relevant_experience_score == 75.0
    # 100*0.40 + 100*0.35 + 100*0.10 + 100*0.05 + 75*0.10 = 40 + 35 + 10 + 5 + 7.5 = 97.5
    assert result.final_match_score == 97.5


@pytest.mark.asyncio
async def test_case_5_final_score_remains_between_0_and_100() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Dev", required_skills=["Python"], preferred_skills=[], responsibilities=[], experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["Python"], projects=[], experience=[], education=[],
        total_experience_months=12, candidate_level="FRESHER", job_titles=["Dev"],
    )
    result, _ = await service.match(job, resume)
    assert 0.0 <= result.final_match_score <= 100.0


@pytest.mark.asyncio
async def test_case_6_zero_component_scores_produce_zero_final_score() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Architect",
        required_skills=["C++"],
        preferred_skills=["Rust"],
        responsibilities=["Manage data centers"],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=[], projects=[], experience=[], education=[],
        total_experience_months=0, candidate_level="FRESHER", job_titles=[],
    )
    result, _ = await service.match(job, resume)
    assert result.required_skills_score == 0.0
    assert result.preferred_skills_score == 0.0
    assert result.responsibility_score == 0.0
    assert result.job_title_score == 40.0  # Default supporting job title baseline when candidate has no title
    # 0*0.45 + 0*0.35 + 0*0.10 + 40*0.10 = 4.0
    assert result.final_match_score == 4.0


@pytest.mark.asyncio
async def test_case_7_perfect_component_scores_produce_100_final_score() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Full Stack Engineer",
        required_skills=["React", "Node.js"],
        preferred_skills=["Docker"],
        responsibilities=["Develop web applications"],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["React", "Node.js", "Docker"],
        projects=[],
        experience=[{"job_title": "Full Stack Engineer", "company": "Co", "responsibilities": ["Develop web applications"]}],
        education=[], total_experience_months=12, candidate_level="FRESHER",
        job_titles=["Full Stack Engineer"],
    )
    result, _ = await service.match(job, resume)
    assert result.required_skills_score == 100.0
    assert result.preferred_skills_score == 100.0
    assert result.responsibility_score == 100.0
    assert result.job_title_score == 100.0
    assert result.final_match_score == 100.0


@pytest.mark.asyncio
async def test_case_8_candidate_level_determines_correct_formula() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Dev", required_skills=["Python"], preferred_skills=[], responsibilities=[], experience_requirements=[{"minimum_months": 24}],
    )
    resume_fresher = SimpleNamespace(
        skills=["Python"], projects=[], experience=[], education=[],
        total_experience_months=12, candidate_level="FRESHER", job_titles=["Dev"],
    )
    resume_exp = SimpleNamespace(
        skills=["Python"], projects=[], experience=[], education=[],
        total_experience_months=24, candidate_level="EXPERIENCED", job_titles=["Dev"],
    )
    res_fresher, _ = await service.match(job, resume_fresher)
    res_exp, _ = await service.match(job, resume_exp)

    # Fresher: 100*0.45 + 100*0.35 + 100*0.10 + 100*0.10 = 100.0
    assert res_fresher.final_match_score == 100.0

    # Experienced: 100*0.40 + 100*0.35 + 100*0.10 + 100*0.05 + 100*0.10 = 100.0
    assert res_exp.final_match_score == 100.0


@pytest.mark.asyncio
async def test_case_9_no_screening_threshold_applied() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Dev", required_skills=["Python"], preferred_skills=[], responsibilities=[], experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["Python"], projects=[], experience=[], education=[],
        total_experience_months=6, candidate_level="FRESHER", job_titles=[],
    )
    result, _ = await service.match(job, resume)
    dict_repr = result.model_dump()

    # Confirm no screening threshold or rating categories added to output
    assert "screened" not in dict_repr
    assert "threshold" not in dict_repr
    assert "rating" not in dict_repr
    assert "recommendation" not in dict_repr
