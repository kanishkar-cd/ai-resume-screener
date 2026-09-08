import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch
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
from app.services.llm.batch_pipeline import (
    GroqBatchExecutor,
    PostDeterministicPipeline,
    ResumeBatchContext,
)
from app.services.llm.key_pool import GroqKeyPoolManager, GroqKeyStatus
from app.services.llm.openrouter_client import OpenRouterBatchExecutor


from app.services.matching_service import ProviderCircuitBreaker


@pytest.fixture(autouse=True)
def reset_breaker():
    ProviderCircuitBreaker.reset_breaker()
    yield
    ProviderCircuitBreaker.reset_breaker()


def _sample_context(resume_id: str = "res_1") -> ResumeBatchContext:
    req = Requirement(requirement_id="req_python", kind=RequirementKind.SKILL, text="Python programming", required=True)
    ev = Evidence(evidence_id=f"{resume_id}:ev_py", kind="skills", text="5 years Python backend development")
    return ResumeBatchContext(
        resume_id=resume_id,
        requirements=[req],
        candidate_evidence=[ev],
        allowed_evidence={"req_python": {f"{resume_id}:ev_py"}},
    )


def _mock_success_response(resume_id: str, req_id: str = "req_python", ev_id: str | None = None) -> str:
    eid = ev_id or f"{resume_id}:ev_py"
    return json.dumps({
        "results": [
            {
                "resume_id": resume_id,
                "verdicts": [
                    {
                        "requirement_id": req_id,
                        "status": "MATCHED",
                        "coverage_score": 1.0,
                        "evidence_ids": [eid],
                        "reasoning": "Direct match for Python skill.",
                    }
                ],
            }
        ]
    })


@pytest.mark.asyncio
async def test_fallback_1_groq_succeeds_openrouter_not_called():
    """Test 1: Normal request where Groq succeeds -> OpenRouter must NOT be called."""
    settings = Settings(
        GROQ_API_KEY_1="gsk_key_1",
        OPENROUTER_API_KEY="sk-or-test-key",
        OPENROUTER_ENABLED=True,
    )
    pool = GroqKeyPoolManager(settings)
    openrouter_exec = OpenRouterBatchExecutor(settings)
    openrouter_mock = AsyncMock()
    openrouter_exec.execute_batch_with_retry = openrouter_mock

    executor = GroqBatchExecutor(
        settings=settings,
        key_pool=pool,
        openrouter_executor=openrouter_exec,
        max_retries=1,
    )

    ctx = _sample_context("res_1")
    groq_resp = _mock_success_response("res_1")

    with patch.object(executor, "_call_groq_api", new_callable=AsyncMock) as mock_groq:
        mock_groq.return_value = groq_resp
        results = await executor.execute_batch_with_retry([ctx])

    assert "res_1" in results
    assert len(results["res_1"]) == 1
    assert results["res_1"][0].status == MatchStatus.MATCHED
    assert results["res_1"][0].method == MatchMethod.LLM_CONFIRMED

    # OpenRouter was never called
    openrouter_mock.assert_not_called()
    assert mock_groq.call_count == 1


@pytest.mark.asyncio
async def test_fallback_2_groq_key1_fails_key2_succeeds():
    """Test 2: Groq Key 1 fails (401), Key 2 succeeds -> OpenRouter not called."""
    settings = Settings(
        GROQ_API_KEY_1="gsk_key_1",
        GROQ_API_KEY_2="gsk_key_2",
        OPENROUTER_API_KEY="sk-or-test-key",
        OPENROUTER_ENABLED=True,
    )
    pool = GroqKeyPoolManager(settings)
    openrouter_exec = OpenRouterBatchExecutor(settings)
    openrouter_mock = AsyncMock()
    openrouter_exec.execute_batch_with_retry = openrouter_mock

    executor = GroqBatchExecutor(
        settings=settings,
        key_pool=pool,
        openrouter_executor=openrouter_exec,
        max_retries=1,
    )

    ctx = _sample_context("res_1")
    call_count = 0

    async def mock_call_groq(payload, timeout, api_key=None):
        nonlocal call_count
        call_count += 1
        if api_key == "gsk_key_1":
            import httpx
            req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
            resp = httpx.Response(status_code=401, request=req)
            raise httpx.HTTPStatusError("Auth failed", request=req, response=resp)
        return _mock_success_response("res_1")

    with patch.object(executor, "_call_groq_api", side_effect=mock_call_groq):
        results = await executor.execute_batch_with_retry([ctx])

    assert "res_1" in results
    assert results["res_1"][0].status == MatchStatus.MATCHED
    # OpenRouter was never called
    openrouter_mock.assert_not_called()
    assert call_count == 2
    key1_entry = next(e for e in pool._entries if e.key_id == "groq_key_1")
    assert key1_entry.status == GroqKeyStatus.DISABLED


@pytest.mark.asyncio
async def test_fallback_3_all_groq_keys_exhausted_openrouter_succeeds():
    """Test 3: All Groq keys exhausted/fail -> OpenRouter fallback is called and succeeds."""
    settings = Settings(
        GROQ_API_KEY_1="gsk_key_1",
        GROQ_API_KEY_2="gsk_key_2",
        OPENROUTER_API_KEY="sk-or-test-key",
        OPENROUTER_ENABLED=True,
    )
    pool = GroqKeyPoolManager(settings)
    openrouter_exec = OpenRouterBatchExecutor(settings)

    executor = GroqBatchExecutor(
        settings=settings,
        key_pool=pool,
        openrouter_executor=openrouter_exec,
        max_retries=1,
    )

    ctx = _sample_context("res_1")
    openrouter_resp = _mock_success_response("res_1")

    # Groq fails completely
    async def mock_groq_fail(payload, timeout, api_key=None):
        import httpx
        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        resp = httpx.Response(status_code=500, request=req)
        raise httpx.HTTPStatusError("Groq 500", request=req, response=resp)

    with patch.object(executor, "_call_groq_api", side_effect=mock_groq_fail), \
         patch.object(openrouter_exec, "_call_openrouter_api", new_callable=AsyncMock) as mock_or_call:
        mock_or_call.return_value = openrouter_resp
        results = await executor.execute_batch_with_retry([ctx])

    assert "res_1" in results
    assert results["res_1"][0].status == MatchStatus.MATCHED
    assert results["res_1"][0].method == MatchMethod.LLM_CONFIRMED
    assert mock_or_call.call_count == 1


@pytest.mark.asyncio
async def test_fallback_4_all_groq_and_openrouter_fail():
    """Test 4: Both Groq and OpenRouter fail -> graceful EVALUATION_FAILED."""
    settings = Settings(
        GROQ_API_KEY_1="gsk_key_1",
        OPENROUTER_API_KEY="sk-or-test-key",
        OPENROUTER_ENABLED=True,
    )
    pool = GroqKeyPoolManager(settings)
    openrouter_exec = OpenRouterBatchExecutor(settings)

    executor = GroqBatchExecutor(
        settings=settings,
        key_pool=pool,
        openrouter_executor=openrouter_exec,
        max_retries=1,
    )

    ctx = _sample_context("res_1")

    async def mock_groq_fail(payload, timeout, api_key=None):
        import httpx
        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        resp = httpx.Response(status_code=500, request=req)
        raise httpx.HTTPStatusError("Groq 500", request=req, response=resp)

    async def mock_or_fail(payload, timeout):
        import httpx
        req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        resp = httpx.Response(status_code=503, request=req)
        raise httpx.HTTPStatusError("OpenRouter 503", request=req, response=resp)

    with patch.object(executor, "_call_groq_api", side_effect=mock_groq_fail), \
         patch.object(openrouter_exec, "_call_openrouter_api", side_effect=mock_or_fail):
        results = await executor.execute_batch_with_retry([ctx])

    assert "res_1" in results
    assert results["res_1"][0].status == MatchStatus.EVALUATION_FAILED
    assert results["res_1"][0].method == MatchMethod.EVALUATION_FAILED


@pytest.mark.asyncio
async def test_fallback_5_openrouter_disabled():
    """Test 5: OPENROUTER_ENABLED=False -> OpenRouter never called even when Groq fails."""
    settings = Settings(
        GROQ_API_KEY_1="gsk_key_1",
        OPENROUTER_API_KEY="sk-or-test-key",
        OPENROUTER_ENABLED=False,
    )
    pool = GroqKeyPoolManager(settings)
    openrouter_exec = OpenRouterBatchExecutor(settings)
    openrouter_mock = AsyncMock()
    openrouter_exec.execute_batch_with_retry = openrouter_mock

    executor = GroqBatchExecutor(
        settings=settings,
        key_pool=pool,
        openrouter_executor=openrouter_exec,
        max_retries=1,
    )

    ctx = _sample_context("res_1")

    async def mock_groq_fail(payload, timeout, api_key=None):
        import httpx
        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        resp = httpx.Response(status_code=500, request=req)
        raise httpx.HTTPStatusError("Groq 500", request=req, response=resp)

    with patch.object(executor, "_call_groq_api", side_effect=mock_groq_fail):
        results = await executor.execute_batch_with_retry([ctx])

    assert "res_1" in results
    assert results["res_1"][0].status == MatchStatus.EVALUATION_FAILED
    openrouter_mock.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_6_openrouter_key_missing():
    """Test 6: OPENROUTER_API_KEY missing -> OpenRouter is disabled and returns EVALUATION_FAILED."""
    settings = Settings(
        GROQ_API_KEY_1="gsk_key_1",
        OPENROUTER_API_KEY=None,
        OPEN_ROUTER=None,
        Open_router=None,
        open_router=None,
        OPENROUTER_ENABLED=True,
    )
    pool = GroqKeyPoolManager(settings)
    openrouter_exec = OpenRouterBatchExecutor(settings)
    assert not openrouter_exec.enabled

    executor = GroqBatchExecutor(
        settings=settings,
        key_pool=pool,
        openrouter_executor=openrouter_exec,
        max_retries=1,
    )

    ctx = _sample_context("res_1")

    async def mock_groq_fail(payload, timeout, api_key=None):
        import httpx
        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        resp = httpx.Response(status_code=500, request=req)
        raise httpx.HTTPStatusError("Groq 500", request=req, response=resp)

    with patch.object(executor, "_call_groq_api", side_effect=mock_groq_fail):
        results = await executor.execute_batch_with_retry([ctx])

    assert "res_1" in results
    assert results["res_1"][0].status == MatchStatus.EVALUATION_FAILED


@pytest.mark.asyncio
async def test_fallback_7_partial_batch_failure_isolation():
    """Test 7: 3 resumes (A, B, C); A & B succeed on Groq, C fails -> ONLY C is sent to OpenRouter."""
    settings = Settings(
        GROQ_API_KEY_1="gsk_key_1",
        OPENROUTER_API_KEY="sk-or-test-key",
        OPENROUTER_ENABLED=True,
    )
    pool = GroqKeyPoolManager(settings)
    openrouter_exec = OpenRouterBatchExecutor(settings)

    executor = GroqBatchExecutor(
        settings=settings,
        key_pool=pool,
        openrouter_executor=openrouter_exec,
        max_retries=0,
    )

    ctx_a = _sample_context("res_A")
    ctx_b = _sample_context("res_B")
    ctx_c = _sample_context("res_C")

    # Groq returns A and B only, omitting C
    groq_resp = json.dumps({
        "results": [
            {
                "resume_id": "res_A",
                "verdicts": [{"requirement_id": "req_python", "status": "MATCHED", "coverage_score": 1.0, "evidence_ids": ["res_A:ev_py"]}],
            },
            {
                "resume_id": "res_B",
                "verdicts": [{"requirement_id": "req_python", "status": "MATCHED", "coverage_score": 1.0, "evidence_ids": ["res_B:ev_py"]}],
            },
        ]
    })

    openrouter_resp = json.dumps({
        "results": [
            {
                "resume_id": "res_C",
                "verdicts": [{"requirement_id": "req_python", "status": "MATCHED", "coverage_score": 1.0, "evidence_ids": ["res_C:ev_py"]}],
            }
        ]
    })

    with patch.object(executor, "_call_groq_api", new_callable=AsyncMock) as mock_groq, \
         patch.object(openrouter_exec, "execute_batch_with_retry", wraps=openrouter_exec.execute_batch_with_retry) as spy_or, \
         patch.object(openrouter_exec, "_call_openrouter_api", new_callable=AsyncMock) as mock_or_call:

        mock_groq.return_value = groq_resp
        mock_or_call.return_value = openrouter_resp

        results = await executor.execute_batch_with_retry([ctx_a, ctx_b, ctx_c])

    assert len(results) == 3
    assert results["res_A"][0].status == MatchStatus.MATCHED
    assert results["res_B"][0].status == MatchStatus.MATCHED
    assert results["res_C"][0].status == MatchStatus.MATCHED

    # Verify OpenRouter was called with ONLY res_C
    spy_or.assert_called_once()
    called_batch = spy_or.call_args[0][0]
    assert len(called_batch) == 1
    assert called_batch[0].resume_id == "res_C"


@pytest.mark.asyncio
async def test_fallback_8_openrouter_response_uses_same_validation():
    """Test 8: OpenRouter response passes through identical anti-hallucination validation."""
    settings = Settings(
        GROQ_API_KEY_1="gsk_key_1",
        OPENROUTER_API_KEY="sk-or-test-key",
        OPENROUTER_ENABLED=True,
    )
    openrouter_exec = OpenRouterBatchExecutor(settings)

    ctx = _sample_context("res_1")

    # Hallucinated evidence ID "foreign_doc:ev_999" not in candidate's allowed evidence
    hallucinated_resp = json.dumps({
        "results": [
            {
                "resume_id": "res_1",
                "verdicts": [
                    {
                        "requirement_id": "req_python",
                        "status": "MATCHED",
                        "coverage_score": 1.0,
                        "evidence_ids": ["foreign_doc:ev_999"],
                        "reasoning": "Hallucinated claim from foreign document",
                    }
                ],
            }
        ]
    })

    with patch.object(openrouter_exec, "_call_openrouter_api", new_callable=AsyncMock) as mock_or_call:
        mock_or_call.return_value = hallucinated_resp
        results = await openrouter_exec.execute_batch_with_retry([ctx])

    assert "res_1" in results
    verdict = results["res_1"][0]
    # Evidence must be rejected and status converted to NO_MATCH / LLM_REJECTED
    assert verdict.status == MatchStatus.NO_MATCH
    assert verdict.method == MatchMethod.LLM_REJECTED
    assert "(Rejected: No valid candidate evidence cited)" in verdict.reasoning


@pytest.mark.asyncio
async def test_fallback_9_openrouter_success_in_pipeline():
    """Test 9: Full PostDeterministicPipeline uses OpenRouter fallback seamlessly."""
    settings = Settings(
        GROQ_API_KEY_1="gsk_key_1",
        OPENROUTER_API_KEY="sk-or-test-key",
        OPENROUTER_ENABLED=True,
    )
    openrouter_exec = OpenRouterBatchExecutor(settings)
    pipeline = PostDeterministicPipeline(settings=settings, openrouter_executor=openrouter_exec)

    ctx = _sample_context("res_1")

    async def mock_groq_fail(payload, timeout, api_key=None):
        import httpx
        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        resp = httpx.Response(status_code=429, request=req)
        raise httpx.HTTPStatusError("Groq 429", request=req, response=resp)

    openrouter_resp = _mock_success_response("res_1")

    with patch.object(pipeline.executor, "_call_groq_api", side_effect=mock_groq_fail), \
         patch.object(openrouter_exec, "_call_openrouter_api", new_callable=AsyncMock) as mock_or_call:
        mock_or_call.return_value = openrouter_resp
        results = await pipeline.execute_parallel([ctx], batch_size=3)

    assert "res_1" in results
    assert results["res_1"][0].status == MatchStatus.MATCHED


@pytest.mark.asyncio
async def test_fallback_10_no_infinite_provider_loop():
    """Test 10: Groq failure -> OpenRouter failure terminates cleanly without looping."""
    settings = Settings(
        GROQ_API_KEY_1="gsk_key_1",
        OPENROUTER_API_KEY="sk-or-test-key",
        OPENROUTER_ENABLED=True,
        OPENROUTER_MAX_RETRIES=1,
    )
    pool = GroqKeyPoolManager(settings)
    openrouter_exec = OpenRouterBatchExecutor(settings, max_retries=1)

    executor = GroqBatchExecutor(
        settings=settings,
        key_pool=pool,
        openrouter_executor=openrouter_exec,
        max_retries=1,
    )

    ctx = _sample_context("res_1")
    groq_calls = 0
    or_calls = 0

    async def mock_groq_fail(payload, timeout, api_key=None):
        nonlocal groq_calls
        groq_calls += 1
        raise RuntimeError("Groq error")

    async def mock_or_fail(payload, timeout):
        nonlocal or_calls
        or_calls += 1
        raise RuntimeError("OpenRouter error")

    with patch.object(executor, "_call_groq_api", side_effect=mock_groq_fail), \
         patch.object(openrouter_exec, "_call_openrouter_api", side_effect=mock_or_fail):
        results = await executor.execute_batch_with_retry([ctx])

    assert "res_1" in results
    assert results["res_1"][0].status == MatchStatus.EVALUATION_FAILED
    # Max 2 Groq attempts (1 initial + 1 retry) and max 2 OR attempts (1 initial + 1 retry)
    assert groq_calls <= 2
    assert or_calls <= 2


@pytest.mark.asyncio
async def test_fallback_11_secrets_never_appear_in_logs(caplog):
    """Test 11: Real or fake secret keys never appear in log output."""
    fake_groq_key = "gsk_SUPER_SECRET_GROQ_KEY_12345"
    fake_or_key = "sk-or-v1-SUPER_SECRET_OPENROUTER_KEY_67890"

    settings = Settings(
        GROQ_API_KEY_1=fake_groq_key,
        OPENROUTER_API_KEY=fake_or_key,
        OPENROUTER_ENABLED=True,
    )
    pool = GroqKeyPoolManager(settings)
    openrouter_exec = OpenRouterBatchExecutor(settings)

    executor = GroqBatchExecutor(
        settings=settings,
        key_pool=pool,
        openrouter_executor=openrouter_exec,
        max_retries=0,
    )

    ctx = _sample_context("res_1")

    with caplog.at_level(logging.DEBUG):
        with patch.object(executor, "_call_groq_api", side_effect=RuntimeError("Test error on Groq")), \
             patch.object(openrouter_exec, "_call_openrouter_api", side_effect=RuntimeError("Test error on OR")):
            await executor.execute_batch_with_retry([ctx])

    for record in caplog.records:
        msg = str(record.getMessage())
        assert fake_groq_key not in msg, f"Leaked Groq key in log: {msg}"
        assert fake_or_key not in msg, f"Leaked OpenRouter key in log: {msg}"
