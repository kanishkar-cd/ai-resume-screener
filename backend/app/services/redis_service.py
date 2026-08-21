import json
from typing import Any
import structlog
import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = structlog.get_logger(__name__)


class RedisService:
    """Async Redis service providing connection pooling, JSON caching, TTL,

    locks, and graceful PostgreSQL-fallback on connection failure.
    """

    _pool: aioredis.ConnectionPool | None = None

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()
        self.enabled: bool = getattr(self.settings, "REDIS_ENABLED", True)
        self.default_ttl: int = getattr(self.settings, "REDIS_CACHE_TTL_SECONDS", 300)
        self._client: aioredis.Redis | None = None

    def _get_client(self) -> aioredis.Redis | None:
        if not self.enabled:
            return None

        if RedisService._pool is None:
            redis_url = getattr(self.settings, "REDIS_URL", None)
            if redis_url:
                RedisService._pool = aioredis.ConnectionPool.from_url(
                    redis_url,
                    decode_responses=True,
                    max_connections=20,
                    socket_connect_timeout=0.2,
                    socket_timeout=0.2,
                )
            else:
                host = getattr(self.settings, "REDIS_HOST", "localhost")
                port = getattr(self.settings, "REDIS_PORT", 6379)
                password = getattr(self.settings, "REDIS_PASSWORD", None)
                db = getattr(self.settings, "REDIS_DB", 0)
                RedisService._pool = aioredis.ConnectionPool(
                    host=host,
                    port=port,
                    password=password if password else None,
                    db=db,
                    decode_responses=True,
                    max_connections=20,
                    socket_connect_timeout=0.2,
                    socket_timeout=0.2,
                )


        if self._client is None:
            self._client = aioredis.Redis(connection_pool=RedisService._pool)
        return self._client

    async def ping(self) -> bool:
        """Check if Redis connection is responsive."""
        client = self._get_client()
        if client is None:
            return False
        try:
            return bool(await client.ping())
        except (RedisError, Exception) as exc:
            logger.debug("[REDIS] ping failed (fallback active)", error=str(exc))
            return False

    async def get(self, key: str) -> str | None:
        """Retrieve raw string value from Redis."""
        client = self._get_client()
        if client is None:
            return None
        try:
            return await client.get(key)
        except (RedisError, Exception) as exc:
            logger.debug("[REDIS] get failed (fallback active)", key=key, error=str(exc))
            return None

    async def get_json(self, key: str) -> Any | None:
        """Retrieve and deserialize JSON value from Redis."""
        val = await self.get(key)
        if val is None:
            return None
        try:
            return json.loads(val)
        except Exception as exc:
            logger.warning("[REDIS] json decode failed", key=key, error=str(exc))
            return None

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> bool:
        """Set string value in Redis with optional TTL."""
        client = self._get_client()
        if client is None:
            return False
        try:
            ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
            if ttl > 0:
                await client.set(key, value, ex=ttl)
            else:
                await client.set(key, value)
            return True
        except (RedisError, Exception) as exc:
            logger.debug("[REDIS] set failed (fallback active)", key=key, error=str(exc))
            return False

    async def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> bool:
        """Serialize and set JSON value in Redis with optional TTL."""
        try:
            encoded = json.dumps(value, default=str)
            return await self.set(key, encoded, ttl_seconds=ttl_seconds)
        except Exception as exc:
            logger.warning("[REDIS] json encode failed", key=key, error=str(exc))
            return False

    async def delete(self, *keys: str) -> bool:
        """Delete one or more keys from Redis."""
        client = self._get_client()
        if client is None or not keys:
            return False
        try:
            await client.delete(*keys)
            return True
        except (RedisError, Exception) as exc:
            logger.debug("[REDIS] delete failed (fallback active)", keys=keys, error=str(exc))
            return False

    async def invalidate_pattern(self, pattern: str) -> bool:
        """Invalidate all keys matching pattern (e.g. 'cache:doc:*')."""
        client = self._get_client()
        if client is None:
            return False
        try:
            keys = []
            async for k in client.scan_iter(match=pattern):
                keys.append(k)
            if keys:
                await client.delete(*keys)
            return True
        except (RedisError, Exception) as exc:
            logger.debug("[REDIS] pattern invalidation failed", pattern=pattern, error=str(exc))
            return False

    async def acquire_lock(self, lock_name: str, timeout_seconds: int = 30) -> bool:
        """Acquire a simple non-blocking distributed lock."""
        client = self._get_client()
        if client is None:
            return True  # Fallback: allow execution if Redis is down
        try:
            lock_key = f"lock:{lock_name}"
            acquired = await client.set(lock_key, "1", nx=True, ex=timeout_seconds)
            return bool(acquired)
        except (RedisError, Exception) as exc:
            logger.debug("[REDIS] acquire lock failed (fallback active)", lock_name=lock_name, error=str(exc))
            return True

    async def release_lock(self, lock_name: str) -> bool:
        """Release distributed lock."""
        client = self._get_client()
        if client is None:
            return True
        try:
            lock_key = f"lock:{lock_name}"
            await client.delete(lock_key)
            return True
        except (RedisError, Exception) as exc:
            logger.debug("[REDIS] release lock failed", lock_name=lock_name, error=str(exc))
            return False

    async def close(self) -> None:

        """Close client connection."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
