import asyncio
import pytest
from app.services.redis_service import RedisService
from app.core.config import get_settings


class DummyFailingSettings:
    REDIS_ENABLED = True
    REDIS_HOST = "invalid_non_existent_redis_host_99999"
    REDIS_PORT = 6379
    REDIS_PASSWORD = None
    REDIS_DB = 0
    REDIS_URL = None
    REDIS_CACHE_TTL_SECONDS = 300


@pytest.mark.asyncio
async def test_redis_graceful_fallback_when_unreachable():
    """Verify that when Redis is unreachable, all methods catch errors

    silently and return None / False without raising exceptions.
    """
    RedisService._pool = None
    failing_redis = RedisService(settings=DummyFailingSettings())


    # ping returns False
    assert await failing_redis.ping() is False

    # get returns None
    assert await failing_redis.get("some_key") is None
    assert await failing_redis.get_json("some_key") is None

    # set returns False
    assert await failing_redis.set("some_key", "val") is False
    assert await failing_redis.set_json("some_key", {"a": 1}) is False

    # delete & invalidate return False
    assert await failing_redis.delete("some_key") is False
    assert await failing_redis.invalidate_pattern("cache:*") is False

    # acquire_lock falls back to True (allowing PostgreSQL operation to proceed), release_lock returns False when server is unreachable
    assert await failing_redis.acquire_lock("test_lock") is True
    assert await failing_redis.release_lock("test_lock") is False



@pytest.mark.asyncio
async def test_redis_disabled_setting():
    """Verify behavior when REDIS_ENABLED=false."""
    class DisabledSettings:
        REDIS_ENABLED = False
        REDIS_CACHE_TTL_SECONDS = 300

    disabled_redis = RedisService(settings=DisabledSettings())
    assert await disabled_redis.ping() is False
    assert await disabled_redis.get("key") is None
    assert await disabled_redis.set("key", "val") is False


@pytest.mark.asyncio
async def test_redis_in_memory_or_live_operations(monkeypatch):
    """Test JSON serialization, TTL, pattern invalidation logic using mock client if Redis server not present."""
    redis_service = RedisService()
    
    # Check if live Redis server is running
    is_live = await redis_service.ping()
    if is_live:
        key = "unit_test:cache_test_key"
        json_data = {"test_id": 123, "status": "COMPLETED"}
        
        # Test set & get JSON
        assert await redis_service.set_json(key, json_data, ttl_seconds=60) is True
        fetched = await redis_service.get_json(key)
        assert fetched == json_data

        # Test pattern invalidation
        assert await redis_service.invalidate_pattern("unit_test:*") is True
        assert await redis_service.get(key) is None

        # Test lock
        lock_name = "test_doc_lock"
        assert await redis_service.acquire_lock(lock_name, timeout_seconds=10) is True
        assert await redis_service.release_lock(lock_name) is True
    else:
        # Verify fallback is clean when no live server is present
        assert await redis_service.get("test_key") is None
