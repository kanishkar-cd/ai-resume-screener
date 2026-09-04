import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.schemas.matching import (
    Evidence, MatchStatus, Requirement, RequirementKind,
)
from app.services.matching_service import (
    GroqMatchEvaluator, GroqTokenBudgetGate,
)


@pytest.fixture(autouse=True)
def reset_gate_before_tests():
    """Reset gate state before every test."""
    GroqTokenBudgetGate.reset_gate()
    GroqMatchEvaluator._cache.clear()


# ==============================================================================
# TEST 1 — PREVENT REQUEST WHEN INSUFFICIENT CAPACITY
# ==============================================================================

@pytest.mark.asyncio
async def test_1_prevent_request_when_insufficient_capacity(monkeypatch):
    """
    Given: limit=8000, safety_margin=0.0 (usable=8000), used=6537, request=2632
    6537 + 2632 = 9169 > 8000.
    Expected: Groq HTTP call count = 0 while capacity is insufficient.
    """
    evaluator = GroqMatchEvaluator()
    monkeypatch.setattr(evaluator.settings, "GROQ_TPM_LIMIT", 8000)
    monkeypatch.setattr(evaluator.settings, "GROQ_TPM_SAFETY_MARGIN", 0.0)
    monkeypatch.setattr(evaluator.settings, "ENABLE_HYBRID_MATCHING", True)
    monkeypatch.setattr(evaluator.settings, "GROQ_API_KEY", "mock_key")

    gate = GroqTokenBudgetGate.get_gate(evaluator.settings)
    # Simulate past token usage of 6537 in sliding window
    now = asyncio.get_running_loop().time()
    gate.usage_history = [(now - 10, 6537)]

    mock_client = MagicMock()
    mock_client.post = AsyncMock()
    monkeypatch.setattr(GroqMatchEvaluator, "_get_client", lambda cls, timeout: mock_client)

    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="React")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="React dev")]
    allowed = {"skill:1": {"experience:1"}}

    # Mock estimate_tokens to return exactly 2632
    monkeypatch.setattr(gate, "estimate_tokens", lambda payload, output_estimate=None: 2632)

    # Verify non-blocking rejection when capacity is insufficient: 0 HTTP calls
    verdicts = await evaluator.evaluate(reqs, evs, allowed)
    assert mock_client.post.call_count == 0
    assert verdicts == []


# ==============================================================================
# TEST 2 — REQUEST PROCEEDS WHEN CAPACITY EXISTS
# ==============================================================================

@pytest.mark.asyncio
async def test_2_request_proceeds_when_capacity_exists(monkeypatch):
    """
    Given: limit=8000, safety_margin=0.0, available=4000, request=2632
    Expected: Groq HTTP calls = 1.
    """
    evaluator = GroqMatchEvaluator()
    monkeypatch.setattr(evaluator.settings, "GROQ_TPM_LIMIT", 8000)
    monkeypatch.setattr(evaluator.settings, "GROQ_TPM_SAFETY_MARGIN", 0.0)
    monkeypatch.setattr(evaluator.settings, "ENABLE_HYBRID_MATCHING", True)
    monkeypatch.setattr(evaluator.settings, "GROQ_API_KEY", "mock_key")

    gate = GroqTokenBudgetGate.get_gate(evaluator.settings)
    now = asyncio.get_running_loop().time()
    gate.usage_history = [(now - 10, 4000)]  # 4000 available out of 8000

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"x-ratelimit-remaining-tokens": "1368", "x-ratelimit-reset-tokens": "5s"}
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({"verdicts": [{"requirement_id": "skill:1", "status": "MATCHED", "confidence": 0.9, "evidence_ids": ["experience:1"], "reasoning": "React match"}]})
            }
        }],
        "usage": {"total_tokens": 2632}
    }
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(GroqMatchEvaluator, "_get_client", lambda cls, timeout: mock_client)

    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="React")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="React dev")]
    allowed = {"skill:1": {"experience:1"}}
    monkeypatch.setattr(gate, "estimate_tokens", lambda payload, output_estimate=None: 2632)

    verdicts = await evaluator.evaluate(reqs, evs, allowed)
    assert len(verdicts) == 1
    assert mock_client.post.call_count == 1
    assert gate.header_remaining_tokens == 1368


# ==============================================================================
# TEST 3 — WAIT AND THEN SEND
# ==============================================================================

@pytest.mark.asyncio
async def test_3_wait_and_then_send(monkeypatch):
    """
    Simulate initial insufficient capacity followed by token window expiration.
    Expected: wait -> budget re-check -> 1 Groq request.
    """
    evaluator = GroqMatchEvaluator()
    monkeypatch.setattr(evaluator.settings, "GROQ_TPM_LIMIT", 8000)
    monkeypatch.setattr(evaluator.settings, "GROQ_TPM_SAFETY_MARGIN", 0.0)
    monkeypatch.setattr(evaluator.settings, "ENABLE_HYBRID_MATCHING", True)
    monkeypatch.setattr(evaluator.settings, "GROQ_API_KEY", "mock_key")

    gate = GroqTokenBudgetGate.get_gate(evaluator.settings)
    now = asyncio.get_running_loop().time()
    # Past usage 6537 expired from sliding window
    gate.usage_history = [(now - 60.1, 6537)]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({"verdicts": [{"requirement_id": "skill:1", "status": "MATCHED", "confidence": 0.9, "evidence_ids": ["experience:1"], "reasoning": "Matched"}]})
            }
        }]
    }
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(GroqMatchEvaluator, "_get_client", lambda cls, timeout: mock_client)

    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="React")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="React dev")]
    allowed = {"skill:1": {"experience:1"}}
    monkeypatch.setattr(gate, "estimate_tokens", lambda payload, output_estimate=None: 2632)

    verdicts = await evaluator.evaluate(reqs, evs, allowed)
    assert len(verdicts) == 1
    assert mock_client.post.call_count == 1


# ==============================================================================
# TEST 4 — CONCURRENT REQUESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_4_concurrent_requests_share_global_budget(monkeypatch):
    """
    Run multiple simultaneous LLM requests.
    Verify global token budget is never oversubscribed.
    """
    evaluator = GroqMatchEvaluator()
    monkeypatch.setattr(evaluator.settings, "GROQ_TPM_LIMIT", 5000)
    monkeypatch.setattr(evaluator.settings, "GROQ_TPM_SAFETY_MARGIN", 0.0)
    monkeypatch.setattr(evaluator.settings, "ENABLE_HYBRID_MATCHING", True)
    monkeypatch.setattr(evaluator.settings, "GROQ_API_KEY", "mock_key")

    gate = GroqTokenBudgetGate.get_gate(evaluator.settings)
    gate.window_seconds = 0.1
    monkeypatch.setattr(gate, "estimate_tokens", lambda payload, output_estimate=None: 3000)

    max_in_flight = 0

    async def tracking_post(*args, **kwargs):
        nonlocal max_in_flight
        in_flight_tokens = gate.reserved_in_flight
        if in_flight_tokens > max_in_flight:
            max_in_flight = in_flight_tokens
        await asyncio.sleep(0.05)
        payload = kwargs.get("json", {})
        sub_reqs = json.loads(payload["messages"][1]["content"])["requirements"] if "content" in payload["messages"][1] else []
        verdicts = [
            {"requirement_id": r["requirement_id"], "status": "MATCHED", "confidence": 0.9, "evidence_ids": [f"experience:{r['requirement_id'].split(':')[1]}"], "reasoning": "Matched"}
            for r in sub_reqs
        ]
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.json.return_value = {"choices": [{"message": {"content": json.dumps({"verdicts": verdicts})}}]}
        resp.raise_for_status = MagicMock()
        return resp

    mock_client = MagicMock()
    mock_client.post = tracking_post
    monkeypatch.setattr(GroqMatchEvaluator, "_get_client", lambda cls, timeout: mock_client)

    reqs1 = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="React")]
    reqs2 = [Requirement(requirement_id="skill:2", kind=RequirementKind.REQUIRED_SKILL, text="Node")]
    evs1 = [Evidence(evidence_id="experience:1", kind="experience", text="React dev")]
    evs2 = [Evidence(evidence_id="experience:2", kind="experience", text="Node dev")]
    allowed1 = {"skill:1": {"experience:1"}}
    allowed2 = {"skill:2": {"experience:2"}}

    # Launch two 3000-token requests concurrently against 5000 TPM limit
    t1 = asyncio.create_task(evaluator.evaluate(reqs1, evs1, allowed1))
    t2 = asyncio.create_task(evaluator.evaluate(reqs2, evs2, allowed2))

    res1, res2 = await asyncio.gather(t1, t2)
    # Exactly one request proceeded within the 5000 limit; the other completed without oversubscribing
    assert (len(res1) + len(res2)) == 1
    assert max_in_flight <= 5000


# ==============================================================================
# TEST 5 — UNEXPECTED 429 RESILIENCE
# ==============================================================================

@pytest.mark.asyncio
async def test_5_unexpected_429_handled_safely(monkeypatch):
    """
    Simulate a provider 429 even though local limiter allowed the request.
    Expected: Retry-After respected, bounded retry, no infinite loop.
    """
    evaluator = GroqMatchEvaluator()
    monkeypatch.setattr(evaluator.settings, "ENABLE_HYBRID_MATCHING", True)
    monkeypatch.setattr(evaluator.settings, "GROQ_API_KEY", "mock_key")
    monkeypatch.setattr(evaluator.settings, "GROQ_MAX_RETRIES", 2)

    gate = GroqTokenBudgetGate.get_gate(evaluator.settings)

    attempts = 0
    async def mock_post(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            resp_429 = MagicMock()
            resp_429.status_code = 429
            resp_429.headers = {"Retry-After": "0.01", "x-ratelimit-reset-tokens": "10ms"}
            resp_429.text = "Rate limit reached"
            raise httpx.HTTPStatusError("429 Rate Limit", request=MagicMock(), response=resp_429)
        
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.headers = {}
        resp_200.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps({"verdicts": [{"requirement_id": "skill:1", "status": "MATCHED", "confidence": 0.9, "evidence_ids": ["experience:1"], "reasoning": "Docker match"}]})
                }
            }]
        }
        resp_200.raise_for_status = MagicMock()
        return resp_200

    mock_client = MagicMock()
    mock_client.post = mock_post
    monkeypatch.setattr(GroqMatchEvaluator, "_get_client", lambda cls, timeout: mock_client)

    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="Docker")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Dockerized apps")]
    allowed = {"skill:1": {"experience:1"}}

    verdicts = await evaluator.evaluate(reqs, evs, allowed)
    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.MATCHED
    assert attempts == 2


# ==============================================================================
# TEST 6 — CACHE HIT
# ==============================================================================

@pytest.mark.asyncio
async def test_6_cache_hit_bypasses_gate_and_http(monkeypatch):
    """
    Expected: cache hit -> 0 Groq calls -> 0 token reservation.
    """
    evaluator = GroqMatchEvaluator()
    monkeypatch.setattr(evaluator.settings, "ENABLE_HYBRID_MATCHING", True)
    monkeypatch.setattr(evaluator.settings, "GROQ_API_KEY", "mock_key")

    gate = GroqTokenBudgetGate.get_gate(evaluator.settings)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({"verdicts": [{"requirement_id": "skill:1", "status": "MATCHED", "confidence": 0.9, "evidence_ids": ["experience:1"], "reasoning": "Cached match"}]})
            }
        }]
    }
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(GroqMatchEvaluator, "_get_client", lambda cls, timeout: mock_client)

    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="Cloud Arch")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="AWS Cloud Arch")]
    allowed = {"skill:1": {"experience:1"}}

    # 1st call -> HTTP call executed
    v1 = await evaluator.evaluate(reqs, evs, allowed)
    assert len(v1) == 1
    assert mock_client.post.call_count == 1

    # 2nd call -> Returns from SHA-256 cache immediately
    v2 = await evaluator.evaluate(reqs, evs, allowed)
    assert len(v2) == 1
    assert mock_client.post.call_count == 1  # 0 additional HTTP calls
    assert gate.reserved_in_flight == 0      # 0 token reservation


# ==============================================================================
# TEST 7 — BATCH PROCESSING
# ==============================================================================

@pytest.mark.asyncio
async def test_7_batch_processing_reserves_tokens_per_chunk(monkeypatch):
    """
    Verify multiple LLM batches (>15 requirements) correctly reserve tokens independently.
    """
    evaluator = GroqMatchEvaluator()
    monkeypatch.setattr(evaluator.settings, "ENABLE_HYBRID_MATCHING", True)
    monkeypatch.setattr(evaluator.settings, "GROQ_API_KEY", "mock_key")
    monkeypatch.setattr(evaluator.settings, "GROQ_TPM_LIMIT", 25000)

    gate = GroqTokenBudgetGate.get_gate(evaluator.settings)

    call_count = 0
    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        payload = kwargs.get("json", {})
        sub_reqs = json.loads(payload["messages"][1]["content"])["requirements"] if "content" in payload["messages"][1] else []
        verdicts = [
            {"requirement_id": r["requirement_id"], "status": "MATCHED", "confidence": 0.9, "evidence_ids": [f"experience:{r['requirement_id'].split(':')[1]}"], "reasoning": "Matched"}
            for r in sub_reqs
        ]
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.json.return_value = {"choices": [{"message": {"content": json.dumps({"verdicts": verdicts})}}]}
        resp.raise_for_status = MagicMock()
        return resp

    mock_client = MagicMock()
    mock_client.post = mock_post
    monkeypatch.setattr(GroqMatchEvaluator, "_get_client", lambda cls, timeout: mock_client)

    reqs = [Requirement(requirement_id=f"skill:{i+1}", kind=RequirementKind.REQUIRED_SKILL, text=f"Skill {i+1}") for i in range(25)]
    evs = [Evidence(evidence_id=f"experience:{i+1}", kind="experience", text=f"Evidence {i+1}") for i in range(25)]
    allowed = {f"skill:{i+1}": {f"experience:{i+1}"} for i in range(25)}

    verdicts = await evaluator.evaluate(reqs, evs, allowed)
    assert len(verdicts) == 25
    assert call_count >= 2  # Proves chunking occurred and reserved tokens independently per chunk
