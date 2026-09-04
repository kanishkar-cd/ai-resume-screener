import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.config import Settings
from app.schemas.matching import (
    Evidence,
    MatchMethod,
    MatchStatus,
    MatchVerdict,
    Requirement,
    RequirementKind,
)
from app.services.matching_service import (
    CerebrasMatchEvaluator,
    GroqMatchEvaluator,
    GroqTokenBudgetGate,
    HybridMatchingService,
    ProviderCircuitBreaker,
    ResumeQueueScheduler,
    SmartMatchEvaluator,
)


def make_test_settings() -> Settings:
    return Settings(
        ENABLE_HYBRID_MATCHING=True,
        GROQ_API_KEY="gsk_test_resilience_key",
        GROQ_MODEL="openai/gpt-oss-20b",
        GROQ_TIMEOUT_SECONDS=5.0,
        GROQ_MAX_RETRIES=2,
        GROQ_TPM_LIMIT=8000,
        GROQ_TPM_SAFETY_MARGIN=0.10,
        CEREBRAS_API_KEY="csk_test_resilience_key",
        CEREBRAS_MODEL="gpt-oss-120b",
        CEREBRAS_TIMEOUT_SECONDS=5.0,
        CEREBRAS_MAX_RETRIES=2,
        CEREBRAS_TPM_LIMIT=60000,
        CEREBRAS_TPM_SAFETY_MARGIN=0.10,
        MAX_CONCURRENT_RESUMES=3,
        LLM_BATCH_THROTTLE_SECONDS=0.05,
        PROVIDER_CIRCUIT_BREAKER_COOLDOWN_SECONDS=0.10,
        PROVIDER_CIRCUIT_BREAKER_MAX_FAILURES=2,
    )


def make_valid_llm_json(req_id: str = "req_1", reasoning: str = "Candidate has direct match") -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "verdicts": [
                            {
                                "requirement_id": req_id,
                                "sub_claims": ["Python proficiency"],
                                "sub_claim_evidence": [
                                    {"claim": "Python proficiency", "evidence_level": "direct", "note": "5 years Python"}
                                ],
                                "coverage_score": 1.0,
                                "importance": "critical",
                                "evidence_ids": ["ev_1"],
                                "reasoning": reasoning,
                            }
                        ]
                    })
                }
            }
        ],
        "usage": {"prompt_tokens": 150, "completion_tokens": 50, "total_tokens": 200},
    }


@pytest.fixture(autouse=True)
def reset_globals():
    ProviderCircuitBreaker.reset_breaker()
    GroqTokenBudgetGate.reset_gate()
    GroqMatchEvaluator._cache.clear()
    CerebrasMatchEvaluator._cache.clear()


# 1. Test that 429 rate-limit triggers retry with backoff, then succeeds
@pytest.mark.asyncio
async def test_groq_429_triggers_retry_with_backoff_and_succeeds():
    settings = make_test_settings()
    evaluator = GroqMatchEvaluator(settings)

    resp_429 = MagicMock(spec=httpx.Response)
    resp_429.status_code = 429
    resp_429.headers = {"Retry-After": "0.01"}
    resp_429.text = '{"error": "rate_limit_exceeded"}'
    err_429 = httpx.HTTPStatusError("429 Rate Limit", request=MagicMock(), response=resp_429)
    resp_429.raise_for_status.side_effect = err_429

    resp_200 = MagicMock(spec=httpx.Response)
    resp_200.status_code = 200
    resp_200.json.return_value = make_valid_llm_json("req_1")
    resp_200.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = [resp_429, resp_200]

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        reqs = [Requirement(requirement_id="req_1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev_1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts = await evaluator.evaluate(reqs, evs, allow_retries=True)

        assert len(verdicts) == 1
        assert verdicts[0].status == MatchStatus.MATCHED
        assert verdicts[0].coverage_score == 1.0
        assert mock_client.post.call_count == 2
        mock_sleep.assert_called_once()


# 2. Test that 5xx server error triggers retry with backoff
@pytest.mark.asyncio
async def test_cerebras_500_triggers_retry_with_backoff():
    settings = make_test_settings()
    evaluator = CerebrasMatchEvaluator(settings)

    resp_500 = MagicMock(spec=httpx.Response)
    resp_500.status_code = 500
    resp_500.text = '{"error": "Internal Server Error"}'
    err_500 = httpx.HTTPStatusError("500 Server Error", request=MagicMock(), response=resp_500)
    resp_500.raise_for_status.side_effect = err_500

    resp_200 = MagicMock(spec=httpx.Response)
    resp_200.status_code = 200
    resp_200.json.return_value = make_valid_llm_json("req_1")
    resp_200.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = [resp_500, resp_200]

    with patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_client), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        reqs = [Requirement(requirement_id="req_1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev_1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts = await evaluator.evaluate(reqs, evs, allow_retries=True)

        assert len(verdicts) == 1
        assert verdicts[0].status == MatchStatus.MATCHED
        assert mock_client.post.call_count == 2
        mock_sleep.assert_called_once()


# 3. Test that 402 Payment Required does NOT retry, fails fast immediately, and trips breaker
@pytest.mark.asyncio
async def test_cerebras_402_fails_fast_without_retries_and_trips_breaker():
    settings = make_test_settings()
    evaluator = CerebrasMatchEvaluator(settings)

    resp_402 = MagicMock(spec=httpx.Response)
    resp_402.status_code = 402
    resp_402.text = '{"error": "Payment required to access this resource"}'
    err_402 = httpx.HTTPStatusError("402 Payment Required", request=MagicMock(), response=resp_402)
    resp_402.raise_for_status.side_effect = err_402

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = resp_402

    with patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_client), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        reqs = [Requirement(requirement_id="req_1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev_1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts = await evaluator.evaluate(reqs, evs, allow_retries=True)

        assert verdicts == []
        assert mock_client.post.call_count == 1  # Exactly 1 call: zero wasted retries on permanent error
        mock_sleep.assert_not_called()

        breaker = ProviderCircuitBreaker.get_breaker(settings)
        assert breaker.can_call("cerebras") is False  # Circuit tripped


# 4. Test that Circuit Breaker skips provider during cooldown window
@pytest.mark.asyncio
async def test_circuit_breaker_skips_dead_provider_during_cooldown():
    settings = make_test_settings()
    breaker = ProviderCircuitBreaker.get_breaker(settings)
    smart_eval = SmartMatchEvaluator(settings)

    # Trip the Cerebras circuit
    breaker.record_failure("cerebras", status_code=402, is_permanent=True, error_msg="402 Payment Required")
    assert breaker.can_call("cerebras") is False

    # Mock Groq to fail with network error
    mock_groq = AsyncMock(spec=httpx.AsyncClient)
    mock_groq.post.side_effect = httpx.ConnectError("Groq unreachable")

    mock_cerebras = AsyncMock(spec=httpx.AsyncClient)

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq), \
         patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_cerebras), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        reqs = [Requirement(requirement_id="req_1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev_1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="cand_123")

        assert verdicts == []
        assert "cerebras" in tele["circuit_skipped"]
        mock_cerebras.post.assert_not_called()


# 5. Test Circuit Breaker recovery after cooldown expires (HALF_OPEN -> CLOSED on success)
@pytest.mark.asyncio
async def test_circuit_breaker_half_open_recovery():
    settings = make_test_settings()
    settings.PROVIDER_CIRCUIT_BREAKER_COOLDOWN_SECONDS = 0.05
    breaker = ProviderCircuitBreaker.get_breaker(settings)

    breaker.record_failure("cerebras", status_code=402, is_permanent=True, error_msg="402 Payment Required")
    assert breaker.can_call("cerebras") is False

    # Wait for cooldown to expire
    await asyncio.sleep(0.06)
    assert breaker.can_call("cerebras") is True  # Transitions to HALF_OPEN

    # Record success -> transitions to CLOSED
    breaker.record_success("cerebras")
    assert breaker._states["cerebras"]["state"] == "CLOSED"
    assert breaker.can_call("cerebras") is True


# 6. Test that EVALUATION_FAILED fires correctly when all providers/retries exhausted
@pytest.mark.asyncio
async def test_hybrid_matching_service_evaluation_failed_fallback():
    settings = make_test_settings()

    mock_evaluator = AsyncMock()
    # Returns empty verdicts (both providers failed)
    mock_evaluator.evaluate.return_value = ([], {"provider_selected": "none", "fallback_reason": "all_exhausted"})

    matching_service = HybridMatchingService(settings=settings, evaluator=mock_evaluator)

    job = MagicMock()
    job.skills = ["Advanced Kubernetes Orchestration"]
    job.responsibilities = ["Lead large-scale distributed database migrations"]
    job.requirements = []
    job.degree_requirements = []
    job.qualifications = []
    job.certifications = []
    job.project_requirements = []
    job.requirement_classifications = {}
    job.raw_metadata = {}
    job.required_degree = None

    resume = MagicMock()
    resume.id = "cand_failed_1"
    resume.skills = []
    resume.work_experiences = []
    resume.projects = []

    extracted = MagicMock()
    extracted.skills = ["Kubernetes", "Database"]
    extracted.work_experiences = [{"description": "Worked on Kubernetes and Database"}]
    extracted.projects = []
    extracted.education = []
    extracted.certifications = []
    extracted.languages = []

    enriched, fused_verdicts = await matching_service.match(job, resume, extracted)

    # Every unresolved requirement must be marked as MatchStatus.EVALUATION_FAILED
    for v in fused_verdicts:
        if v.method == MatchMethod.EVALUATION_FAILED:
            assert v.status == MatchStatus.EVALUATION_FAILED
            assert v.coverage_score == 0.0
            assert "AI evaluation could not be completed" in v.reasoning


# 7. Test ResumeQueueScheduler request pacing/throttling
@pytest.mark.asyncio
async def test_resume_queue_scheduler_request_pacing():
    scheduler = ResumeQueueScheduler(max_concurrent=2, throttle_seconds=0.05)

    async def mock_task():
        await asyncio.sleep(0.01)
        return "done"

    t0 = time.monotonic()
    tasks = [scheduler.run_resume_task(f"res_{i}", mock_task()) for i in range(3)]
    results = await asyncio.gather(*tasks)
    elapsed = time.monotonic() - t0

    assert results == ["done", "done", "done"]
    assert elapsed >= 0.05
