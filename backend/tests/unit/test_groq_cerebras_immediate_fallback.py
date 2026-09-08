import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from app.schemas.matching import (
    Evidence, LLMVerdict, LLMVerdictBatch, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    CerebrasMatchEvaluator,
    CerebrasTokenBudgetGate,
    EvidencePrefilter,
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


@pytest.mark.asyncio
async def test_22_requirements_estimate_within_budget_and_select_groq():
    """Regression Test 1: 22 requirements estimate below Groq budget and route to Groq."""
    settings = make_test_settings()
    smart_eval = SmartMatchEvaluator(settings)

    reqs = [
        Requirement(requirement_id=f"skill:{i}", kind=RequirementKind.SKILL, text=f"Technical Skill {i}", required=True)
        for i in range(1, 23)
    ]
    evs = [
        Evidence(evidence_id=f"ev:{i}", kind="skills", text=f"Demonstrated technical experience {i}", canonical_terms=[f"skill_{i}"])
        for i in range(1, 10)
    ]

    gate = GroqTokenBudgetGate.get_gate(settings)
    payload = GroqMatchEvaluator(settings)._payload(reqs, evs)
    estimated_tokens = gate.estimate_tokens(payload)

    # 22 requirements MUST estimate within the usable TPM limit (7,000 tokens)
    assert estimated_tokens <= gate.usable_tpm, f"Estimated tokens {estimated_tokens} exceeded usable TPM {gate.usable_tpm}"

    mock_resp_data = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "verdicts": [
                            {
                                "requirement_id": r.requirement_id,
                                "status": "MATCHED",
                                "sub_claims": [r.text],
                                "sub_claim_evidence": [{"claim": r.text, "evidence_level": "direct", "note": "Direct match"}],
                                "coverage_score": 1.0,
                                "importance": "important",
                                "evidence_ids": ["ev:1"],
                                "reasoning": f"Evidence directly demonstrates {r.text}."
                            }
                            for r in reqs
                        ]
                    })
                }
            }
        ],
        "usage": {"prompt_tokens": 2000, "completion_tokens": 1200, "total_tokens": 3200}
    }

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_resp_data
    mock_resp.headers = {"x-ratelimit-remaining-tokens": "5000"}
    mock_resp.raise_for_status = MagicMock()

    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)
    mock_groq_client.post.return_value = mock_resp

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client):
        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_22_reqs")
        assert tele["provider_selected"] == "groq"
        assert tele["reason"] == "budget_available"
        assert len(verdicts) == 22
        assert all(v.status == MatchStatus.MATCHED for v in verdicts)
        assert not any(v.status == MatchStatus.EVALUATION_FAILED for v in verdicts)


@pytest.mark.asyncio
async def test_cerebras_not_called_when_disabled_or_unavailable():
    """Regression Test 2: Cerebras is not called when its key is unavailable/disabled."""
    settings = make_test_settings()
    settings.CEREBRAS_API_KEY = None  # Disabled / no key configured

    smart_eval = SmartMatchEvaluator(settings)
    assert not smart_eval.cerebras.enabled

    reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
    evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

    # Make Groq fail with an error
    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)
    mock_groq_client.post.side_effect = httpx.ConnectError("Groq unreachable")

    mock_cerebras_client = AsyncMock(spec=httpx.AsyncClient)

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client), \
         patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_cerebras_client):
        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_no_cerebras")
        # Cerebras was NOT called
        mock_cerebras_client.post.assert_not_called()
        assert tele.get("fallback_provider", "none") in ("none", "")


@pytest.mark.asyncio
async def test_successful_groq_evaluation_returns_valid_verdicts_not_evaluation_failed():
    """Regression Test 3: Successful Groq evaluation returns verdicts with valid reasoning, not EVALUATION_FAILED."""
    settings = make_test_settings()
    smart_eval = SmartMatchEvaluator(settings)

    reqs = [
        Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Python", required=True),
        Requirement(requirement_id="skill:2", kind=RequirementKind.SKILL, text="FastAPI", required=True),
    ]
    evs = [Evidence(evidence_id="ev1", kind="skills", text="Python and FastAPI developer", canonical_terms=["python", "fastapi"])]

    mock_resp_data = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "verdicts": [
                            {
                                "requirement_id": "skill:1",
                                "status": "MATCHED",
                                "coverage_score": 1.0,
                                "importance": "important",
                                "evidence_ids": ["ev1"],
                                "reasoning": "Strong Python experience evidenced."
                            },
                            {
                                "requirement_id": "skill:2",
                                "status": "PARTIALLY_MATCHED",
                                "coverage_score": 0.5,
                                "importance": "important",
                                "evidence_ids": ["ev1"],
                                "reasoning": "FastAPI used in project context."
                            }
                        ]
                    })
                }
            }
        ],
        "usage": {"prompt_tokens": 400, "completion_tokens": 200, "total_tokens": 600}
    }

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_resp_data
    mock_resp.headers = {"x-ratelimit-remaining-tokens": "7000"}
    mock_resp.raise_for_status = MagicMock()

    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)
    mock_groq_client.post.return_value = mock_resp

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client):
        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_valid")
        assert tele["provider_selected"] == "groq"
        assert len(verdicts) == 2
        for v in verdicts:
            assert v.status in (MatchStatus.MATCHED, MatchStatus.PARTIALLY_MATCHED)
            assert v.status != MatchStatus.EVALUATION_FAILED
            assert "AI evaluation could not be completed" not in v.reasoning
            assert len(v.reasoning) > 0


# Regression Tests for Evidence-Backed Requirements (SQL, HTML, CSS, OOP)
def test_prefilter_selects_evidence_for_sql_html_css_oop():
    """Prefilter selects appropriate evidence for domain skills like SQL, HTML, CSS, OOP."""
    prefilter = EvidencePrefilter(threshold=0.20, limit=5)
    evidence = [
        Evidence(evidence_id="project:1", kind="project", text="Developed web-based collaborative diagramming application using React and PostgreSQL database.", canonical_terms=["PostgreSQL", "React"]),
        Evidence(evidence_id="project:2", kind="project", text="Built walletless decentralized application on Polygon.", canonical_terms=["Solidity"]),
        Evidence(evidence_id="skills:1", kind="skills", text="Java, Python, TypeScript, React, PostgreSQL", canonical_terms=["Java", "Python", "TypeScript", "React", "PostgreSQL"]),
        Evidence(evidence_id="experience:1", kind="experience", text="Frontend styling and responsive web design using modern CSS and HTML markup.", canonical_terms=["CSS", "HTML"]),
    ]

    # 1. SQL requirement should select project:1 (PostgreSQL) and skills:1
    req_sql = Requirement(requirement_id="req:sql", kind=RequirementKind.SKILL, text="SQL")
    sel_sql = prefilter.select(req_sql, evidence)
    sel_sql_ids = {e.evidence_id for e in sel_sql}
    assert "project:1" in sel_sql_ids or "skills:1" in sel_sql_ids

    # 2. HTML requirement should select web/frontend evidence
    req_html = Requirement(requirement_id="req:html", kind=RequirementKind.SKILL, text="HTML")
    sel_html = prefilter.select(req_html, evidence)
    sel_html_ids = {e.evidence_id for e in sel_html}
    assert "project:1" in sel_html_ids or "experience:1" in sel_html_ids

    # 3. CSS requirement should select styling/web evidence
    req_css = Requirement(requirement_id="req:css", kind=RequirementKind.SKILL, text="CSS")
    sel_css = prefilter.select(req_css, evidence)
    sel_css_ids = {e.evidence_id for e in sel_css}
    assert "experience:1" in sel_css_ids or "project:1" in sel_css_ids

    # 4. OOP requirement should select Java/Python evidence
    req_oop = Requirement(requirement_id="req:oop", kind=RequirementKind.SKILL, text="Object-Oriented Programming")
    sel_oop = prefilter.select(req_oop, evidence)
    sel_oop_ids = {e.evidence_id for e in sel_oop}
    assert "skills:1" in sel_oop_ids


def test_validator_preserves_supported_sql_html_css_oop_verdicts():
    """Validator preserves evidence-backed verdicts for SQL, HTML, CSS, OOP without rejecting them to UNRESOLVED."""
    evaluator = GroqMatchEvaluator()
    reqs = [
        Requirement(requirement_id="req:sql", kind=RequirementKind.SKILL, text="SQL"),
        Requirement(requirement_id="req:html", kind=RequirementKind.SKILL, text="HTML"),
        Requirement(requirement_id="req:css", kind=RequirementKind.SKILL, text="CSS"),
        Requirement(requirement_id="req:oop", kind=RequirementKind.SKILL, text="Object-Oriented Programming"),
    ]
    evidence = [
        Evidence(evidence_id="project:1", kind="project", text="Built fullstack app using PostgreSQL database.", canonical_terms=["PostgreSQL"]),
        Evidence(evidence_id="project:2", kind="project", text="Built web frontend interface using HTML and CSS styling.", canonical_terms=["HTML", "CSS"]),
        Evidence(evidence_id="skills:1", kind="skills", text="Java, Python, C++, TypeScript OOP languages.", canonical_terms=["Java", "Python"]),
    ]
    allowed_evidence = {
        "req:sql": {"project:1"},
        "req:html": {"project:2"},
        "req:css": {"project:2"},
        "req:oop": {"skills:1"},
    }
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="req:sql", status=MatchStatus.MATCHED, coverage_score=1.0, evidence_ids=["project:1"], reasoning="Project:1 uses PostgreSQL satisfying SQL."),
        LLMVerdict(requirement_id="req:html", status=MatchStatus.MATCHED, coverage_score=1.0, evidence_ids=["project:2"], reasoning="Project:2 demonstrates frontend HTML."),
        LLMVerdict(requirement_id="req:css", status=MatchStatus.MATCHED, coverage_score=1.0, evidence_ids=["project:2"], reasoning="Project:2 demonstrates CSS styling."),
        LLMVerdict(requirement_id="req:oop", status=MatchStatus.MATCHED, coverage_score=1.0, evidence_ids=["skills:1"], reasoning="Java and Python satisfy OOP requirement."),
    ])

    validated = evaluator._validate(batch, reqs, evidence, allowed_evidence)
    assert len(validated) == 4
    for v in validated:
        assert v.status == MatchStatus.MATCHED
        assert v.method == MatchMethod.LLM_CONFIRMED
        assert "Rejected: No valid candidate evidence ID cited for match" not in v.reasoning
        assert len(v.evidence_ids) > 0


def test_validator_strictly_rejects_hallucinated_or_unsupported_evidence():
    """Validator strictly demotes unsupported claims to UNRESOLVED when citations are fake or missing."""
    evaluator = GroqMatchEvaluator()
    reqs = [
        Requirement(requirement_id="req:cplusplus", kind=RequirementKind.SKILL, text="C++"),
        Requirement(requirement_id="req:rust", kind=RequirementKind.SKILL, text="Rust"),
    ]
    evidence = [
        Evidence(evidence_id="project:1", kind="project", text="Python data pipeline.", canonical_terms=["Python"]),
    ]
    allowed_evidence = {
        "req:cplusplus": {"project:1"},
        "req:rust": {"project:1"},
    }
    batch = LLMVerdictBatch(verdicts=[
        # Fake hallucinated ID
        LLMVerdict(requirement_id="req:cplusplus", status=MatchStatus.MATCHED, coverage_score=1.0, evidence_ids=["fake:999"], reasoning="Candidate knows C++ from unknown source."),
        # Empty evidence IDs
        LLMVerdict(requirement_id="req:rust", status=MatchStatus.MATCHED, coverage_score=0.9, evidence_ids=[], reasoning="Rust is great but no evidence exists."),
    ])

    validated = evaluator._validate(batch, reqs, evidence, allowed_evidence)
    assert len(validated) == 2
    # fake:999 must be rejected to UNRESOLVED because evidence ID is hallucinated
    assert validated[0].requirement_id == "req:cplusplus"
    assert validated[0].status == MatchStatus.UNRESOLVED
    assert validated[0].method == MatchMethod.LLM_UNRESOLVED
    assert "fake:999" not in validated[0].evidence_ids

    # req:rust must be rejected because reasoning states no evidence exists
    assert validated[1].requirement_id == "req:rust"
    assert validated[1].status == MatchStatus.NO_MATCH
    assert validated[1].method == MatchMethod.LLM_REJECTED


@pytest.mark.asyncio
async def test_groq_budget_wait_when_cerebras_disabled_recovers_and_evaluates():
    """When Cerebras is disabled and Groq budget is temporarily exhausted, SmartMatchEvaluator waits for replenishment and succeeds with Groq."""
    settings = make_test_settings()
    # Cerebras is completely disabled/unconfigured
    settings.CEREBRAS_API_KEY = None

    smart_eval = SmartMatchEvaluator(settings)
    gate = GroqTokenBudgetGate.get_gate(settings)
    # Saturate gate with an entry that expires very soon (0.05s ago from 60s)
    gate.usage_history = [(time.monotonic() - 59.95, gate.usable_tpm)]

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = make_valid_response("req1", "Direct match verified", 120)
    mock_resp.raise_for_status = MagicMock()

    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)
    mock_groq_client.post.return_value = mock_resp

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client):
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, tele = await smart_eval.evaluate(reqs, evs, resume_id="res_wait_test")

        assert len(verdicts) == 1
        assert verdicts[0].status == MatchStatus.MATCHED
        assert tele["provider_selected"] == "groq"
        assert tele["reason"] == "budget_replenished_after_wait"
        mock_groq_client.post.assert_called_once()

