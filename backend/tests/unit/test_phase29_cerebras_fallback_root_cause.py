from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from app.core.config import Settings
from app.schemas.matching import (
    Evidence,
    LLMVerdictBatch,
    MatchMethod,
    MatchStatus,
    MatchVerdict,
    Requirement,
    RequirementKind,
)
from app.services.matching_service import (
    CerebrasMatchEvaluator,
    CerebrasTokenBudgetGate,
    GroqMatchEvaluator,
    GroqTokenBudgetGate,
    HybridMatchingService,
    ProviderCircuitBreaker,
    SmartMatchEvaluator,
)
from app.services.llm.provider_router import (
    CerebrasAdapter,
    GroqAdapter,
    ProviderRouter,
)
from app.services.llm.provider_types import LLMRequest, ProviderResult, ProviderStatus


@pytest.fixture(autouse=True)
def clean_state():
    """Reset provider circuit breaker and token gates between test runs."""
    ProviderCircuitBreaker.reset_breaker()
    GroqTokenBudgetGate.reset_gate()
    CerebrasTokenBudgetGate.reset_gate()
    GroqMatchEvaluator._cache.clear()
    CerebrasMatchEvaluator._cache.clear()


def _make_mock_settings():
    return Settings(
        ENABLE_HYBRID_MATCHING=True,
        GROQ_API_KEY="mock_groq_key",
        GROQ_BASE_URL="https://api.groq.com/openai/v1",
        GROQ_MODEL="openai/gpt-oss-20b",
        GROQ_TIMEOUT_SECONDS=2.0,
        GROQ_MAX_RETRIES=1,
        CEREBRAS_API_KEY="mock_cerebras_key",
        CEREBRAS_BASE_URL="https://api.cerebras.ai/v1",
        CEREBRAS_MODEL="llama3.1-70b",
        CEREBRAS_TIMEOUT_SECONDS=2.0,
        CEREBRAS_MAX_RETRIES=1,
    )


# ==============================================================================
# TEST 1 — GROQ SUCCESS: Cerebras not called
# ==============================================================================

@pytest.mark.asyncio
async def test_1_groq_success_cerebras_not_called():
    """Groq succeeds -> Cerebras is never called; provider=groq."""
    settings = _make_mock_settings()
    groq_eval = GroqMatchEvaluator(settings)
    cerebras_eval = CerebrasMatchEvaluator(settings)

    groq_eval.evaluate_with_usage = AsyncMock(return_value=([
        MatchVerdict(
            requirement_id="req:1",
            status=MatchStatus.MATCHED,
            method=MatchMethod.LLM,
            confidence=0.95,
            evidence_ids=["exp:1"],
            reasoning="Candidate has direct experience.",
        )
    ], {"total_tokens": 120, "prompt_tokens": 100, "completion_tokens": 20}))

    cerebras_eval.evaluate_with_usage = AsyncMock()

    smart_eval = SmartMatchEvaluator(settings, groq_evaluator=groq_eval, cerebras_evaluator=cerebras_eval)

    reqs = [Requirement(requirement_id="req:1", kind=RequirementKind.RESPONSIBILITY, text="Lead backend architecture")]
    evs = [Evidence(evidence_id="exp:1", kind="experience", text="Managed lead backend architecture")]

    verdicts, tele = await smart_eval.evaluate(reqs, evs)

    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.MATCHED
    assert tele["provider_selected"] == "groq"
    assert tele["fallback_used"] is False
    assert tele["actual_total_tokens"] == 120
    groq_eval.evaluate_with_usage.assert_called_once()
    cerebras_eval.evaluate_with_usage.assert_not_called()


# ==============================================================================
# TEST 2 — GROQ 429 -> CEREBRAS SUCCESS
# ==============================================================================

@pytest.mark.asyncio
async def test_2_groq_429_routes_immediately_to_cerebras():
    """Groq 429 rate limit -> immediate Cerebras fallback produces valid decision."""
    settings = _make_mock_settings()
    groq_eval = GroqMatchEvaluator(settings)
    cerebras_eval = CerebrasMatchEvaluator(settings)

    req_mock = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp_mock = httpx.Response(429, request=req_mock, text='{"error": "rate_limit_exceeded"}')
    groq_eval.evaluate_with_usage = AsyncMock(side_effect=httpx.HTTPStatusError("429 Rate Limit", request=req_mock, response=resp_mock))

    cerebras_verdict = MatchVerdict(
        requirement_id="req:1",
        status=MatchStatus.MATCHED,
        method=MatchMethod.LLM,
        confidence=0.92,
        evidence_ids=["exp:1"],
        reasoning="Cerebras confirmed candidate experience.",
    )
    cerebras_eval.evaluate_with_usage = AsyncMock(return_value=([cerebras_verdict], {"total_tokens": 140, "prompt_tokens": 110, "completion_tokens": 30}))

    smart_eval = SmartMatchEvaluator(settings, groq_evaluator=groq_eval, cerebras_evaluator=cerebras_eval)

    reqs = [Requirement(requirement_id="req:1", kind=RequirementKind.RESPONSIBILITY, text="Lead backend architecture")]
    evs = [Evidence(evidence_id="exp:1", kind="experience", text="Managed lead backend architecture")]

    verdicts, tele = await smart_eval.evaluate(reqs, evs)

    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.MATCHED
    assert "Cerebras confirmed" in verdicts[0].reasoning
    assert tele["provider_selected"] == "cerebras"
    assert tele["fallback_used"] is True
    assert "groq_rate_limit" in tele["reason"]
    groq_eval.evaluate_with_usage.assert_called_once()
    cerebras_eval.evaluate_with_usage.assert_called_once()


# ==============================================================================
# TEST 3 — GROQ BUDGET EXHAUSTED -> CEREBRAS SUCCESS
# ==============================================================================

@pytest.mark.asyncio
async def test_3_groq_budget_exhausted_routes_to_cerebras():
    """Groq budget reservation fails -> immediate failover to Cerebras without calling Groq client."""
    settings = _make_mock_settings()
    gate = GroqTokenBudgetGate.get_gate(settings)
    # Drain Groq gate
    gate.reserved_in_flight = gate.usable_tpm + 5000
    assert gate.available_tokens() == 0

    groq_eval = GroqMatchEvaluator(settings)
    groq_eval.evaluate_with_usage = AsyncMock()
    cerebras_eval = CerebrasMatchEvaluator(settings)

    cerebras_verdict = MatchVerdict(
        requirement_id="req:1",
        status=MatchStatus.MATCHED,
        method=MatchMethod.LLM,
        confidence=0.89,
        evidence_ids=["exp:1"],
        reasoning="Cerebras evaluated within available budget.",
    )
    cerebras_eval.evaluate_with_usage = AsyncMock(return_value=([cerebras_verdict], {"total_tokens": 115}))

    smart_eval = SmartMatchEvaluator(settings, groq_evaluator=groq_eval, cerebras_evaluator=cerebras_eval)

    reqs = [Requirement(requirement_id="req:1", kind=RequirementKind.RESPONSIBILITY, text="Lead backend architecture")]
    evs = [Evidence(evidence_id="exp:1", kind="experience", text="Managed lead backend architecture")]

    verdicts, tele = await smart_eval.evaluate(reqs, evs)

    assert len(verdicts) == 1
    assert tele["provider_selected"] == "cerebras"
    assert tele["fallback_reason"] == "groq_budget_exhausted"
    groq_eval.evaluate_with_usage.assert_not_called()
    cerebras_eval.evaluate_with_usage.assert_called_once()


# ==============================================================================
# TEST 4 — GROQ TIMEOUT -> CEREBRAS SUCCESS
# ==============================================================================

@pytest.mark.asyncio
async def test_4_groq_timeout_routes_to_cerebras():
    """Groq read timeout -> immediate failover to Cerebras succeeds."""
    settings = _make_mock_settings()
    groq_eval = GroqMatchEvaluator(settings)
    cerebras_eval = CerebrasMatchEvaluator(settings)

    groq_eval.evaluate_with_usage = AsyncMock(side_effect=httpx.TimeoutException("Groq read timed out"))
    cerebras_eval.evaluate_with_usage = AsyncMock(return_value=([
        MatchVerdict(requirement_id="req:1", status=MatchStatus.MATCHED, method=MatchMethod.LLM, confidence=0.88, evidence_ids=["exp:1"], reasoning="Cerebras success after Groq timeout.")
    ], {"total_tokens": 130}))

    smart_eval = SmartMatchEvaluator(settings, groq_evaluator=groq_eval, cerebras_evaluator=cerebras_eval)

    reqs = [Requirement(requirement_id="req:1", kind=RequirementKind.RESPONSIBILITY, text="Lead backend architecture")]
    evs = [Evidence(evidence_id="exp:1", kind="experience", text="Managed lead backend architecture")]

    verdicts, tele = await smart_eval.evaluate(reqs, evs)

    assert len(verdicts) == 1
    assert tele["provider_selected"] == "cerebras"
    assert "groq_timeout" in tele["reason"]
    assert tele["fallback_used"] is True


# ==============================================================================
# TEST 5 — GROQ SUCCESS -> NO CEREBRAS CALL
# ==============================================================================

@pytest.mark.asyncio
async def test_5_groq_success_never_invokes_cerebras():
    """Zero unnecessary calls: Cerebras must not be contacted when Groq succeeds."""
    settings = _make_mock_settings()
    groq_eval = GroqMatchEvaluator(settings)
    cerebras_eval = CerebrasMatchEvaluator(settings)

    groq_eval.evaluate_with_usage = AsyncMock(return_value=([
        MatchVerdict(requirement_id="req:1", status=MatchStatus.NO_MATCH, method=MatchMethod.LLM_REJECTED, confidence=0.91, evidence_ids=[], reasoning="Candidate lacks required skill.")
    ], {"total_tokens": 90}))
    cerebras_eval.evaluate_with_usage = AsyncMock()

    smart_eval = SmartMatchEvaluator(settings, groq_evaluator=groq_eval, cerebras_evaluator=cerebras_eval)

    reqs = [Requirement(requirement_id="req:1", kind=RequirementKind.SKILL, text="Rust")]
    evs = [Evidence(evidence_id="exp:1", kind="experience", text="Python web development")]

    verdicts, tele = await smart_eval.evaluate(reqs, evs)

    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.NO_MATCH
    assert tele["provider_selected"] == "groq"
    cerebras_eval.evaluate_with_usage.assert_not_called()


# ==============================================================================
# TEST 6 — GROQ FAILURE + CEREBRAS FAILURE -> SAFE UNRESOLVED
# ==============================================================================

@pytest.mark.asyncio
async def test_6_both_providers_fail_safely_unresolved():
    """When both Groq and Cerebras fail, result is safe UNRESOLVED, no crash, no fake match."""
    settings = _make_mock_settings()
    groq_eval = GroqMatchEvaluator(settings)
    cerebras_eval = CerebrasMatchEvaluator(settings)

    groq_eval.evaluate_with_usage = AsyncMock(side_effect=httpx.ConnectError("Groq unreachable"))
    cerebras_eval.evaluate_with_usage = AsyncMock(side_effect=httpx.ConnectError("Cerebras unreachable"))

    smart_eval = SmartMatchEvaluator(settings, groq_evaluator=groq_eval, cerebras_evaluator=cerebras_eval)
    service = HybridMatchingService(settings, evaluator=smart_eval)

    job = SimpleNamespace(
        id="j_fail", title="Lead DevOps",
        responsibilities=["Automate multi-region infrastructure"],
        required_skills=[], preferred_skills=[], experience_requirements=[], project_requirements=[], certifications=[]
    )
    resume = SimpleNamespace(
        name="Candidate", skills=[], experience=[],
        projects=[{"name": "Project", "description": "Cloud operations"}],
        education=[], certifications=[], languages=[]
    )
    extracted = SimpleNamespace(skills=[], experience=[], projects=resume.projects, education=[], certifications=[], languages=[])

    _, verdicts = await service.match(job, resume, extracted)

    assert len(verdicts) == 1
    assert verdicts[0].status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}
    assert verdicts[0].status != MatchStatus.MATCHED
    assert verdicts[0].status != MatchStatus.EVALUATION_FAILED


# ==============================================================================
# TEST 7 — CEREBRAS 402 PAYMENT REQUIRED -> FAST FAIL & CIRCUIT OPEN
# ==============================================================================

@pytest.mark.asyncio
async def test_7_cerebras_402_payment_required_handled_safely():
    """Cerebras HTTP 402 Payment Required -> marked permanent failure, no retries, safe UNRESOLVED."""
    settings = _make_mock_settings()
    breaker = ProviderCircuitBreaker.get_breaker(settings)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    req_mock = httpx.Request("POST", "https://api.cerebras.ai/v1/chat/completions")
    resp_mock = httpx.Response(402, request=req_mock, text='{"message":"Payment required to access this resource.","type":"payment_required_error"}')
    mock_client.post.side_effect = httpx.HTTPStatusError("402 Payment Required", request=req_mock, response=resp_mock)

    cerebras_eval = CerebrasMatchEvaluator(settings)

    with patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_client):
        reqs = [Requirement(requirement_id="req:1", kind=RequirementKind.RESPONSIBILITY, text="Lead architecture")]
        evs = [Evidence(evidence_id="exp:1", kind="experience", text="Managed lead architecture")]

        verdicts, usage = await cerebras_eval.evaluate_with_usage(reqs, evs)

        # 1. Bounded: returns empty immediately without infinite loop
        assert verdicts == []
        # 2. Circuit breaker opened permanently for Cerebras
        assert not breaker.can_call("cerebras")
        # 3. Only 1 attempt made (no retries on 402)
        assert mock_client.post.call_count == 1


# ==============================================================================
# TEST 8 — CEREBRAS MALFORMED / INVALID RESPONSE
# ==============================================================================

@pytest.mark.asyncio
async def test_8_cerebras_malformed_response_safe_unresolved():
    """Cerebras returns malformed JSON -> parsed cleanly without crash, returns safe fallback."""
    settings = _make_mock_settings()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    req_mock = httpx.Request("POST", "https://api.cerebras.ai/v1/chat/completions")
    resp_mock = httpx.Response(200, request=req_mock, json={"choices": [{"message": {"content": "INVALID NOT JSON {"}}]})
    mock_client.post.return_value = resp_mock

    cerebras_eval = CerebrasMatchEvaluator(settings)
    with patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_client):
        reqs = [Requirement(requirement_id="req:1", kind=RequirementKind.RESPONSIBILITY, text="Lead architecture")]
        evs = [Evidence(evidence_id="exp:1", kind="experience", text="Managed lead architecture")]

        verdicts, usage = await cerebras_eval.evaluate_with_usage(reqs, evs)
        assert verdicts == []


# ==============================================================================
# TEST 9 — PROVIDER STATE ISOLATION
# ==============================================================================

@pytest.mark.asyncio
async def test_9_provider_state_isolation_groq_open_does_not_block_cerebras():
    """Tripping Groq circuit breaker does NOT block or disable healthy Cerebras."""
    settings = _make_mock_settings()
    breaker = ProviderCircuitBreaker.get_breaker(settings)

    # Force Groq circuit breaker OPEN
    breaker.record_failure("groq", status_code=500, is_permanent=True)
    assert not breaker.can_call("groq")
    # Cerebras circuit breaker must remain CLOSED and healthy
    assert breaker.can_call("cerebras")

    groq_eval = GroqMatchEvaluator(settings)
    groq_eval.evaluate_with_usage = AsyncMock()
    cerebras_eval = CerebrasMatchEvaluator(settings)
    cerebras_eval.evaluate_with_usage = AsyncMock(return_value=([
        MatchVerdict(requirement_id="req:1", status=MatchStatus.MATCHED, method=MatchMethod.LLM, confidence=0.91, evidence_ids=["exp:1"], reasoning="Cerebras evaluated while Groq circuit was open.")
    ], {"total_tokens": 125}))

    smart_eval = SmartMatchEvaluator(settings, groq_evaluator=groq_eval, cerebras_evaluator=cerebras_eval)

    reqs = [Requirement(requirement_id="req:1", kind=RequirementKind.RESPONSIBILITY, text="Lead backend architecture")]
    evs = [Evidence(evidence_id="exp:1", kind="experience", text="Managed lead backend architecture")]

    verdicts, tele = await smart_eval.evaluate(reqs, evs)

    assert len(verdicts) == 1
    assert tele["provider_selected"] == "cerebras"
    assert "groq" in tele["circuit_skipped"]
    groq_eval.evaluate_with_usage.assert_not_called()
    cerebras_eval.evaluate_with_usage.assert_called_once()


# ==============================================================================
# TEST 10 — REPEATED REQUESTS & PROVIDER STATE INTEGRITY
# ==============================================================================

@pytest.mark.asyncio
async def test_10_repeated_evaluations_state_integrity():
    """State does not become permanently corrupted across multiple evaluations."""
    settings = _make_mock_settings()
    groq_eval = GroqMatchEvaluator(settings)
    cerebras_eval = CerebrasMatchEvaluator(settings)

    # Evaluation 1: Groq succeeds
    groq_eval.evaluate_with_usage = AsyncMock(return_value=([
        MatchVerdict(requirement_id="req:1", status=MatchStatus.MATCHED, method=MatchMethod.LLM, confidence=0.90, evidence_ids=["exp:1"], reasoning="Groq eval 1.")
    ], {"total_tokens": 100}))
    cerebras_eval.evaluate_with_usage = AsyncMock()

    smart_eval = SmartMatchEvaluator(settings, groq_evaluator=groq_eval, cerebras_evaluator=cerebras_eval)
    reqs = [Requirement(requirement_id="req:1", kind=RequirementKind.RESPONSIBILITY, text="Task 1")]
    evs = [Evidence(evidence_id="exp:1", kind="experience", text="Task 1 experience")]

    verdicts1, tele1 = await smart_eval.evaluate(reqs, evs, resume_id="res_1")
    assert tele1["provider_selected"] == "groq"

    # Evaluation 2: Groq temporarily times out -> Cerebras succeeds
    groq_eval.evaluate_with_usage = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
    cerebras_eval.evaluate_with_usage = AsyncMock(return_value=([
        MatchVerdict(requirement_id="req:2", status=MatchStatus.MATCHED, method=MatchMethod.LLM, confidence=0.88, evidence_ids=["exp:2"], reasoning="Cerebras eval 2.")
    ], {"total_tokens": 110}))

    verdicts2, tele2 = await smart_eval.evaluate([Requirement(requirement_id="req:2", kind=RequirementKind.RESPONSIBILITY, text="Task 2")], [Evidence(evidence_id="exp:2", kind="experience", text="Task 2 exp")], resume_id="res_2")
    assert tele2["provider_selected"] == "cerebras"
    assert tele2["fallback_used"] is True


# ==============================================================================
# TEST 11 — END-TO-END MATCHING PIPELINE TEST WITH CEREBRAS FALLBACK
# ==============================================================================

@pytest.mark.asyncio
async def test_11_end_to_end_matching_path_with_cerebras_fallback():
    """
    End-to-end trace:
    JD requirement -> LLM eligible -> Groq 429 -> Cerebras fallback succeeds ->
    requirement decision MATCHED -> final scoring service reflects candidate score.
    """
    settings = _make_mock_settings()
    groq_eval = GroqMatchEvaluator(settings)
    cerebras_eval = CerebrasMatchEvaluator(settings)

    # Groq returns 429
    req_mock = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp_mock = httpx.Response(429, request=req_mock, text='{"error": "rate_limit"}')
    groq_eval.evaluate_with_usage = AsyncMock(side_effect=httpx.HTTPStatusError("429 Rate Limit", request=req_mock, response=resp_mock))

    # Cerebras returns MATCHED
    cerebras_verdict = MatchVerdict(
        requirement_id="responsibility:1",
        status=MatchStatus.MATCHED,
        method=MatchMethod.LLM,
        confidence=0.94,
        evidence_ids=["project:1"],
        reasoning="Cerebras identified candidate distributed systems experience.",
        coverage_score=1.0,
    )
    cerebras_eval.evaluate_with_usage = AsyncMock(return_value=([cerebras_verdict], {"total_tokens": 150}))

    smart_eval = SmartMatchEvaluator(settings, groq_evaluator=groq_eval, cerebras_evaluator=cerebras_eval)
    service = HybridMatchingService(settings, evaluator=smart_eval)

    job = SimpleNamespace(
        id="j_e2e",
        title="Senior Cloud Architect",
        responsibilities=["Lead multi-region distributed system deployment and orchestration."],
        required_skills=[],
        preferred_skills=[],
        experience_requirements=[],
        project_requirements=[],
        certifications=[],
    )
    resume = SimpleNamespace(
        name="Alex Architect",
        skills=[],
        experience=[],
        projects=[{"name": "Cluster Engine", "description": "Engineered global multi-region cloud cluster deployment."}],
        education=[],
        certifications=[],
        languages=[],
    )
    extracted = SimpleNamespace(
        skills=[],
        experience=[],
        projects=resume.projects,
        education=[],
        certifications=[],
        languages=[],
    )

    _, verdicts = await service.match(job, resume, extracted)

    assert len(verdicts) == 1
    v = verdicts[0]
    assert v.status == MatchStatus.MATCHED
    assert v.method in {MatchMethod.LLM, MatchMethod.LLM_CONFIRMED}
    assert v.confidence == 0.94
    assert "project:1" in v.evidence_ids
    assert "Cerebras identified" in v.reasoning
