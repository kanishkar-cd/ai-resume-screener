import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.schemas.matching import Evidence, MatchVerdict, Requirement, RequirementKind
from app.services.matching_service import (
    CerebrasMatchEvaluator,
    GroqMatchEvaluator,
    GroqTokenBudgetGate,
    ProviderCircuitBreaker,
    SmartMatchEvaluator,
)


@pytest.fixture(autouse=True)
def reset_state():
    ProviderCircuitBreaker.reset_breaker()
    GroqTokenBudgetGate.reset_gate()
    GroqMatchEvaluator._cache.clear()
    CerebrasMatchEvaluator._cache.clear()


def make_settings(enable_cerebras=False, cerebras_key=None):
    return MagicMock(
        ENABLE_HYBRID_MATCHING=True,
        ENABLE_CEREBRAS_FALLBACK=enable_cerebras,
        GROQ_API_KEY="mock_groq_key",
        GROQ_BASE_URL="https://api.groq.com/openai/v1",
        GROQ_MODEL="openai/gpt-oss-20b",
        GROQ_TIMEOUT_SECONDS=5.0,
        GROQ_TPM_LIMIT=8000,
        GROQ_TPM_SAFETY_MARGIN=0.125,
        GROQ_MAX_RETRIES=1,
        GROQ_BUDGET_WAIT_TIMEOUT_SECONDS=5.0,
        CEREBRAS_API_KEY=cerebras_key,
        CEREBRAS_BASE_URL="https://api.cerebras.ai/v1",
        CEREBRAS_MODEL="gpt-oss-120b",
        CEREBRAS_TIMEOUT_SECONDS=5.0,
        CEREBRAS_MAX_RETRIES=1,
        PROVIDER_CIRCUIT_BREAKER_COOLDOWN_SECONDS=1.0,
        PROVIDER_CIRCUIT_BREAKER_MAX_FAILURES=1,
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_CACHE_SIZE=100,
    )


def make_verdict_response(req_id: str, reason: str = "Matched", ev_ids: list[str] | None = None):
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "verdicts": [
                            {
                                "requirement_id": req_id,
                                "status": "MATCHED",
                                "confidence": 0.95,
                                "reasoning": reason,
                                "evidence_ids": ev_ids if ev_ids is not None else ["ev1"],
                            }
                        ]
                    })
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 500,
            "completion_tokens": 100,
            "total_tokens": 600,
        },
    }


# 1. 1 resume -> Groq succeeds
@pytest.mark.asyncio
async def test_single_resume_groq_succeeds():
    settings = make_settings()
    smart_eval = SmartMatchEvaluator(settings)

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = make_verdict_response("req_1")
    mock_resp.headers = {"x-ratelimit-remaining-tokens": "7000"}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_resp

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        reqs = [Requirement(requirement_id="req_1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python")]

        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_1")

        assert len(verdicts) == 1
        assert verdicts[0].status == "MATCHED"
        assert tele["provider_selected"] == "groq"
        assert tele["fallback_used"] is False
        mock_client.post.assert_called_once()


# 2. 2+ resumes -> evaluations safely queued/throttled sharing Groq TPM budget
@pytest.mark.asyncio
async def test_multi_resume_concurrent_budget_queuing():
    settings = make_settings()
    gate = GroqTokenBudgetGate.get_gate(settings)
    smart_eval = SmartMatchEvaluator(settings)

    call_log = []

    async def mock_post(url, **kwargs):
        call_log.append(("start", time.monotonic()))
        await asyncio.sleep(0.05)
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = make_verdict_response("req_common")
        resp.headers = {"x-ratelimit-remaining-tokens": "6000"}
        call_log.append(("end", time.monotonic()))
        return resp

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        reqs = [Requirement(requirement_id="req_common", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python")]

        # Consume 5000 tokens so only 2000 remain
        gate.reserved_in_flight = 5000

        task1 = asyncio.create_task(smart_eval.evaluate(reqs, evs, resume_id="res_concurrent_1"))
        task2 = asyncio.create_task(smart_eval.evaluate(reqs, evs, resume_id="res_concurrent_2"))

        # Release the 5000 in-flight tokens after 0.02s
        await asyncio.sleep(0.02)
        await gate.release_reservation(5000)

        res1, res2 = await asyncio.gather(task1, task2)

        v1, tele1 = res1
        v2, tele2 = res2

        assert len(v1) == 1
        assert len(v2) == 1
        assert tele1["provider_selected"] == "groq"
        assert tele2["provider_selected"] == "groq"


# 3. Concurrent requests cannot overspend the shared budget
@pytest.mark.asyncio
async def test_concurrent_requests_cannot_overspend_budget():
    settings = make_settings()
    gate = GroqTokenBudgetGate.get_gate(settings)

    # Max usable is 7000
    res1 = await gate.try_reserve(4000)
    assert res1 is True
    assert gate.reserved_in_flight == 4000

    # Second parallel request tries to reserve 4000 -> 4000 + 4000 > 7000 -> must fail
    res2 = await gate.try_reserve(4000)
    assert res2 is False
    # Budget did not overspend
    assert gate.reserved_in_flight == 4000

    # Release 4000
    await gate.release_reservation(4000)
    assert gate.reserved_in_flight == 0

    # Now it can reserve
    res3 = await gate.try_reserve(4000)
    assert res3 is True


# 4. Temporarily insufficient Groq budget waits/retries instead of selecting unavailable Cerebras
@pytest.mark.asyncio
async def test_temporarily_insufficient_groq_budget_waits_and_retries():
    settings = make_settings(enable_cerebras=False)
    gate = GroqTokenBudgetGate.get_gate(settings)
    smart_eval = SmartMatchEvaluator(settings)

    # Exhaust budget initially
    gate.reserved_in_flight = gate.usable_tpm

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = make_verdict_response("req_wait")
    mock_resp.headers = {"x-ratelimit-remaining-tokens": "7000"}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_resp

    async def replenish_soon():
        await asyncio.sleep(0.05)
        await gate.release_reservation(gate.usable_tpm)

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        reqs = [Requirement(requirement_id="req_wait", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python")]

        asyncio.create_task(replenish_soon())
        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_waiting")

        assert len(verdicts) == 1
        assert tele["provider_selected"] == "groq"
        assert tele["reason"] == "budget_replenished_after_wait"


# 5. Cerebras disabled/unfunded -> never called
@pytest.mark.asyncio
async def test_cerebras_disabled_or_unfunded_never_called():
    settings = make_settings(enable_cerebras=False, cerebras_key=None)
    smart_eval = SmartMatchEvaluator(settings)

    mock_cerebras_client = AsyncMock(spec=httpx.AsyncClient)

    # Force Groq circuit to open
    breaker = ProviderCircuitBreaker.get_breaker(settings)
    breaker.record_failure("groq", status_code=500)

    with patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_cerebras_client):
        reqs = [Requirement(requirement_id="req_noback", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python")]

        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_no_cerebras")

        # Cerebras must never have been called
        mock_cerebras_client.post.assert_not_called()
        assert tele["provider_selected"] != "cerebras"
        assert verdicts == []


# 6. Circuit breaker permanent 402 lockout never resets to HALF_OPEN
def test_circuit_breaker_permanent_402_never_resets():
    settings = make_settings()
    breaker = ProviderCircuitBreaker.get_breaker(settings)

    # Initial state is callable
    assert breaker.can_call("cerebras") is True

    # Record 402 payment required
    breaker.record_failure("cerebras", status_code=402, is_permanent=True)

    # Circuit is immediately OPEN and cannot be called
    assert breaker.can_call("cerebras") is False

    # Simulate cooldown expiration
    entry = breaker._states["cerebras"]
    entry["last_failure_time"] = time.monotonic() - 9999.0

    # Even after cooldown, permanent failure must NEVER reset to HALF_OPEN
    assert breaker.can_call("cerebras") is False


# 7. Resume A failure does not affect Resume B
@pytest.mark.asyncio
async def test_resume_a_failure_does_not_affect_resume_b():
    settings = make_settings()
    smart_eval = SmartMatchEvaluator(settings)

    async def mock_post(url, json=None, **kwargs):
        content = json["messages"][-1]["content"]
        if "resume_a" in content:
            raise httpx.ConnectError("Connection failed for resume_a")
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = make_verdict_response("req_b", ev_ids=["ev_b"])
        resp.headers = {"x-ratelimit-remaining-tokens": "7000"}
        return resp

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        reqs_a = [Requirement(requirement_id="req_a", kind=RequirementKind.SKILL, text="resume_a", required=True)]
        evs_a = [Evidence(evidence_id="ev_a", kind="skills", text="resume_a")]

        reqs_b = [Requirement(requirement_id="req_b", kind=RequirementKind.SKILL, text="resume_b", required=True)]
        evs_b = [Evidence(evidence_id="ev_b", kind="skills", text="resume_b")]

        res_a, res_b = await asyncio.gather(
            smart_eval.evaluate(reqs_a, evs_a, resume_id="resume_a"),
            smart_eval.evaluate(reqs_b, evs_b, resume_id="resume_b"),
        )

        v_a, tele_a = res_a
        v_b, tele_b = res_b

        # Resume A failed cleanly
        assert v_a == []
        # Resume B succeeded completely
        assert len(v_b) == 1
        assert v_b[0].status == "MATCHED"
        assert tele_b["provider_selected"] == "groq"
