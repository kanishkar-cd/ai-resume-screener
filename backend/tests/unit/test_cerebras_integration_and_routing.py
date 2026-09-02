import json
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from app.schemas.matching import Evidence, MatchMethod, MatchStatus, Requirement, RequirementKind
from app.services.matching_service import (
    CerebrasMatchEvaluator,
    CerebrasTokenBudgetGate,
    GroqMatchEvaluator,
    GroqTokenBudgetGate,
    SmartMatchEvaluator,
)


@pytest.fixture(autouse=True)
def reset_gates():
    GroqTokenBudgetGate.reset_gate()
    CerebrasTokenBudgetGate.reset_gate()
    GroqMatchEvaluator._cache.clear()
    CerebrasMatchEvaluator._cache.clear()


@pytest.mark.asyncio
async def test_1_groq_capacity_available_routes_to_groq():
    settings = MagicMock(
        ENABLE_HYBRID_MATCHING=True,
        GROQ_API_KEY="mock_groq_key",
        GROQ_BASE_URL="https://api.groq.com/openai/v1",
        GROQ_MODEL="openai/gpt-oss-20b",
        GROQ_TIMEOUT_SECONDS=5.0,
        GROQ_TPM_LIMIT=8000,
        GROQ_TPM_SAFETY_MARGIN=0.125,
        CEREBRAS_API_KEY="mock_cerebras_key",
        CEREBRAS_BASE_URL="https://api.cerebras.ai/v1",
        CEREBRAS_MODEL="gpt-oss-120b",
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_CACHE_SIZE=100,
    )

    groq_eval = GroqMatchEvaluator(settings)
    cerebras_eval = CerebrasMatchEvaluator(settings)
    smart_eval = SmartMatchEvaluator(settings, groq_evaluator=groq_eval, cerebras_evaluator=cerebras_eval)

    groq_eval.evaluate_with_usage = AsyncMock(return_value=([
        MagicMock(requirement_id="req1", status=MatchStatus.MATCHED)
    ], {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}))

    cerebras_eval.evaluate_with_usage = AsyncMock()

    reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
    evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

    verdicts, tele = await smart_eval.evaluate(reqs, evs)

    assert len(verdicts) == 1
    assert tele["provider_selected"] == "groq"
    assert tele["actual_total_tokens"] == 120
    assert tele["fallback_reason"] == "none"
    groq_eval.evaluate_with_usage.assert_called_once()
    cerebras_eval.evaluate_with_usage.assert_not_called()


@pytest.mark.asyncio
async def test_2_groq_capacity_insufficient_routes_immediately_to_cerebras():
    settings = MagicMock(
        ENABLE_HYBRID_MATCHING=True,
        GROQ_API_KEY="mock_groq_key",
        GROQ_BASE_URL="https://api.groq.com/openai/v1",
        GROQ_MODEL="openai/gpt-oss-20b",
        GROQ_TIMEOUT_SECONDS=5.0,
        GROQ_TPM_LIMIT=8000,
        GROQ_TPM_SAFETY_MARGIN=0.125,
        CEREBRAS_API_KEY="mock_cerebras_key",
        CEREBRAS_BASE_URL="https://api.cerebras.ai/v1",
        CEREBRAS_MODEL="gpt-oss-120b",
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_CACHE_SIZE=100,
    )

    groq_eval = GroqMatchEvaluator(settings)
    cerebras_eval = CerebrasMatchEvaluator(settings)
    smart_eval = SmartMatchEvaluator(settings, groq_evaluator=groq_eval, cerebras_evaluator=cerebras_eval)

    groq_eval.evaluate_with_usage = AsyncMock(side_effect=RuntimeError("Groq timeout or unavailable"))
    cerebras_eval.evaluate_with_usage = AsyncMock(return_value=([
        MagicMock(requirement_id="req1", status=MatchStatus.MATCHED)
    ], {"prompt_tokens": 150, "completion_tokens": 30, "total_tokens": 180}))

    reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
    evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

    verdicts, tele = await smart_eval.evaluate(reqs, evs)

    assert len(verdicts) == 1
    assert tele["provider_selected"] == "cerebras"
    assert "groq_error" in tele["fallback_reason"]
    assert tele["actual_total_tokens"] == 180
    groq_eval.evaluate_with_usage.assert_called_once()
    cerebras_eval.evaluate_with_usage.assert_called_once()



@pytest.mark.asyncio
async def test_3_cerebras_successful_response_parsing_and_token_telemetry():
    settings = MagicMock(
        ENABLE_HYBRID_MATCHING=True,
        GROQ_API_KEY="mock_groq_key",
        CEREBRAS_API_KEY="mock_cerebras_key",
        CEREBRAS_BASE_URL="https://api.cerebras.ai/v1",
        CEREBRAS_MODEL="gpt-oss-120b",
        CEREBRAS_TIMEOUT_SECONDS=5.0,
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_CACHE_SIZE=100,
    )

    evaluator = CerebrasMatchEvaluator(settings)

    mock_resp_json = {
        "id": "chatcmpl-123",
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "verdicts": [
                            {
                                "requirement_id": "req1",
                                "status": "MATCHED",
                                "confidence": 0.95,
                                "evidence_ids": ["ev1"],
                                "reasoning": "Direct Python skill match."
                            }
                        ]
                    })
                }
            }
        ],
        "usage": {
            "prompt_tokens": 210,
            "completion_tokens": 45,
            "total_tokens": 255
        }
    }

    mock_http_response = MagicMock(spec=httpx.Response)
    mock_http_response.status_code = 200
    mock_http_response.json.return_value = mock_resp_json
    mock_http_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_http_response

    with patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_client):
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, usage = await evaluator.evaluate_with_usage(reqs, evs)

        assert len(verdicts) == 1
        assert verdicts[0].requirement_id == "req1"
        assert verdicts[0].status == MatchStatus.MATCHED
        assert verdicts[0].evidence_ids == ["ev1"]
        assert usage["prompt_tokens"] == 210
        assert usage["completion_tokens"] == 45
        assert usage["total_tokens"] == 255


@pytest.mark.asyncio
async def test_4_cerebras_404_model_not_found_handled_safely():
    settings = MagicMock(
        ENABLE_HYBRID_MATCHING=True,
        CEREBRAS_API_KEY="mock_cerebras_key",
        CEREBRAS_BASE_URL="https://api.cerebras.ai/v1",
        CEREBRAS_MODEL="llama3.1-70b",
        CEREBRAS_TIMEOUT_SECONDS=5.0,
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_CACHE_SIZE=100,
    )

    evaluator = CerebrasMatchEvaluator(settings)

    mock_http_response = MagicMock(spec=httpx.Response)
    mock_http_response.status_code = 404
    mock_http_response.text = '{"message": "Model does not exist", "code": "model_not_found"}'
    
    exc = httpx.HTTPStatusError("404 Not Found", request=MagicMock(), response=mock_http_response)
    mock_http_response.raise_for_status.side_effect = exc

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_http_response

    with patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_client):
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, usage = await evaluator.evaluate_with_usage(reqs, evs)

        assert verdicts == []
        assert usage["prompt_tokens"] == 0
        assert usage["completion_tokens"] == 0
        assert usage["total_tokens"] == 0


@pytest.mark.asyncio
async def test_5_cerebras_401_authentication_failure_handled_distinctly():
    settings = MagicMock(
        ENABLE_HYBRID_MATCHING=True,
        CEREBRAS_API_KEY="invalid_key",
        CEREBRAS_BASE_URL="https://api.cerebras.ai/v1",
        CEREBRAS_MODEL="gpt-oss-120b",
        CEREBRAS_TIMEOUT_SECONDS=5.0,
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_CACHE_SIZE=100,
    )

    evaluator = CerebrasMatchEvaluator(settings)

    mock_http_response = MagicMock(spec=httpx.Response)
    mock_http_response.status_code = 401
    mock_http_response.text = '{"message": "Invalid API key"}'
    
    exc = httpx.HTTPStatusError("401 Unauthorized", request=MagicMock(), response=mock_http_response)
    mock_http_response.raise_for_status.side_effect = exc

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_http_response

    with patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_client):
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, usage = await evaluator.evaluate_with_usage(reqs, evs)

        assert verdicts == []
        assert usage["total_tokens"] == 0


@pytest.mark.asyncio
async def test_6_cerebras_429_rate_limit_handled_safely():
    settings = MagicMock(
        ENABLE_HYBRID_MATCHING=True,
        CEREBRAS_API_KEY="mock_key",
        CEREBRAS_BASE_URL="https://api.cerebras.ai/v1",
        CEREBRAS_MODEL="gpt-oss-120b",
        CEREBRAS_TIMEOUT_SECONDS=5.0,
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_CACHE_SIZE=100,
    )

    evaluator = CerebrasMatchEvaluator(settings)

    mock_http_response = MagicMock(spec=httpx.Response)
    mock_http_response.status_code = 429
    mock_http_response.text = '{"message": "Rate limit exceeded"}'
    
    exc = httpx.HTTPStatusError("429 Rate Limit", request=MagicMock(), response=mock_http_response)
    mock_http_response.raise_for_status.side_effect = exc

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_http_response

    with patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_client):
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, usage = await evaluator.evaluate_with_usage(reqs, evs)

        assert verdicts == []
        assert usage["total_tokens"] == 0


@pytest.mark.asyncio
async def test_7_cerebras_malformed_json_response_rejected():
    settings = MagicMock(
        ENABLE_HYBRID_MATCHING=True,
        CEREBRAS_API_KEY="mock_key",
        CEREBRAS_BASE_URL="https://api.cerebras.ai/v1",
        CEREBRAS_MODEL="gpt-oss-120b",
        CEREBRAS_TIMEOUT_SECONDS=5.0,
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_CACHE_SIZE=100,
    )

    evaluator = CerebrasMatchEvaluator(settings)

    mock_resp_json = {
        "choices": [{"message": {"content": "INVALID NON-JSON TEXT"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
    }

    mock_http_response = MagicMock(spec=httpx.Response)
    mock_http_response.status_code = 200
    mock_http_response.json.return_value = mock_resp_json

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_http_response

    with patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_client):
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, usage = await evaluator.evaluate_with_usage(reqs, evs)

        assert verdicts == []
        assert usage["total_tokens"] == 0


@pytest.mark.asyncio
async def test_8_provider_fallback_end_to_end():
    settings = MagicMock(
        ENABLE_HYBRID_MATCHING=True,
        GROQ_API_KEY="mock_groq_key",
        GROQ_BASE_URL="https://api.groq.com/openai/v1",
        GROQ_MODEL="openai/gpt-oss-20b",
        GROQ_TIMEOUT_SECONDS=5.0,
        GROQ_TPM_LIMIT=8000,
        GROQ_TPM_SAFETY_MARGIN=0.125,
        CEREBRAS_API_KEY="mock_cerebras_key",
        CEREBRAS_BASE_URL="https://api.cerebras.ai/v1",
        CEREBRAS_MODEL="gpt-oss-120b",
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_CACHE_SIZE=100,
    )

    smart_eval = SmartMatchEvaluator(settings)

    mock_cerebras_json = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "verdicts": [
                            {
                                "requirement_id": "req1",
                                "status": "MATCHED",
                                "confidence": 0.92,
                                "evidence_ids": ["ev1"],
                                "reasoning": "Fallback Cerebras verdict matched Python skill."
                            }
                        ]
                    })
                }
            }
        ],
        "usage": {"prompt_tokens": 180, "completion_tokens": 35, "total_tokens": 215}
    }

    mock_http_response = MagicMock(spec=httpx.Response)
    mock_http_response.status_code = 200
    mock_http_response.json.return_value = mock_cerebras_json

    mock_cerebras_client = AsyncMock(spec=httpx.AsyncClient)
    mock_cerebras_client.post.return_value = mock_http_response

    # Mock Groq client to fail with 500 error
    mock_groq_response = MagicMock(spec=httpx.Response)
    mock_groq_response.status_code = 500
    mock_groq_response.text = '{"error": "Internal server error"}'
    mock_groq_response.raise_for_status.side_effect = httpx.HTTPStatusError("500 Server Error", request=MagicMock(), response=mock_groq_response)

    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)
    mock_groq_client.post.return_value = mock_groq_response

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client), \
         patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_cerebras_client):
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, tele = await smart_eval.evaluate(reqs, evs)

        assert len(verdicts) == 1
        assert verdicts[0].requirement_id == "req1"
        assert verdicts[0].status == MatchStatus.MATCHED
        assert tele["provider_selected"] == "cerebras"
        assert "groq_error" in tele["fallback_reason"]
        assert tele["actual_total_tokens"] == 215


@pytest.mark.asyncio
async def test_9_no_false_success_when_cerebras_fails():
    settings = MagicMock(
        ENABLE_HYBRID_MATCHING=True,
        GROQ_API_KEY="mock_groq_key",
        GROQ_BASE_URL="https://api.groq.com/openai/v1",
        GROQ_MODEL="openai/gpt-oss-20b",
        GROQ_TIMEOUT_SECONDS=5.0,
        GROQ_TPM_LIMIT=8000,
        GROQ_TPM_SAFETY_MARGIN=0.125,
        CEREBRAS_API_KEY="mock_cerebras_key",
        CEREBRAS_BASE_URL="https://api.cerebras.ai/v1",
        CEREBRAS_MODEL="gpt-oss-120b",
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_CACHE_SIZE=100,
    )

    smart_eval = SmartMatchEvaluator(settings)

    mock_http_response = MagicMock(spec=httpx.Response)
    mock_http_response.status_code = 402
    mock_http_response.text = '{"message": "Payment required"}'
    
    exc = httpx.HTTPStatusError("402 Payment Required", request=MagicMock(), response=mock_http_response)
    mock_http_response.raise_for_status.side_effect = exc

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_http_response

    mock_groq_response = MagicMock(spec=httpx.Response)
    mock_groq_response.status_code = 500
    mock_groq_response.raise_for_status.side_effect = httpx.HTTPStatusError("500 Server Error", request=MagicMock(), response=mock_groq_response)
    mock_groq_client = AsyncMock(spec=httpx.AsyncClient)
    mock_groq_client.post.return_value = mock_groq_response

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_groq_client), \
         patch.object(CerebrasMatchEvaluator, "_get_client", return_value=mock_client):
        reqs = [Requirement(requirement_id="req1", kind=RequirementKind.SKILL, text="Python", required=True)]
        evs = [Evidence(evidence_id="ev1", kind="skills", text="Python", canonical_terms=["python"])]

        verdicts, tele = await smart_eval.evaluate(reqs, evs)

        assert verdicts == []
        assert tele["provider_selected"] == "cerebras"
        assert tele["actual_total_tokens"] == 0
        assert "groq_error" in tele["fallback_reason"]

