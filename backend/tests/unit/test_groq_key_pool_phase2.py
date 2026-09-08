import asyncio
import time
import pytest
from app.core.config import Settings
from app.services.llm.key_pool import GroqKeyPoolManager, GroqKeyStatus, GroqKeyLease
from app.services.llm.batch_pipeline import (
    GroqBatchExecutor,
    PostDeterministicPipeline,
    ResumeBatchContext,
    group_into_batches,
)
from app.schemas.matching import (
    Evidence,
    MatchMethod,
    MatchStatus,
    MatchVerdict,
    Requirement,
    RequirementKind,
)
from app.services.matching_service import ProviderCircuitBreaker


@pytest.fixture(autouse=True)
def reset_cb():
    ProviderCircuitBreaker.reset_breaker()
    yield
    ProviderCircuitBreaker.reset_breaker()


@pytest.mark.asyncio
async def test_key_pool_a_two_keys_round_robin():
    """
    Test A — Two keys:
    key1, key2
    Expected:
    request 1 -> key1
    request 2 -> key2
    request 3 -> key1
    request 4 -> key2
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2"])
    assert pool.total_keys == 2

    k1 = await pool.acquire_key()
    assert k1 is not None and k1.api_key == "test-key-1" and k1.key_id == "groq_key_1"

    k2 = await pool.acquire_key()
    assert k2 is not None and k2.api_key == "test-key-2" and k2.key_id == "groq_key_2"

    k3 = await pool.acquire_key()
    assert k3 is not None and k3.api_key == "test-key-1" and k3.key_id == "groq_key_1"

    k4 = await pool.acquire_key()
    assert k4 is not None and k4.api_key == "test-key-2" and k4.key_id == "groq_key_2"


@pytest.mark.asyncio
async def test_key_pool_b_three_keys_round_robin():
    """
    Test B — Three keys:
    Expected sequence: key1, key2, key3, key1, key2, key3
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2", "test-key-3"])
    assert pool.total_keys == 3

    keys_acquired = [await pool.acquire_key() for _ in range(6)]
    key_ids = [k.key_id for k in keys_acquired if k]
    assert key_ids == [
        "groq_key_1", "groq_key_2", "groq_key_3",
        "groq_key_1", "groq_key_2", "groq_key_3",
    ]


@pytest.mark.asyncio
async def test_key_pool_c_duplicate_keys():
    """
    Test C — Duplicate keys:
    Input: key1, key1, key2
    Expected pool size: 2
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-1", "test-key-2"])
    assert pool.total_keys == 2
    k1 = await pool.acquire_key()
    k2 = await pool.acquire_key()
    assert k1.api_key == "test-key-1"
    assert k2.api_key == "test-key-2"


@pytest.mark.asyncio
async def test_key_pool_d_empty_keys():
    """
    Test D — Empty keys:
    Input: key1, empty/whitespace, key2, None
    Expected pool size: 2
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "", "   ", "test-key-2", None])
    assert pool.total_keys == 2
    k1 = await pool.acquire_key()
    k2 = await pool.acquire_key()
    assert k1.api_key == "test-key-1"
    assert k2.api_key == "test-key-2"


@pytest.mark.asyncio
async def test_key_pool_e_key_1_rate_limited_429():
    """
    Test E — Key 1 rate limited:
    key1 -> 429 -> cooldown
    next request -> key2
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2"], cooldown_seconds=10.0)
    k1 = await pool.acquire_key()
    assert k1.key_id == "groq_key_1"

    await pool.mark_failure(k1.key_id, error_type="GROQ_HTTP_429", status_code=429)

    status = pool.get_pool_status()
    assert status["available_count"] == 1
    assert status["cooldown_count"] == 1

    # Next acquire must return key2, not key1
    k_next = await pool.acquire_key()
    assert k_next is not None
    assert k_next.key_id == "groq_key_2"

    # Subsequent acquire must still return key2 because key1 is in cooldown
    k_next2 = await pool.acquire_key()
    assert k_next2.key_id == "groq_key_2"


@pytest.mark.asyncio
async def test_key_pool_f_key_1_timeout():
    """
    Test F — Key 1 timeout:
    key1 -> timeout -> cooldown
    next request -> key2
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2"], cooldown_seconds=10.0)
    k1 = await pool.acquire_key()
    assert k1.key_id == "groq_key_1"

    await pool.mark_failure(k1.key_id, error_type="GROQ_TIMEOUT", status_code=408)

    k_next = await pool.acquire_key()
    assert k_next.key_id == "groq_key_2"


@pytest.mark.asyncio
async def test_key_pool_g_key_1_auth_failure_401():
    """
    Test G — Key 1 authentication failure (401/403):
    key1 -> disabled
    next request -> key2
    key1 must NOT be retried.
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2"])
    k1 = await pool.acquire_key()
    assert k1.key_id == "groq_key_1"

    await pool.mark_failure(k1.key_id, error_type="GROQ_AUTH_FAILED", status_code=401, is_permanent=True)

    status = pool.get_pool_status()
    assert status["disabled_count"] == 1
    assert status["available_count"] == 1

    k_next1 = await pool.acquire_key()
    assert k_next1.key_id == "groq_key_2"

    k_next2 = await pool.acquire_key()
    assert k_next2.key_id == "groq_key_2"


@pytest.mark.asyncio
async def test_key_pool_h_key_recovery_after_cooldown():
    """
    Test H — Key recovery:
    key1 -> cooldown (short cooldown 0.1s)
    cooldown expires -> key1 becomes available again
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2"], cooldown_seconds=0.1)
    k1 = await pool.acquire_key()
    await pool.mark_failure(k1.key_id, error_type="GROQ_HTTP_429", status_code=429)

    # Immediately, only key2 available
    k2 = await pool.acquire_key()
    assert k2.key_id == "groq_key_2"

    # Wait for cooldown to expire
    await asyncio.sleep(0.15)

    # Now both keys should be available, round-robin can select key1 again
    k_recovered = await pool.acquire_key()
    assert k_recovered is not None


@pytest.mark.asyncio
async def test_key_pool_i_all_keys_unavailable():
    """
    Test I — All keys unavailable:
    All keys in cooldown or disabled -> returns None, no infinite loop.
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2"], cooldown_seconds=60.0)
    await pool.mark_failure("groq_key_1", error_type="GROQ_AUTH_FAILED", status_code=401, is_permanent=True)
    await pool.mark_failure("groq_key_2", error_type="GROQ_HTTP_429", status_code=429)

    lease = await pool.acquire_key()
    assert lease is None

    status = pool.get_pool_status()
    assert status["available_count"] == 0
    assert status["cooldown_count"] == 1
    assert status["disabled_count"] == 1


@pytest.mark.asyncio
async def test_key_pool_j_concurrent_acquisition():
    """
    Test J — Concurrent acquisition:
    Launch multiple concurrent tasks requesting keys simultaneously.
    Verify: no race conditions, fair distribution, correct counters.
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2", "test-key-3"])

    async def _worker(task_id: int):
        lease = await pool.acquire_key()
        await asyncio.sleep(0.01)
        if lease:
            await pool.mark_success(lease.key_id)
        return lease.key_id if lease else None

    tasks = [_worker(i) for i in range(12)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 12
    # Ensure all 3 keys were utilized
    assert set(results) == {"groq_key_1", "groq_key_2", "groq_key_3"}
    status = pool.get_pool_status()
    assert status["total_keys"] == 3
    assert status["available_count"] == 3
    total_successes = sum(k["success_count"] for k in status["keys"])
    assert total_successes == 12


@pytest.mark.asyncio
async def test_key_pool_k_partial_batch_failure_retry_isolation():
    """
    Test K — Partial batch failure:
    Batch = [A, B, C]
    Attempt 1 on key1 returns verdicts for A and C only (B failed/missing).
    Attempt 2 on key2 retries ONLY B.
    A and C are preserved and not reprocessed.
    """
    req_a = Requirement(requirement_id="req-a", text="Python skill", kind=RequirementKind.SKILL, required=True)
    req_b = Requirement(requirement_id="req-b", text="Kubernetes skill", kind=RequirementKind.SKILL, required=True)
    req_c = Requirement(requirement_id="req-c", text="SQL skill", kind=RequirementKind.SKILL, required=True)

    ev_a = Evidence(evidence_id="ev-a", text="5 years Python", kind="skills")
    ev_b = Evidence(evidence_id="ev-b", text="Kubernetes admin", kind="skills")
    ev_c = Evidence(evidence_id="ev-c", text="Postgres SQL", kind="skills")

    ctx_a = ResumeBatchContext(resume_id="res_a", requirements=[req_a], candidate_evidence=[ev_a], allowed_evidence={"req-a": {"ev-a"}})
    ctx_b = ResumeBatchContext(resume_id="res_b", requirements=[req_b], candidate_evidence=[ev_b], allowed_evidence={"req-b": {"ev-b"}})
    ctx_c = ResumeBatchContext(resume_id="res_c", requirements=[req_c], candidate_evidence=[ev_c], allowed_evidence={"req-c": {"ev-c"}})

    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2"])
    executor = GroqBatchExecutor(key_pool=pool, max_retries=2)

    call_count = 0
    keys_used = []
    batches_received = []

    async def mock_send_groq_request(batch, exclude_key_ids=None):
        nonlocal call_count
        call_count += 1
        lease = await pool.acquire_key(exclude_key_ids=exclude_key_ids)
        keys_used.append(lease.key_id)
        batches_received.append([c.resume_id for c in batch])

        if call_count == 1:
            # First attempt returns results for res_a and res_c only
            return {
                "res_a": [MatchVerdict(requirement_id="req-a", status=MatchStatus.MATCHED, method=MatchMethod.LLM, confidence=1.0, reasoning="Matched A")],
                "res_c": [MatchVerdict(requirement_id="req-c", status=MatchStatus.MATCHED, method=MatchMethod.LLM, confidence=1.0, reasoning="Matched C")],
            }, None, lease.key_id
        else:
            # Second attempt receives ONLY res_b
            return {
                "res_b": [MatchVerdict(requirement_id="req-b", status=MatchStatus.MATCHED, method=MatchMethod.LLM, confidence=1.0, reasoning="Matched B")],
            }, None, lease.key_id


    executor._send_groq_request = mock_send_groq_request

    results = await executor.execute_batch_with_retry([ctx_a, ctx_b, ctx_c], max_retries=1)

    assert call_count == 2
    assert batches_received[0] == ["res_a", "res_b", "res_c"]
    # Attempt 2 ONLY retried res_b
    assert batches_received[1] == ["res_b"]
    assert "res_a" in results
    assert "res_b" in results
    assert "res_c" in results
    assert results["res_a"][0].status == MatchStatus.MATCHED
    assert results["res_b"][0].status == MatchStatus.MATCHED
    assert results["res_c"][0].status == MatchStatus.MATCHED
