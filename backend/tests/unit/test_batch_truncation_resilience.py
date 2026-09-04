import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from app.core.config import get_settings
from app.schemas.matching import Evidence, MatchStatus, MatchVerdict, Requirement, RequirementKind
from app.services.matching_service import (
    CerebrasMatchEvaluator,
    GroqMatchEvaluator,
    GroqTokenBudgetGate,
    ProviderCircuitBreaker,
    SmartMatchEvaluator,
    _parse_llm_batch_response,
)


@pytest.fixture(autouse=True)
def reset_state():
    ProviderCircuitBreaker.reset_breaker()
    GroqTokenBudgetGate.reset_gate()
    GroqMatchEvaluator._cache.clear()
    CerebrasMatchEvaluator._cache.clear()


def make_test_settings():
    return MagicMock(
        ENABLE_HYBRID_MATCHING=True,
        GROQ_API_KEY="mock_groq_key",
        GROQ_BASE_URL="https://api.groq.com/openai/v1",
        GROQ_MODEL="openai/gpt-oss-20b",
        GROQ_TIMEOUT_SECONDS=5.0,
        GROQ_TPM_LIMIT=80000,
        GROQ_TPM_SAFETY_MARGIN=0.10,
        GROQ_MAX_RETRIES=1,
        GROQ_MAX_COMPLETION_TOKENS=4096,
        CEREBRAS_API_KEY="mock_cerebras_key",
        CEREBRAS_BASE_URL="https://api.cerebras.ai/v1",
        CEREBRAS_MODEL="gpt-oss-120b",
        CEREBRAS_TIMEOUT_SECONDS=5.0,
        CEREBRAS_TPM_LIMIT=60000,
        CEREBRAS_TPM_SAFETY_MARGIN=0.10,
        CEREBRAS_MAX_RETRIES=1,
        CEREBRAS_MAX_COMPLETION_TOKENS=4096,
        LLM_BATCH_THROTTLE_SECONDS=0.0,
        LLM_BATCH_CHUNK_SIZE=8,
        PROVIDER_CIRCUIT_BREAKER_COOLDOWN_SECONDS=60.0,
        PROVIDER_CIRCUIT_BREAKER_MAX_FAILURES=2,
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_CACHE_SIZE=100,
    )


def make_verdict_item(req_id: str, coverage: float = 1.0) -> dict:
    return {
        "requirement_id": req_id,
        "sub_claims": [f"claim for {req_id}"],
        "sub_claim_evidence": [
            {"claim": f"claim for {req_id}", "evidence_level": "direct", "note": "Demonstrated"}
        ],
        "coverage_score": coverage,
        "importance": "critical",
        "evidence_ids": ["ev1"],
        "reasoning": f"Evidence directly demonstrates {req_id}",
    }


def test_truncated_json_partial_recovery():
    """Test that an abruptly truncated JSON stream can recover all completed verdict items."""
    reqs = [
        Requirement(requirement_id="req_1", kind=RequirementKind.SKILL, text="Python", required=True),
        Requirement(requirement_id="req_2", kind=RequirementKind.SKILL, text="FastAPI", required=True),
        Requirement(requirement_id="req_3", kind=RequirementKind.RESPONSIBILITY, text="Lead architecture", required=True),
    ]

    # JSON truncated mid-stream in item 3
    truncated_raw = (
        '{"verdicts": ['
        + json.dumps(make_verdict_item("req_1"))
        + ", "
        + json.dumps(make_verdict_item("req_2"))
        + ', {"requirement_id": "req_3", "sub_claims": ["Lead arch'
    )

    batch = _parse_llm_batch_response(truncated_raw, reqs, finish_reason="length")
    assert len(batch.verdicts) == 2
    assert batch.verdicts[0].requirement_id == "req_1"
    assert batch.verdicts[1].requirement_id == "req_2"


@pytest.mark.asyncio
async def test_large_requirement_batch_chunking():
    """Test that a large batch of 16 requirements is automatically split into chunks of 8."""
    settings = make_test_settings()
    settings.LLM_BATCH_CHUNK_SIZE = 8

    reqs = [
        Requirement(requirement_id=f"req_{i}", kind=RequirementKind.SKILL if i < 10 else RequirementKind.RESPONSIBILITY, text=f"Skill/Duty {i}", required=True)
        for i in range(1, 17)
    ]
    evs = [Evidence(evidence_id="ev1", kind="skills", text="Skill 1", canonical_terms=["skill"])]

    evaluator = GroqMatchEvaluator(settings)

    call_count = 0

    async def mock_post(url, headers=None, json=None, timeout=None):
        nonlocal call_count
        call_count += 1
        chunk_reqs = json["messages"][1]["content"]
        chunk_data = __import__("json").loads(chunk_reqs)["requirements"]
        verdicts = [make_verdict_item(r["requirement_id"]) for r in chunk_data]

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"finish_reason": "stop", "message": {"content": __import__("json").dumps({"verdicts": verdicts})}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 300, "total_tokens": 500},
        }
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        verdicts, usage = await evaluator.evaluate_with_usage(reqs, evs)

        # 16 items / chunk size 8 = exactly 2 LLM calls
        assert call_count == 2
        assert len(verdicts) == 16
        verdict_ids = {v.requirement_id for v in verdicts}
        for i in range(1, 17):
            assert f"req_{i}" in verdict_ids


@pytest.mark.asyncio
async def test_truncation_recovery_evaluates_missing_requirements_in_sub_batch():
    """
    Test that when a response is cut off at the token limit (finish_reason='length'),
    the evaluator recovers the initial verdicts AND immediately evaluates the remaining
    missing items in a follow-up sub-batch, producing 100% evaluated requirements.
    """
    settings = make_test_settings()
    evaluator = GroqMatchEvaluator(settings)

    reqs = [
        Requirement(requirement_id="req_1", kind=RequirementKind.SKILL, text="Python", required=True),
        Requirement(requirement_id="req_2", kind=RequirementKind.SKILL, text="Docker", required=True),
        Requirement(requirement_id="req_3", kind=RequirementKind.RESPONSIBILITY, text="Lead backend team", required=True),
        Requirement(requirement_id="req_4", kind=RequirementKind.RESPONSIBILITY, text="Drive roadmap", required=True),
    ]
    evs = [Evidence(evidence_id="ev1", kind="skills", text="Python Docker Lead", canonical_terms=["python"])]

    call_index = 0

    async def mock_post(url, headers=None, json=None, timeout=None):
        nonlocal call_index
        call_index += 1
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200

        if call_index == 1:
            # First call gets cut off mid-way (only req_1 and req_2 finish before token cutoff)
            content_truncated = (
                '{"verdicts": ['
                + __import__("json").dumps(make_verdict_item("req_1"))
                + ", "
                + __import__("json").dumps(make_verdict_item("req_2"))
                + ', {"requirement_id": "req_3", "cov'
            )
            mock_resp.json.return_value = {
                "choices": [{"finish_reason": "length", "message": {"content": content_truncated}}],
                "usage": {"prompt_tokens": 150, "completion_tokens": 2048, "total_tokens": 2198},
            }
        else:
            # Sub-batch evaluates remaining req_3 and req_4
            content_complete = __import__("json").dumps({
                "verdicts": [make_verdict_item("req_3"), make_verdict_item("req_4")]
            })
            mock_resp.json.return_value = {
                "choices": [{"finish_reason": "stop", "message": {"content": content_complete}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 300, "total_tokens": 400},
            }

        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = mock_post

    with patch.object(GroqMatchEvaluator, "_get_client", return_value=mock_client):
        verdicts, usage = await evaluator.evaluate_with_usage(reqs, evs)

        # Verified: recovered req_1 and req_2, then sub-batched req_3 and req_4
        assert call_index == 2
        assert len(verdicts) == 4
        verdict_ids = [v.requirement_id for v in verdicts]
        assert verdict_ids == ["req_1", "req_2", "req_3", "req_4"]
        assert all(v.status != MatchStatus.EVALUATION_FAILED for v in verdicts)
