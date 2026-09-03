"""Distributed idempotency manager for financial operations using Redis."""

import json
from typing import Optional, Dict, Any
import redis.asyncio as aioredis
from apps.api.config import settings
import structlog

logger = structlog.get_logger(__name__)


class IdempotencyConflictError(Exception):
    """Raised when an operation with the same idempotency key is currently processing or completed."""
    def __init__(self, key: str, cached_result: Optional[Dict[str, Any]] = None):
        super().__init__(f"Operation with idempotency key '{key}' has already been processed or is in-flight.")
        self.key = key
        self.cached_result = cached_result


class IdempotencyManager:
    def __init__(self):
        self.redis_url = settings.REDIS_URL
        self._redis_client: Optional[aioredis.Redis] = None
        self._in_memory_store: Dict[str, str] = {}

    async def _get_client(self) -> Optional[aioredis.Redis]:
        if self._redis_client is None:
            try:
                self._redis_client = aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=2.0
                )
                await self._redis_client.ping()
            except Exception as e:
                logger.warning("Redis not available for idempotency. Using in-memory fallback.", error=str(e))
                self._redis_client = None
        return self._redis_client

    async def acquire_lock(self, key: str, ttl_seconds: int = 86400) -> bool:
        """
        Attempts to register the idempotency key.
        Returns True if new and locked, False if already registered.
        """
        client = await self._get_client()
        redis_key = f"idempotency:{key}"
        if client:
            try:
                # SETNX
                acquired = await client.set(redis_key, json.dumps({"status": "PROCESSING"}), nx=True, ex=ttl_seconds)
                return bool(acquired)
            except Exception as e:
                logger.error("Redis set error in idempotency manager", error=str(e))

        # In-memory fallback
        if key in self._in_memory_store:
            return False
        self._in_memory_store[key] = json.dumps({"status": "PROCESSING"})
        return True

    async def set_result(self, key: str, result_data: Dict[str, Any], ttl_seconds: int = 86400):
        """Stores the terminal result associated with the idempotency key."""
        client = await self._get_client()
        redis_key = f"idempotency:{key}"
        val = json.dumps({"status": "COMPLETED", "result": result_data})
        if client:
            try:
                await client.set(redis_key, val, ex=ttl_seconds)
                return
            except Exception as e:
                logger.error("Redis error updating idempotency result", error=str(e))

        self._in_memory_store[key] = val

    async def get_result(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieves cached result if this idempotency key was previously processed."""
        client = await self._get_client()
        redis_key = f"idempotency:{key}"
        raw = None
        if client:
            try:
                raw = await client.get(redis_key)
            except Exception:
                pass

        if not raw:
            raw = self._in_memory_store.get(key)

        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None


idempotency_manager = IdempotencyManager()

