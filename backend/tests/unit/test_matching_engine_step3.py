from types import SimpleNamespace
import pytest

from app.core.config import Settings
from app.schemas.matching import MatchMethod, MatchStatus, MatchVerdict, Requirement
from app.services.matching_service import HybridMatchingService


def get_test_settings():
    return Settings(
        ENABLE_HYBRID_MATCHING=True,
        GROQ_API_KEY="test-key",
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_KEYWORD_OVERLAP_THRESHOLD=0.1,
    )


@pytest.mark.asyncio
async def test_case_1_required_skill_exact_and_normalized_match_no_llm() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Software Engineer",
        required_skills=["Python", "PostgreSQL"],
        preferred_skills=[],
        responsibilities=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        candidate_name="Jane Doe", email="jane@example.com", phone="+919876543210",
        skills=["python", "postgres"],
        projects=[], experience=[], education=[],
        total_experience_months=24, candidate_level="EXPERIENCED",
        job_titles=["Software Engineer"],
    )
    result, verdicts = await service.match(job, resume)
    assert result.required_skills_score == 100.0
    assert result.matched_required_skills == ["Python", "PostgreSQL"]
    assert result.missing_required_skills == []


@pytest.mark.asyncio
async def test_case_2_required_skill_found_through_project_technology() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Frontend Developer",
        required_skills=["React"],
        preferred_skills=[], responsibilities=[], experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["JavaScript"],
        projects=[{"name": "Web App", "technologies": ["reactjs"], "description": "Built UI"}],
        experience=[], education=[],
        total_experience_months=6, candidate_level="FRESHER",
        job_titles=[],
    )
    result, _ = await service.match(job, resume)
    assert "React" in result.matched_required_skills
    assert result.required_skills_score == 100.0


@pytest.mark.asyncio
async def test_case_3_duplicate_skills_in_multiple_sections_counted_once() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Python Dev",
        required_skills=["Python"],
        preferred_skills=[], responsibilities=[], experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["Python"],
        projects=[{"name": "AI Tool", "technologies": ["Python"], "description": "Used Python"}],
        experience=[{"job_title": "Dev", "company": "Co", "responsibilities": ["Wrote Python code."]}],
        education=[], total_experience_months=10, candidate_level="FRESHER",
        job_titles=[],
    )
    result, _ = await service.match(job, resume)
    assert result.matched_required_skills.count("Python") == 1
    assert result.required_skills_score == 100.0


@pytest.mark.asyncio
async def test_case_4_preferred_skill_missing_does_not_reject() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Backend Dev",
        required_skills=["Python"],
        preferred_skills=["GraphQL"],
        responsibilities=[], experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["Python"], projects=[], experience=[], education=[],
        total_experience_months=12, candidate_level="FRESHER",
        job_titles=[],
    )
    result, _ = await service.match(job, resume)
    assert result.required_skills_score == 100.0
    assert result.preferred_skills_score == 0.0
    assert result.missing_preferred_skills == ["GraphQL"]


@pytest.mark.asyncio
async def test_case_5_different_job_title_with_relevant_skills_matches() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Senior MERN Stack Developer",
        required_skills=["React", "Node.js"],
        preferred_skills=[], responsibilities=[], experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["React", "Node.js"], projects=[], experience=[], education=[],
        total_experience_months=36, candidate_level="EXPERIENCED",
        job_titles=["Full Stack Developer"],
    )
    result, _ = await service.match(job, resume)
    assert result.required_skills_score == 100.0
    assert result.job_title_score >= 70.0


@pytest.mark.asyncio
async def test_case_6_fresher_candidate_0_to_12_months() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Junior Dev", required_skills=["Python"], preferred_skills=[],
        responsibilities=[], experience_requirements=[{"minimum_months": 0}],
    )
    resume = SimpleNamespace(
        skills=["Python"], projects=[], experience=[], education=[],
        total_experience_months=6, candidate_level="FRESHER",
        job_titles=[],
    )
    result, _ = await service.match(job, resume)
    assert result.profile.candidate_level == "FRESHER"
    assert result.relevant_experience_score is None


@pytest.mark.asyncio
async def test_case_7_experienced_candidate_greater_than_12_months() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Senior Dev", required_skills=["Python"], preferred_skills=[],
        responsibilities=[], experience_requirements=[{"minimum_months": 24}],
    )
    resume = SimpleNamespace(
        skills=["Python"], projects=[], experience=[], education=[],
        total_experience_months=36, candidate_level="EXPERIENCED",
        job_titles=[],
    )
    result, _ = await service.match(job, resume)
    assert result.profile.candidate_level == "EXPERIENCED"
    assert result.relevant_experience_score == 100.0


@pytest.mark.asyncio
async def test_case_8_responsibility_keyword_match_no_llm() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Backend Engineer", required_skills=[], preferred_skills=[],
        responsibilities=["Build REST APIs"], experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=[], projects=[],
        experience=[{"job_title": "Backend Eng", "company": "Acme", "responsibilities": ["Build REST APIs in FastAPI"]}],
        education=[], total_experience_months=18, candidate_level="EXPERIENCED",
        job_titles=[],
    )
    result, _ = await service.match(job, resume)
    assert result.responsibility_score == 100.0
    assert result.responsibility_details[0].status == MatchStatus.MATCHED
    assert result.responsibility_details[0].method == MatchMethod.EXACT


@pytest.mark.asyncio
async def test_case_9_ambiguous_responsibility_calls_targeted_llm() -> None:
    class MockEvaluator:
        enabled = True
        async def evaluate(self, requirements, evidence, allowed_evidence=None):
            assert len(requirements) == 1
            assert requirements[0].text == "Architect cloud microservices"
            return [MatchVerdict(
                requirement_id=requirements[0].requirement_id,
                status=MatchStatus.MATCHED, confidence=0.9,
                evidence_ids=[e.evidence_id for e in evidence[:1]],
                reasoning="Targeted LLM confirmed cloud microservices experience.",
                method=MatchMethod.LLM_CONFIRMED,
            )]

    service = HybridMatchingService(settings=get_test_settings(), evaluator=MockEvaluator())
    job = SimpleNamespace(
        job_title="Cloud Architect", required_skills=[], preferred_skills=[],
        responsibilities=["Architect cloud microservices"], experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=[],
        projects=[{"name": "Distributed System", "description": "Designed resilient AWS serverless architecture.", "technologies": ["AWS"]}],
        experience=[], education=[], total_experience_months=48, candidate_level="EXPERIENCED",
        job_titles=[],
    )
    result, _ = await service.match(job, resume)
    assert result.responsibility_score == 100.0
    assert result.responsibility_details[0].method == MatchMethod.LLM_CONFIRMED


@pytest.mark.asyncio
async def test_case_10_full_jd_and_full_resume_never_sent_to_llm() -> None:
    captured_requirements = []
    captured_evidence = []

    class CapturingEvaluator:
        enabled = True
        async def evaluate(self, requirements, evidence, allowed_evidence=None):
            nonlocal captured_requirements, captured_evidence
            captured_requirements.extend(requirements)
            captured_evidence.extend(evidence)
            return [MatchVerdict(
                requirement_id=requirements[0].requirement_id,
                status=MatchStatus.MATCHED, confidence=0.95,
                evidence_ids=[evidence[0].evidence_id],
                reasoning="Targeted evaluation.",
                method=MatchMethod.LLM_CONFIRMED,
            )]

    service = HybridMatchingService(settings=get_test_settings(), evaluator=CapturingEvaluator())
    job = SimpleNamespace(
        job_title="Engineer", required_skills=["Python"], preferred_skills=[],
        responsibilities=["Optimize high-throughput database queries"], experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["Python"],
        projects=[{"name": "DB Tool", "description": "Tuned SQL indexes for high traffic.", "technologies": ["SQL"]}],
        experience=[], education=[], total_experience_months=12, candidate_level="FRESHER",
        job_titles=[],
    )
    await service.match(job, resume)
    # Confirm evaluator received ONLY the specific responsibility requirement, NOT full JD skills/degrees/etc.
    assert len(captured_requirements) == 1
    assert captured_requirements[0].text == "Optimize high-throughput database queries"


@pytest.mark.asyncio
async def test_case_11_education_does_not_affect_matching_score() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Developer", required_skills=["Python"], preferred_skills=[],
        responsibilities=[], experience_requirements=[],
    )
    resume_degree = SimpleNamespace(
        skills=["Python"], projects=[], experience=[],
        education=[{"degree": "Master of Science", "institution": "Top Univ"}],
        total_experience_months=24, candidate_level="EXPERIENCED", job_titles=[],
    )
    resume_no_degree = SimpleNamespace(
        skills=["Python"], projects=[], experience=[],
        education=[], total_experience_months=24, candidate_level="EXPERIENCED", job_titles=[],
    )
    res_degree, _ = await service.match(job, resume_degree)
    res_no_degree, _ = await service.match(job, resume_no_degree)
    assert res_degree.required_skills_score == res_no_degree.required_skills_score == 100.0
    assert res_degree.responsibility_score == res_no_degree.responsibility_score == 100.0


@pytest.mark.asyncio
async def test_case_12_matching_uses_only_normalized_jd_and_normalized_resume() -> None:
    service = HybridMatchingService(settings=get_test_settings())
    job = SimpleNamespace(
        job_title="Data Scientist", required_skills=["Python", "Pandas"], preferred_skills=[],
        responsibilities=[], experience_requirements=[],
    )
    resume = SimpleNamespace(
        candidate_name="Alex Smith", email="alex@example.com", phone="+1234567890",
        skills=["Python", "Pandas"], projects=[], experience=[], education=[],
        total_experience_months=30, candidate_level="EXPERIENCED", job_titles=["Data Scientist"],
    )
    result, _ = await service.match(job, resume)
    assert result.profile.candidate_name == "Alex Smith"
    assert result.profile.total_experience_months == 30
    assert result.required_skills_score == 100.0
