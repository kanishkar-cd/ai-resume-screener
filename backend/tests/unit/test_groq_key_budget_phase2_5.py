import asyncio
import pytest
from app.core.config import Settings
from app.services.llm.key_pool import GroqKeyPoolManager, GroqKeyStatus, GroqKeyLease
from app.services.matching_service import ProviderCircuitBreaker


@pytest.fixture(autouse=True)
def reset_cb():
    ProviderCircuitBreaker.reset_breaker()
    yield
    ProviderCircuitBreaker.reset_breaker()


@pytest.mark.asyncio
async def test_key_budget_a_independent_budgets():
    """
    Test A — Independent budgets:
    Key 1 = 7000
    Key 2 = 7000
    Verify: Key 1 budget = 7000, Key 2 budget = 7000.
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2"], token_budget_per_key=7000)
    status = pool.get_pool_status()
    assert status["total_keys"] == 2
    assert status["keys"][0]["token_budget"] == 7000
    assert status["keys"][1]["token_budget"] == 7000
    assert status["keys"][0]["remaining_tokens"] == 7000
    assert status["keys"][1]["remaining_tokens"] == 7000


@pytest.mark.asyncio
async def test_key_budget_b_total_capacity():
    """
    Test B — Total capacity:
    Both keys can independently reserve tokens up to 7000.
    Total capacity = 14,000.
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2"], token_budget_per_key=7000)

    # Reserve 7000 on key 1
    lease1 = await pool.acquire_key(estimated_tokens=7000)
    assert lease1 is not None
    assert lease1.key_id == "groq_key_1"

    # Reserve 7000 on key 2
    lease2 = await pool.acquire_key(estimated_tokens=7000)
    assert lease2 is not None
    assert lease2.key_id == "groq_key_2"

    # Next reservation must fail because both are at 7000 capacity
    lease3 = await pool.acquire_key(estimated_tokens=500)
    assert lease3 is None

    status = pool.get_pool_status()
    assert status["keys"][0]["reserved_in_flight"] == 7000
    assert status["keys"][1]["reserved_in_flight"] == 7000
    assert status["keys"][0]["remaining_tokens"] == 0
    assert status["keys"][1]["remaining_tokens"] == 0


@pytest.mark.asyncio
async def test_key_budget_c_key_1_exhausted():
    """
    Test C — Key 1 exhausted:
    Key 1 remaining = 0
    Key 2 remaining = 7000
    New request must select Key 2.
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2"], token_budget_per_key=7000)

    # Exhaust key 1
    k1 = await pool.acquire_key(estimated_tokens=7000)
    assert k1.key_id == "groq_key_1"

    # Next request for 2000 tokens must select Key 2
    k2 = await pool.acquire_key(estimated_tokens=2000)
    assert k2 is not None
    assert k2.key_id == "groq_key_2"

    # Another request for 2000 tokens must still select Key 2
    k3 = await pool.acquire_key(estimated_tokens=2000)
    assert k3 is not None
    assert k3.key_id == "groq_key_2"


@pytest.mark.asyncio
async def test_key_budget_d_key_2_exhausted():
    """
    Test D — Key 2 exhausted:
    Key 1 remaining = 7000
    Key 2 remaining = 0
    New request must select Key 1.
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2"], token_budget_per_key=7000)

    # Acquire key 1 with 0 tokens
    k1_dummy = await pool.acquire_key(estimated_tokens=0)
    assert k1_dummy.key_id == "groq_key_1"

    # Exhaust key 2
    k2 = await pool.acquire_key(estimated_tokens=7000)
    assert k2.key_id == "groq_key_2"

    # Now Key 2 has 0 remaining, Key 1 has 7000 remaining
    k1 = await pool.acquire_key(estimated_tokens=2000)
    assert k1 is not None
    assert k1.key_id == "groq_key_1"


@pytest.mark.asyncio
async def test_key_budget_e_both_exhausted():
    """
    Test E — Both exhausted:
    Key 1 = 0, Key 2 = 0
    Expected: returns None without infinite loop.
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2"], token_budget_per_key=7000)

    await pool.acquire_key(estimated_tokens=7000)
    await pool.acquire_key(estimated_tokens=7000)

    lease = await pool.acquire_key(estimated_tokens=500)
    assert lease is None


@pytest.mark.asyncio
async def test_key_budget_f_concurrent_reservation_single_key():
    """
    Test F — Concurrent reservation:
    Start concurrent requests against one key. Combined reservations never exceed 7000.
    """
    pool = GroqKeyPoolManager(keys=["test-key-1"], token_budget_per_key=7000)

    async def _worker(req_id: int):
        lease = await pool.acquire_key(estimated_tokens=2000)
        return lease is not None

    tasks = [_worker(i) for i in range(5)]
    results = await asyncio.gather(*tasks)

    # With 7000 budget and 2000 per request, exactly 3 should succeed (6000 reserved) and 2 should fail
    assert results.count(True) == 3
    assert results.count(False) == 2

    status = pool.get_pool_status()
    assert status["keys"][0]["reserved_in_flight"] == 6000
    assert status["keys"][0]["remaining_tokens"] == 1000


@pytest.mark.asyncio
async def test_key_budget_g_two_keys_concurrent_reservation():
    """
    Test G — Two keys concurrently:
    Run concurrent requests and verify Key 1 and Key 2 budgets are tracked independently.
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2"], token_budget_per_key=7000)

    async def _worker(req_id: int):
        lease = await pool.acquire_key(estimated_tokens=2000)
        return lease.key_id if lease else None

    # 8 concurrent requests for 2000 tokens: 3 can fit on Key 1 (6000) and 3 on Key 2 (6000) = 6 total successes
    tasks = [_worker(i) for i in range(8)]
    results = await asyncio.gather(*tasks)

    key1_count = results.count("groq_key_1")
    key2_count = results.count("groq_key_2")
    none_count = results.count(None)

    assert key1_count == 3
    assert key2_count == 3
    assert none_count == 2

    status = pool.get_pool_status()
    assert status["keys"][0]["reserved_in_flight"] == 6000
    assert status["keys"][1]["reserved_in_flight"] == 6000


@pytest.mark.asyncio
async def test_key_budget_h_actual_usage_reconciliation():
    """
    Test H — Actual usage reconciliation:
    Reserved = 2000, Actual = 1500.
    Verify 500 difference is returned to remaining budget.
    """
    pool = GroqKeyPoolManager(keys=["test-key-1"], token_budget_per_key=7000)

    lease = await pool.acquire_key(estimated_tokens=2000)
    assert lease is not None
    assert lease.key_id == "groq_key_1"

    status_during = pool.get_pool_status()
    assert status_during["keys"][0]["reserved_in_flight"] == 2000
    assert status_during["keys"][0]["remaining_tokens"] == 5000

    # Succeeded with actual_tokens=1500
    await pool.mark_success(lease.key_id, estimated_tokens=2000, actual_tokens=1500)

    status_after = pool.get_pool_status()
    assert status_after["keys"][0]["reserved_in_flight"] == 0
    assert status_after["keys"][0]["window_tokens_used"] == 1500
    # 7000 - 1500 = 5500 remaining
    assert status_after["keys"][0]["remaining_tokens"] == 5500


@pytest.mark.asyncio
async def test_key_budget_i_over_reservation_prevention():
    """
    Test I — Over-reservation prevention:
    Remaining = 1000, request estimate = 1500.
    Key must be rejected before HTTP execution.
    """
    pool = GroqKeyPoolManager(keys=["test-key-1"], token_budget_per_key=7000)

    # Use 6000 tokens
    lease1 = await pool.acquire_key(estimated_tokens=6000)
    await pool.mark_success(lease1.key_id, estimated_tokens=6000, actual_tokens=6000)

    status = pool.get_pool_status()
    assert status["keys"][0]["remaining_tokens"] == 1000

    # Request for 1500 tokens must be rejected
    lease2 = await pool.acquire_key(estimated_tokens=1500)
    assert lease2 is None

    # Request for 800 tokens must be accepted
    lease3 = await pool.acquire_key(estimated_tokens=800)
    assert lease3 is not None
    assert lease3.key_id == "groq_key_1"


@pytest.mark.asyncio
async def test_key_budget_j_cooldown_with_budget():
    """
    Test J — Cooldown + budget:
    A key in cooldown must NOT be selected even if it has budget remaining.
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2"], token_budget_per_key=7000, cooldown_seconds=60.0)

    # Key 1 fails with 429
    await pool.mark_failure("groq_key_1", error_type="GROQ_HTTP_429", status_code=429)

    # Key 1 has 7000 tokens remaining, but is in COOLDOWN -> must select Key 2
    lease = await pool.acquire_key(estimated_tokens=1000)
    assert lease is not None
    assert lease.key_id == "groq_key_2"


@pytest.mark.asyncio
async def test_key_budget_k_disabled_with_budget():
    """
    Test K — Disabled + budget:
    A disabled key must never be selected even if it has budget remaining.
    """
    pool = GroqKeyPoolManager(keys=["test-key-1", "test-key-2"], token_budget_per_key=7000)

    # Key 1 disabled
    await pool.mark_failure("groq_key_1", error_type="GROQ_AUTH_FAILED", status_code=401, is_permanent=True)

    # Must select Key 2
    lease = await pool.acquire_key(estimated_tokens=1000)
    assert lease is not None
    assert lease.key_id == "groq_key_2"

    # If Key 2 is exhausted, must return None (cannot use disabled Key 1)
    await pool.acquire_key(estimated_tokens=6000)
    lease_none = await pool.acquire_key(estimated_tokens=1000)
    assert lease_none is None
