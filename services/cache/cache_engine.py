"""Redis-backed multi-tier semantic and query caching engine with transactional invalidation."""

import json
import re
import hashlib
from typing import Optional, Dict, Any
import redis.asyncio as aioredis
from apps.api.config import settings
import structlog

logger = structlog.get_logger(__name__)


class CacheEngine:
    def __init__(self):
        self.redis_url = settings.REDIS_URL
        self._redis_client: Optional[aioredis.Redis] = None
        self._in_memory_cache: Dict[str, Dict[str, Any]] = {}

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
            except Exception as exc:
                logger.warning("Redis cache connection failed, operating with in-memory fallback", error=str(exc))
                self._redis_client = None
        return self._redis_client

    def normalize_query(self, query: str) -> str:
        """Strips whitespace, punctuation, and converts to lowercase for exact semantic key matching."""
        cleaned = re.sub(r"[^\w\s]", "", query.lower().strip())
        collapsed = re.sub(r"\s+", " ", cleaned)
        return collapsed

    def _generate_key(self, customer_id: int, normalized_query: str) -> str:
        query_hash = hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()[:16]
        return f"cache:cust:{customer_id}:q:{query_hash}"

    def is_cacheable(self, query: str) -> bool:
        """Determines if a query is an informational read-only request safe for caching."""
        q = query.lower()
        # Non-cacheable: mutating operations or explicit confirmations
        if any(k in q for k in ["transfer", "send", "pay", "freeze", "unfreeze", "apply", "replace", "yes", "confirm", "no", "cancel"]):
            return False
        # Cacheable: balance check, status, interest rates, FAQs, fees
        if any(k in q for k in ["balance", "interest rate", "fixed deposit", "fees", "charges", "what are the charges", "policy"]):
            return True
        return False

    async def get_cached_response(self, customer_id: int, query: str) -> Optional[Dict[str, Any]]:
        """Retrieves cached response from Redis or in-memory fallback."""
        if not self.is_cacheable(query):
            return None

        norm = self.normalize_query(query)
        cache_key = self._generate_key(customer_id, norm)

        client = await self._get_client()
        if client:
            try:
                cached_str = await client.get(cache_key)
                if cached_str:
                    logger.info("Redis Query Cache Hit", customer_id=customer_id, key=cache_key)
                    return json.loads(cached_str)
            except Exception as exc:
                logger.warn("Redis cache read error", error=str(exc))

        # In-memory fallback
        if cache_key in self._in_memory_cache:
            logger.info("In-Memory Query Cache Hit", customer_id=customer_id)
            return self._in_memory_cache[cache_key]

        return None

    async def set_cached_response(
        self,
        customer_id: int,
        query: str,
        response_payload: Dict[str, Any],
        ttl_seconds: int = 300
    ):
        """Stores response in Redis cache with appropriate TTL."""
        if not self.is_cacheable(query):
            return

        norm = self.normalize_query(query)
        cache_key = self._generate_key(customer_id, norm)

        # Use 60s TTL for real-time balances, 3600s (1hr) for static FAQs and interest rates
        if "balance" in query.lower():
            ttl = 60
        else:
            ttl = 3600

        client = await self._get_client()
        if client:
            try:
                await client.set(cache_key, json.dumps(response_payload), ex=ttl)
                return
            except Exception as exc:
                logger.warn("Redis cache write error", error=str(exc))

        # In-memory fallback
        self._in_memory_cache[cache_key] = response_payload

    async def invalidate_customer_cache(self, customer_id: int):
        """
        Crucial Financial Safety Guarantee:
        Purges all cached query keys for this customer when any mutating transaction occurs.
        """
        pattern = f"cache:cust:{customer_id}:*"
        client = await self._get_client()
        if client:
            try:
                keys = []
                async for k in client.scan_iter(match=pattern):
                    keys.append(k)
                if keys:
                    await client.delete(*keys)
                    logger.info("Customer cache invalidated after mutation", customer_id=customer_id, keys_cleared=len(keys))
            except Exception as exc:
                logger.warn("Redis cache invalidation error", error=str(exc))

        # Clear in-memory entries for customer
        self._in_memory_cache = {
            k: v for k, v in self._in_memory_cache.items() if not k.startswith(f"cache:cust:{customer_id}:")
        }


cache_engine = CacheEngine()
