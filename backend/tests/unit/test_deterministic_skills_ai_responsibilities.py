import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.schemas.matching import (
    Evidence,
    MatchMethod,
    MatchStatus,
    MatchVerdict,
    Requirement,
    RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher,
    GroqMatchEvaluator,
    GroqTokenBudgetGate,
    HybridMatchingService,
    ProviderCircuitBreaker,
    SmartMatchEvaluator,
)
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.weight_calculation_service import WeightCalculationService


@pytest.fixture(autouse=True)
def reset_state():
    ProviderCircuitBreaker.reset_breaker()
    GroqTokenBudgetGate.reset_gate()
    GroqMatchEvaluator._cache.clear()


def make_mock_settings():
    return MagicMock(
        ENABLE_CEREBRAS_FALLBACK=False,
        GROQ_API_KEY="mock_groq_key",
        GROQ_BASE_URL="https://api.groq.com/openai/v1",
        GROQ_MODEL="openai/gpt-oss-20b",
        GROQ_TIMEOUT_SECONDS=5.0,
        GROQ_TPM_LIMIT=8000,
        GROQ_TPM_SAFETY_MARGIN=0.125,
        GROQ_MAX_RETRIES=1,
        GROQ_BUDGET_WAIT_TIMEOUT_SECONDS=5.0,
        CEREBRAS_API_KEY=None,
        PROVIDER_CIRCUIT_BREAKER_COOLDOWN_SECONDS=1.0,
        PROVIDER_CIRCUIT_BREAKER_MAX_FAILURES=1,
        HYBRID_MATCHING_KEYWORD_OVERLAP_THRESHOLD=0.15,
        HYBRID_MATCHING_MAX_EVIDENCE_PER_REQUIREMENT=5,
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_CACHE_SIZE=100,
    )


# 1. Required skills do not trigger Groq calls
@pytest.mark.asyncio
async def test_1_required_skills_do_not_trigger_groq_calls():
    mock_settings = make_mock_settings()
    hybrid = HybridMatchingService(settings=mock_settings)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        # Job with only required skills
        fake_job = SimpleNamespace(
            required_skills=["Python", "FastAPI", "SQL"],
            skills=["Python", "FastAPI", "SQL"],
            responsibilities=[],
        )
        fake_resume = SimpleNamespace(
            skills=["Python", "FastAPI"],
            experience=[],
            projects=[],
            education=[],
            certifications=[],
        )
        fake_extracted = SimpleNamespace(
            skills=["Python", "FastAPI"],
            experience=[],
            projects=[],
            education=[],
            certifications=[],
            languages=[],
            summary="Python developer with FastAPI experience.",
        )

        _, verdicts = await hybrid.match(fake_job, fake_resume, fake_extracted)

        # Groq client was NEVER called for skills
        assert mock_client.post.call_count == 0
        assert len(verdicts) >= 3


# 2. Canonical skill matches work correctly
@pytest.mark.asyncio
async def test_2_canonical_skill_matches_work_correctly():
    mock_settings = make_mock_settings()
    hybrid = HybridMatchingService(settings=mock_settings)

    fake_job = SimpleNamespace(
        required_skills=["PostgreSQL", "React.js"],
        skills=["PostgreSQL", "React.js"],
        responsibilities=[],
    )
    # Resume contains aliases "postgres" and "react"
    fake_resume = SimpleNamespace(
        skills=["postgres", "react"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
    )
    fake_extracted = SimpleNamespace(
        skills=["postgres", "react"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
        summary="",
    )

    _, verdicts = await hybrid.match(fake_job, fake_resume, fake_extracted)
    v_map = {v.requirement_text: v for v in verdicts}

    assert v_map["PostgreSQL"].status == MatchStatus.MATCHED
    assert v_map["PostgreSQL"].coverage == 1.0
    assert v_map["React.js"].status == MatchStatus.MATCHED
    assert v_map["React.js"].coverage == 1.0


# 3. Partial skill matches retain their existing points
@pytest.mark.asyncio
async def test_3_partial_skill_matches_retain_points():
    mock_settings = make_mock_settings()
    hybrid = HybridMatchingService(settings=mock_settings)

    # Conjunction compound skill: "Python and Kubernetes"
    fake_job = SimpleNamespace(
        required_skills=["Python and Kubernetes"],
        skills=["Python and Kubernetes"],
        responsibilities=[],
    )
    # Resume only has Python
    fake_resume = SimpleNamespace(
        skills=["Python"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
    )
    fake_extracted = SimpleNamespace(
        skills=["Python"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
        summary="",
    )

    _, verdicts = await hybrid.match(fake_job, fake_resume, fake_extracted)
    v = verdicts[0]

    assert v.status == MatchStatus.PARTIALLY_MATCHED
    assert 0.0 < v.coverage < 1.0
    assert v.coverage_score == v.coverage


# 4. Truly unmatched skills receive 0 points
@pytest.mark.asyncio
async def test_4_truly_unmatched_skills_receive_zero_points():
    mock_settings = make_mock_settings()
    hybrid = HybridMatchingService(settings=mock_settings)

    fake_job = SimpleNamespace(
        required_skills=["Rust programming"],
        skills=["Rust programming"],
        responsibilities=[],
    )
    fake_resume = SimpleNamespace(
        skills=["Java", "Spring"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
    )
    fake_extracted = SimpleNamespace(
        skills=["Java", "Spring"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
        summary="Java backend developer",
    )

    _, verdicts = await hybrid.match(fake_job, fake_resume, fake_extracted)
    v = verdicts[0]

    assert v.status == MatchStatus.NO_MATCH
    assert v.coverage == 0.0
    assert v.coverage_score == 0.0
    assert len(v.evidence_ids) == 0


# 5. Responsibilities still use Groq AI
@pytest.mark.asyncio
async def test_5_responsibilities_still_use_groq_ai():
    mock_settings = make_mock_settings()
    hybrid = HybridMatchingService(settings=mock_settings)

    def mock_response(*args, **kwargs):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "verdicts": [
                                {
                                    "requirement_id": "responsibility:1",
                                    "status": "MATCHED",
                                    "confidence": 0.95,
                                    "coverage_score": 0.9,
                                    "reasoning": "Built scalable cloud architectures",
                                    "evidence_ids": ["experience:1"],
                                }
                            ]
                        })
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 300, "completion_tokens": 100, "total_tokens": 400},
        }
        resp.headers = {"x-ratelimit-remaining-tokens": "7000"}
        return resp

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_response

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        fake_job = SimpleNamespace(
            required_skills=["Python"],
            skills=["Python"],
            responsibilities=["Design and deploy scalable cloud microservices"],
        )
        fake_resume = SimpleNamespace(
            skills=["Python"],
            experience=[{"title": "Backend Engineer", "company": "Acme", "description": "Designed cloud microservices"}],
            projects=[],
            education=[],
            certifications=[],
        )
        fake_extracted = SimpleNamespace(
            skills=["Python"],
            experience=[{"title": "Backend Engineer", "company": "Acme", "description": "Designed cloud microservices"}],
            projects=[],
            education=[],
            certifications=[],
            languages=[],
            summary="",
        )

        _, verdicts = await hybrid.match(fake_job, fake_resume, fake_extracted)

        # Groq client was called EXACTLY once for the responsibility (NOT for Python)
        assert mock_client.post.call_count == 1
        resp_v = [v for v in verdicts if str(v.requirement_id).startswith("responsibility:")][0]
        assert resp_v.status == MatchStatus.MATCHED
        assert resp_v.reasoning == "Built scalable cloud architectures"


# 6. AI responsibility verdicts contain valid evidence/reasoning
@pytest.mark.asyncio
async def test_6_ai_responsibility_verdicts_contain_valid_evidence():
    mock_settings = make_mock_settings()
    hybrid = HybridMatchingService(settings=mock_settings)

    def mock_response(*args, **kwargs):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "verdicts": [
                                {
                                    "requirement_id": "responsibility:1",
                                    "status": "PARTIALLY_MATCHED",
                                    "confidence": 0.8,
                                    "coverage_score": 0.5,
                                    "reasoning": "Candidate assisted in ETL development",
                                    "evidence_ids": ["experience:1"],
                                }
                            ]
                        })
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 300, "completion_tokens": 100, "total_tokens": 400},
        }
        resp.headers = {"x-ratelimit-remaining-tokens": "7000"}
        return resp

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_response

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        fake_job = SimpleNamespace(
            required_skills=[],
            skills=[],
            responsibilities=["Lead automated data pipeline engineering"],
        )
        fake_resume = SimpleNamespace(
            skills=[],
            experience=[{"title": "Junior Data Engineer", "description": "Assisted in pipeline development"}],
            projects=[],
            education=[],
            certifications=[],
        )
        fake_extracted = SimpleNamespace(
            skills=[],
            experience=[{"title": "Junior Data Engineer", "description": "Assisted in pipeline development"}],
            projects=[],
            education=[],
            certifications=[],
            languages=[],
            summary="",
        )

        _, verdicts = await hybrid.match(fake_job, fake_resume, fake_extracted)
        resp_v = verdicts[0]
        assert resp_v.status == MatchStatus.PARTIALLY_MATCHED
        assert "experience:1" in resp_v.evidence_ids
        assert resp_v.reasoning == "Candidate assisted in ETL development"


# 7. Multiple resumes scored concurrently without skill evaluations consuming Groq budget
@pytest.mark.asyncio
async def test_7_multiple_resumes_concurrent_scoring_no_skill_groq_consumption():
    mock_settings = make_mock_settings()
    hybrid = HybridMatchingService(settings=mock_settings)

    groq_call_log = []

    def mock_response(*args, **kwargs):
        content = kwargs["json"]["messages"][-1]["content"]
        groq_call_log.append(content)
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "verdicts": [
                                {
                                    "requirement_id": "responsibility:1",
                                    "status": "MATCHED",
                                    "confidence": 0.9,
                                    "coverage_score": 0.8,
                                    "reasoning": "Demonstrated",
                                    "evidence_ids": ["experience:1"],
                                }
                            ]
                        })
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 200, "completion_tokens": 50, "total_tokens": 250},
        }
        resp.headers = {"x-ratelimit-remaining-tokens": "7500"}
        return resp

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_response

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        fake_job = SimpleNamespace(
            required_skills=["Python", "Go", "Docker", "Kubernetes", "AWS"],
            skills=["Python", "Go", "Docker", "Kubernetes", "AWS"],
            responsibilities=["Develop distributed backend services"],
        )

        GroqMatchEvaluator._cache.clear()

        async def run_one(name, skill_list):
            res = SimpleNamespace(
                id=name,
                skills=skill_list,
                experience=[{"title": "Backend Dev", "description": f"Built distributed services at {name}"}],
                projects=[],
                education=[],
                certifications=[],
            )
            ext = SimpleNamespace(
                skills=skill_list,
                experience=[{"title": "Backend Dev", "description": f"Built distributed services at {name}"}],
                projects=[],
                education=[],
                certifications=[],
                languages=[],
                summary="",
            )
            return await hybrid.match(fake_job, res, ext)

        results = await asyncio.gather(
            run_one("cand_1", ["Python", "Docker"]),
            run_one("cand_2", ["Go", "Kubernetes"]),
            run_one("cand_3", ["AWS"]),
        )

        assert len(results) == 3
        # Exactly 3 Groq calls — one per resume for responsibility ONLY!
        assert len(groq_call_log) == 3
        # None of the Groq calls contain the 5 skill requirements
        for payload in groq_call_log:
            assert "Develop distributed backend services" in payload
            assert "Docker" not in payload
            assert "Kubernetes" not in payload


# 8. One resume's failure cannot contaminate another resume
@pytest.mark.asyncio
async def test_8_one_resume_failure_does_not_contaminate_another():
    mock_settings = make_mock_settings()
    hybrid = HybridMatchingService(settings=mock_settings)

    def mock_response(*args, **kwargs):
        content = kwargs["json"]["messages"][-1]["content"]
        if "failing_candidate" in content:
            raise httpx.ConnectError("Network dropped for failing candidate")
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "verdicts": [
                                {
                                    "requirement_id": "responsibility:1",
                                    "status": "MATCHED",
                                    "confidence": 0.9,
                                    "coverage_score": 0.8,
                                    "reasoning": "Demonstrated",
                                    "evidence_ids": ["experience:1"],
                                }
                            ]
                        })
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 200, "completion_tokens": 50, "total_tokens": 250},
        }
        resp.headers = {"x-ratelimit-remaining-tokens": "7500"}
        return resp

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_response

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        fake_job = SimpleNamespace(
            required_skills=["Python"],
            skills=["Python"],
            responsibilities=["Maintain core API infrastructure"],
        )

        res_fail = SimpleNamespace(
            id="failing_candidate",
            skills=["Python"],
            experience=[{"title": "Dev", "description": "failing_candidate work on API"}],
            projects=[],
            education=[],
            certifications=[],
        )
        ext_fail = SimpleNamespace(
            skills=["Python"],
            experience=[{"title": "Dev", "description": "failing_candidate work on API"}],
            projects=[],
            education=[],
            certifications=[],
            languages=[],
            summary="",
        )

        res_succ = SimpleNamespace(
            id="success_candidate",
            skills=["Python"],
            experience=[{"title": "Dev", "description": "success_candidate work on API"}],
            projects=[],
            education=[],
            certifications=[],
        )
        ext_succ = SimpleNamespace(
            skills=["Python"],
            experience=[{"title": "Dev", "description": "success_candidate work on API"}],
            projects=[],
            education=[],
            certifications=[],
            languages=[],
            summary="",
        )

        res1, res2 = await asyncio.gather(
            hybrid.match(fake_job, res_fail, ext_fail),
            hybrid.match(fake_job, res_succ, ext_succ),
        )

        v1 = res1[1]
        v2 = res2[1]

        # In res1: Python succeeded deterministically! Only the responsibility failed!
        p_v1 = [v for v in v1 if v.requirement_text == "Python"][0]
        assert p_v1.status == MatchStatus.MATCHED
        resp_v1 = [v for v in v1 if str(v.requirement_id).startswith("responsibility:")][0]
        assert resp_v1.status == MatchStatus.EVALUATION_FAILED

        # In res2: Both Python and responsibility succeeded completely!
        p_v2 = [v for v in v2 if v.requirement_text == "Python"][0]
        assert p_v2.status == MatchStatus.MATCHED
        resp_v2 = [v for v in v2 if str(v.requirement_id).startswith("responsibility:")][0]
        assert resp_v2.status == MatchStatus.MATCHED


# 9. 50/50 scoring formula remains skillsPts + respPts
def test_9_scoring_formula_50_50_preservation():
    scoring_service = ComponentScoringService()

    fake_job = SimpleNamespace(
        required_skills=["Python", "FastAPI"],
        skills=["Python", "FastAPI"],
        responsibilities=["Build REST APIs", "Database administration"],
    )
    fake_resume = SimpleNamespace(
        skills=["Python", "FastAPI"],
        experience=[{"title": "Engineer", "description": "Built REST APIs"}],
        projects=[],
        education=[],
        certifications=[],
    )

    verdicts = [
        # Skills: 100% matched
        MatchVerdict(
            requirement_id="skill:1", requirement_text="Python", kind=RequirementKind.SKILL,
            status=MatchStatus.MATCHED, confidence=1.0, coverage=1.0, coverage_score=1.0,
            importance="critical", method=MatchMethod.EXACT,
        ),
        MatchVerdict(
            requirement_id="skill:2", requirement_text="FastAPI", kind=RequirementKind.SKILL,
            status=MatchStatus.MATCHED, confidence=1.0, coverage=1.0, coverage_score=1.0,
            importance="critical", method=MatchMethod.EXACT,
        ),
        # Responsibilities: 1 of 2 matched (50%)
        MatchVerdict(
            requirement_id="responsibility:1", requirement_text="Build REST APIs", kind=RequirementKind.RESPONSIBILITY,
            status=MatchStatus.MATCHED, confidence=0.9, coverage=1.0, coverage_score=1.0,
            importance="important", method=MatchMethod.LLM_CONFIRMED,
        ),
        MatchVerdict(
            requirement_id="responsibility:2", requirement_text="Database administration", kind=RequirementKind.RESPONSIBILITY,
            status=MatchStatus.NO_MATCH, confidence=0.9, coverage=0.0, coverage_score=0.0,
            importance="important", method=MatchMethod.LLM_REJECTED,
        ),
    ]

    components = scoring_service.score(
        resume=fake_resume,
        job=fake_job,
        config=None,
        match_verdicts=verdicts,
    )

    # Skills score should be 100.0%
    assert components.skills.score == 100.0
    # Responsibilities score should be 50.0%
    assert components.responsibilities.score == 50.0

    # 50/50 weighted total
    effective_weights = {"required_skills": 50.0, "responsibilities": 50.0}
    weighted_scores, raw_total, weighted_total, _ = WeightCalculationService.calculate(
        components, config=SimpleNamespace(weights=effective_weights)
    )

    # Skills contribution: 100 * 0.5 = 50.0 points
    assert weighted_scores.skills == 50.0
    # Responsibilities contribution: 50 * 0.5 = 25.0 points
    assert weighted_scores.responsibilities == 25.0
    # Total: 50.0 + 25.0 = 75.0 points
    assert weighted_total == 75.0
