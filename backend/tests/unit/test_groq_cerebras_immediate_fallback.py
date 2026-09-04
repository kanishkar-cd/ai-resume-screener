import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from app.schemas.matching import Evidence, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind
from app.services.matching_service import (
    CerebrasMatchEvaluator,
    CerebrasTokenBudgetGate,
    GroqMatchEvaluator,
    GroqTokenBudgetGate,
    ProviderCircuitBreaker,
    SmartMatchEvaluator,
)


@pytest.fixture(autouse=True)
def reset_gates():
    ProviderCircuitBreaker.reset_breaker()
    GroqTokenBudgetGate.reset_gate()
    CerebrasTokenBudgetGate.reset_gate()
    GroqMatchEvaluator._cache.clear()
    CerebrasMatchEvaluator._cache.clear()


def make_test_settings():
    return MagicMock(
        ENABLE_HYBRID_MATCHING=True,
        GROQ_API_KEY="mock_groq_key",
        GROQ_BASE_URL="https://api.groq.com/openai/v1",
        GROQ_MODEL="openai/gpt-oss-20b",
        GROQ_TIMEOUT_SECONDS=5.0,
        GROQ_TPM_LIMIT=8000,
        GROQ_TPM_SAFETY_MARGIN=0.125,
        GROQ_MAX_RETRIES=2,
        CEREBRAS_API_KEY="mock_cerebras_key",
        CEREBRAS_BASE_URL="https://api.cerebras.ai/v1",
        CEREBRAS_MODEL="gpt-oss-120b",
        CEREBRAS_TIMEOUT_SECONDS=5.0,
        CEREBRAS_TPM_LIMIT=60000,
        CEREBRAS_TPM_SAFETY_MARGIN=0.10,
        CEREBRAS_MAX_RETRIES=2,
        LLM_BATCH_THROTTLE_SECONDS=0.0,
        PROVIDER_CIRCUIT_BREAKER_COOLDOWN_SECONDS=60.0,
        PROVIDER_CIRCUIT_BREAKER_MAX_FAILURES=2,
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_CACHE_SIZE=100,
    )


def make_valid_response(requirement_id: str = "req1", reasoning: str = "Valid match", provider_tokens: int = 120):
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "verdicts": [
                            {
                                "requirement_id": requirement_id,
                                "status": "MATCHED",
                                "coverage_score": 1.0,
                                "confidence": 0.95,
                                "evidence_ids": ["ev1"],
                                "reasoning": reasoning,
                            }
                        ]
                    })
                }
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": provider_tokens},
    }


# Test 1: Groq budget available -> Groq called, Cerebras not called
@pytest.mark.asyncio
async def test_1_groq_budget_available_calls_groq_not_cerebras():
    settings = make_test_settings()
    smart_eval = SmartMatchEvaluator(settings)

    mock_groq_resp = MagicMock(spec=httpx.Response)
    mock_groq_resp.status_code = 200
    mock_groq_resp.json.return_value = make_valid_response("req1", "Groq direct match", 120)
    mock_groq_resp.raise_for_status = MagicMock()

    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)
    mock_groq_client.post.return_value = mock_groq_resp

    mock_cerebras_client = AsyncMock(spec=httpx.AsyncClient)

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client), \
         patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_cerebras_client):
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_1")

        assert len(verdicts) == 1
        assert tele["provider_selected"] == "groq"
        assert tele["reason"] == "budget_available"
        assert tele["actual_total_tokens"] == 120
        mock_groq_client.post.assert_called_once()
        mock_cerebras_client.post.assert_not_called()


# Test 2: Groq budget exhausted -> Groq HTTP request NOT called, Cerebras called immediately, NO asyncio.sleep()
@pytest.mark.asyncio
async def test_2_groq_budget_exhausted_skips_groq_and_invokes_cerebras_immediately_no_sleep():
    settings = make_test_settings()
    gate = GroqTokenBudgetGate.get_gate(settings)
    # Saturate Groq budget so try_reserve fails
    gate.reserved_in_flight = gate.usable_tpm

    smart_eval = SmartMatchEvaluator(settings)

    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)

    mock_cerebras_resp = MagicMock(spec=httpx.Response)
    mock_cerebras_resp.status_code = 200
    mock_cerebras_resp.json.return_value = make_valid_response("req1", "Cerebras fallback match", 150)
    mock_cerebras_resp.raise_for_status = MagicMock()

    mock_cerebras_client = AsyncMock(spec=httpx.AsyncClient)
    mock_cerebras_client.post.return_value = mock_cerebras_resp

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client), \
         patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_cerebras_client), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        t0 = time.monotonic()
        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_2")
        duration = time.monotonic() - t0

        assert duration < 0.5
        assert len(verdicts) == 1
        assert tele["provider_selected"] == "cerebras"
        assert tele["reason"] == "groq_budget_exhausted"
        assert tele["fallback_reason"] == "groq_budget_exhausted"
        # Groq HTTP client must NOT be called
        mock_groq_client.post.assert_not_called()
        # Cerebras must be called
        mock_cerebras_client.post.assert_called_once()
        # Zero sleep
        mock_sleep.assert_not_called()


# Test 3: Groq timeout -> Retries transient error, then Cerebras called
@pytest.mark.asyncio
async def test_3_groq_timeout_immediately_invokes_cerebras():
    settings = make_test_settings()
    smart_eval = SmartMatchEvaluator(settings)

    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)
    mock_groq_client.post.side_effect = httpx.TimeoutException("Groq gateway timeout")

    mock_cerebras_resp = MagicMock(spec=httpx.Response)
    mock_cerebras_resp.status_code = 200
    mock_cerebras_resp.json.return_value = make_valid_response("req1", "Cerebras after timeout", 180)
    mock_cerebras_resp.raise_for_status = MagicMock()

    mock_cerebras_client = AsyncMock(spec=httpx.AsyncClient)
    mock_cerebras_client.post.return_value = mock_cerebras_resp

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client), \
         patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_cerebras_client), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_3")

        assert len(verdicts) == 1
        assert tele["provider_selected"] == "cerebras"
        assert tele["reason"] == "groq_timeout"
        assert mock_groq_client.post.call_count == 3
        mock_cerebras_client.post.assert_called_once()
        assert mock_sleep.call_count >= 2


# Test 4: Groq 429 -> Retries with backoff, then falls back to Cerebras
@pytest.mark.asyncio
async def test_4_groq_429_immediately_invokes_cerebras_no_retry_wait():
    settings = make_test_settings()
    smart_eval = SmartMatchEvaluator(settings)

    req_429 = MagicMock(spec=httpx.Response)
    req_429.status_code = 429
    req_429.headers = {"Retry-After": "45.0"}
    req_429.text = '{"error": "Rate limit exceeded"}'
    err_429 = httpx.HTTPStatusError("429 Rate Limit", request=MagicMock(), response=req_429)
    req_429.raise_for_status.side_effect = err_429

    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)
    mock_groq_client.post.return_value = req_429

    mock_cerebras_resp = MagicMock(spec=httpx.Response)
    mock_cerebras_resp.status_code = 200
    mock_cerebras_resp.json.return_value = make_valid_response("req1", "Cerebras after 429", 190)
    mock_cerebras_resp.raise_for_status = MagicMock()

    mock_cerebras_client = AsyncMock(spec=httpx.AsyncClient)
    mock_cerebras_client.post.return_value = mock_cerebras_resp

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client), \
         patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_cerebras_client), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_4")

        assert len(verdicts) == 1
        assert tele["provider_selected"] == "cerebras"
        assert tele["reason"] == "groq_429"
        assert mock_groq_client.post.call_count == 3
        mock_cerebras_client.post.assert_called_once()
        assert mock_sleep.call_count >= 2


# Test 5: Groq 500 -> Retries transient error, then falls back to Cerebras
@pytest.mark.asyncio
async def test_5_groq_500_immediately_invokes_cerebras():
    settings = make_test_settings()
    smart_eval = SmartMatchEvaluator(settings)

    req_500 = MagicMock(spec=httpx.Response)
    req_500.status_code = 500
    req_500.text = '{"error": "Internal Server Error"}'
    err_500 = httpx.HTTPStatusError("500 Server Error", request=MagicMock(), response=req_500)
    req_500.raise_for_status.side_effect = err_500

    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)
    mock_groq_client.post.return_value = req_500

    mock_cerebras_resp = MagicMock(spec=httpx.Response)
    mock_cerebras_resp.status_code = 200
    mock_cerebras_resp.json.return_value = make_valid_response("req1", "Cerebras after 500", 175)
    mock_cerebras_resp.raise_for_status = MagicMock()

    mock_cerebras_client = AsyncMock(spec=httpx.AsyncClient)
    mock_cerebras_client.post.return_value = mock_cerebras_resp

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client), \
         patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_cerebras_client), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_5")

        assert len(verdicts) == 1
        assert tele["provider_selected"] == "cerebras"
        assert tele["reason"] == "groq_500"
        assert mock_groq_client.post.call_count == 3
        mock_cerebras_client.post.assert_called_once()
        assert mock_sleep.call_count >= 2


# Test 6: Groq network error -> Retries, then falls back to Cerebras
@pytest.mark.asyncio
async def test_6_groq_network_error_immediately_invokes_cerebras():
    settings = make_test_settings()
    smart_eval = SmartMatchEvaluator(settings)

    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)
    mock_groq_client.post.side_effect = httpx.ConnectError("Connection refused to api.groq.com")

    mock_cerebras_resp = MagicMock(spec=httpx.Response)
    mock_cerebras_resp.status_code = 200
    mock_cerebras_resp.json.return_value = make_valid_response("req1", "Cerebras after network error", 160)
    mock_cerebras_resp.raise_for_status = MagicMock()

    mock_cerebras_client = AsyncMock(spec=httpx.AsyncClient)
    mock_cerebras_client.post.return_value = mock_cerebras_resp

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client), \
         patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_cerebras_client), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_6")

        assert len(verdicts) == 1
        assert tele["provider_selected"] == "cerebras"
        assert tele["reason"] == "groq_network_error"
        assert mock_groq_client.post.call_count == 3
        mock_cerebras_client.post.assert_called_once()
        assert mock_sleep.call_count >= 2


# Test 7: Groq returns invalid/empty verdict -> Cerebras called
@pytest.mark.asyncio
async def test_7_groq_empty_or_invalid_verdict_immediately_invokes_cerebras():
    settings = make_test_settings()
    smart_eval = SmartMatchEvaluator(settings)

    # Groq returns empty verdicts list
    mock_groq_resp = MagicMock(spec=httpx.Response)
    mock_groq_resp.status_code = 200
    mock_groq_resp.json.return_value = {"choices": [{"message": {"content": json.dumps({"verdicts": []})}}]}
    mock_groq_resp.raise_for_status = MagicMock()

    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)
    mock_groq_client.post.return_value = mock_groq_resp

    mock_cerebras_resp = MagicMock(spec=httpx.Response)
    mock_cerebras_resp.status_code = 200
    mock_cerebras_resp.json.return_value = make_valid_response("req1", "Cerebras recovered from empty Groq", 140)
    mock_cerebras_resp.raise_for_status = MagicMock()

    mock_cerebras_client = AsyncMock(spec=httpx.AsyncClient)
    mock_cerebras_client.post.return_value = mock_cerebras_resp

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client), \
         patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_cerebras_client), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_7")

        assert len(verdicts) == 1
        assert tele["provider_selected"] == "cerebras"
        assert tele["reason"] == "groq_empty_or_invalid_verdict"
        mock_groq_client.post.assert_called_once()
        mock_cerebras_client.post.assert_called_once()


# Test 8: Cerebras succeeds -> Final LLM verdict comes from Cerebras
@pytest.mark.asyncio
async def test_8_cerebras_succeeds_verdicts_returned():
    settings = make_test_settings()
    smart_eval = SmartMatchEvaluator(settings)

    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)
    mock_groq_client.post.side_effect = httpx.ConnectError("Groq offline")

    mock_cerebras_resp = MagicMock(spec=httpx.Response)
    mock_cerebras_resp.status_code = 200
    mock_cerebras_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "verdicts": [
                            {
                                "requirement_id": "skill:1",
                                "status": "MATCHED",
                                "coverage_score": 1.0,
                                "confidence": 0.94,
                                "evidence_ids": ["ev1"],
                                "reasoning": "High confidence Cerebras match",
                            }
                        ]
                    })
                }
            }
        ],
        "usage": {"prompt_tokens": 200, "completion_tokens": 40, "total_tokens": 240},
    }
    mock_cerebras_resp.raise_for_status = MagicMock()

    mock_cerebras_client = AsyncMock(spec=httpx.AsyncClient)
    mock_cerebras_client.post.return_value = mock_cerebras_resp

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client), \
         patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_cerebras_client), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_8")

        assert len(verdicts) == 1
        assert verdicts[0].requirement_id == "skill:1"
        assert verdicts[0].status == MatchStatus.MATCHED
        assert verdicts[0].confidence == 0.94
        assert tele["provider_selected"] == "cerebras"
        assert tele["actual_total_tokens"] == 240


# Test 9: Both providers fail -> Existing graceful error behavior
@pytest.mark.asyncio
async def test_9_both_providers_fail_graceful_handling():
    settings = make_test_settings()
    smart_eval = SmartMatchEvaluator(settings)

    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)
    mock_groq_client.post.side_effect = httpx.ConnectError("Groq down")

    mock_cerebras_client = AsyncMock(spec=httpx.AsyncClient)
    mock_cerebras_client.post.side_effect = httpx.ConnectError("Cerebras down")

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client), \
         patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_cerebras_client), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        t0 = time.monotonic()
        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_9")
        duration = time.monotonic() - t0

        assert duration < 1.0
        assert verdicts == []
        assert tele["provider_selected"] == "cerebras"
        assert tele["actual_total_tokens"] == 0


# Test 10: Concurrent resume evaluation -> atomic reservations, no race condition, no oversubscription
@pytest.mark.asyncio
async def test_10_concurrent_resume_evaluations_atomic_safety_and_immediate_fallback():
    settings = make_test_settings()
    # Usable limit = 8000 * 0.875 = 7000 tokens
    settings.GROQ_TPM_LIMIT = 8000
    settings.GROQ_TPM_SAFETY_MARGIN = 0.125
    groq_gate = GroqTokenBudgetGate.get_gate(settings)
    groq_gate.reset_gate()

    smart_eval = SmartMatchEvaluator(settings)

    groq_call_count = 0
    cerebras_call_count = 0
    lock = asyncio.Lock()

    async def mock_groq_post(*args, **kwargs):
        nonlocal groq_call_count
        async with lock:
            groq_call_count += 1
        await asyncio.sleep(0.02)
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = make_valid_response("req1", "Groq concurrent verdict", 200)
        resp.raise_for_status = MagicMock()
        return resp

    async def mock_cerebras_post(*args, **kwargs):
        nonlocal cerebras_call_count
        async with lock:
            cerebras_call_count += 1
        await asyncio.sleep(0.01)
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = make_valid_response("req1", "Cerebras concurrent verdict", 200)
        resp.raise_for_status = MagicMock()
        return resp

    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)
    mock_groq_client.post.side_effect = mock_groq_post

    mock_cerebras_client = AsyncMock(spec=httpx.AsyncClient)
    mock_cerebras_client.post.side_effect = mock_cerebras_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client), \
         patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_cerebras_client):
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        # Each payload estimates to ~1350-1400 tokens.
        # With usable_tpm = 7000, at most 5 can be in-flight concurrently on Groq.
        # The remaining 5 concurrent requests MUST immediately route to Cerebras without blocking!
        tasks = [
            smart_eval.evaluate(reqs, evs, resume_id=f"res_{i}")
            for i in range(10)
        ]

        t0 = time.monotonic()
        results = await asyncio.gather(*tasks)
        duration = time.monotonic() - t0

        assert duration < 2.0  # Completed swiftly without waiting for 60s window
        assert len(results) == 10

        groq_results = [r for r in results if r[1]["provider_selected"] == "groq"]
        cerebras_results = [r for r in results if r[1]["provider_selected"] == "cerebras"]

        # Both providers were utilized
        assert len(groq_results) > 0
        assert len(cerebras_results) > 0
        assert len(groq_results) + len(cerebras_results) == 10

        # All requests produced valid verdicts
        for verdicts, tele in results:
            assert len(verdicts) == 1
            assert verdicts[0].status == MatchStatus.MATCHED

        # For requests routed to Cerebras, reason was groq_budget_exhausted
        for _, tele in cerebras_results:
            assert tele["reason"] == "groq_budget_exhausted"
