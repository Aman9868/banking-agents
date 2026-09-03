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

    def get_intent_signature(self, query: str, intent: Optional[str] = None) -> Optional[str]:
        """Maps query to canonical semantic signature (e.g. intent:BALANCE_CHECK)."""
        if intent:
            return f"intent:{intent}"
        q = query.lower()
        if any(k in q for k in ["balance", "balence", "how much money", "account balance", "wht is my bal", "show balance"]):
            return "intent:BALANCE_CHECK"
        if any(k in q for k in ["spending", "spend", "expenses", "expense", "subscriptions", "recurring", "cashflow"]):
            return "intent:SPENDING_INSIGHTS"
        if any(k in q for k in ["interest rate", "fixed deposit", "atm charges", "fees for", "what are the charges", "policy on"]):
            return "intent:KNOWLEDGE_FAQ"
        return None

    def is_cacheable(self, query: str) -> bool:
        """Determines if a query is an informational read-only request safe for caching."""
        q = query.lower()
        # Non-cacheable: mutating operations or explicit confirmations
        if any(k in q for k in ["transfer", "trnasfer", "send", "pay", "freeze", "freze", "unfreeze", "apply", "replace", "yes", "confirm", "no", "cancel"]):
            return False
        # Cacheable: balance check, status, interest rates, FAQs, fees
        if any(k in q for k in ["balance", "balence", "interest rate", "fixed deposit", "fees", "charges", "what are the charges", "policy", "spending", "expenses"]):
            return True
        return False

    async def get_cached_response(
        self,
        customer_id: int,
        query: str,
        intent: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Layered Cache Lookup:
        Layer 1: Exact Query Hash (Redis Key-Value)
        Layer 2: Intent-Signature Semantic Cache (Canonical intent + entities)
        """
        if not self.is_cacheable(query):
            return None

        norm = self.normalize_query(query)
        client = await self._get_client()

        # 1. Exact Query Key Lookup
        cache_key = self._generate_key(customer_id, norm)
        if client:
            try:
                cached_str = await client.get(cache_key)
                if cached_str:
                    logger.info("Redis Query Exact Cache Hit", customer_id=customer_id, key=cache_key)
                    return json.loads(cached_str)
            except Exception as exc:
                logger.warn("Redis cache read error", error=str(exc))

        if cache_key in self._in_memory_cache:
            logger.info("In-Memory Query Exact Cache Hit", customer_id=customer_id)
            return self._in_memory_cache[cache_key]

        # 2. Intent-Level Semantic Cache Lookup
        sig = self.get_intent_signature(query, intent)
        if sig:
            sig_key = f"cache:cust:{customer_id}:{sig}"
            if client:
                try:
                    cached_str = await client.get(sig_key)
                    if cached_str:
                        logger.info("Redis Intent Semantic Cache Hit", customer_id=customer_id, key=sig_key)
                        res = json.loads(cached_str)
                        res["is_semantic_cache_hit"] = True
                        return res
                except Exception as exc:
                    logger.warn("Redis semantic cache read error", error=str(exc))

            if sig_key in self._in_memory_cache:
                logger.info("In-Memory Intent Semantic Cache Hit", customer_id=customer_id)
                res = dict(self._in_memory_cache[sig_key])
                res["is_semantic_cache_hit"] = True
                return res

        return None

    async def set_cached_response(
        self,
        customer_id: int,
        query: str,
        response_payload: Dict[str, Any],
        ttl_seconds: int = 300,
        intent: Optional[str] = None
    ):
        """Stores response in both exact and semantic cache layers."""
        if not self.is_cacheable(query):
            return

        norm = self.normalize_query(query)
        cache_key = self._generate_key(customer_id, norm)

        # TTL strategy: 60s for live balances, 3600s for static FAQs
        if "balance" in query.lower() or intent == "BALANCE_CHECK":
            ttl = 60
        else:
            ttl = 3600

        client = await self._get_client()
        sig = self.get_intent_signature(query, intent)
        sig_key = f"cache:cust:{customer_id}:{sig}" if sig else None

        if client:
            try:
                await client.set(cache_key, json.dumps(response_payload), ex=ttl)
                if sig_key:
                    await client.set(sig_key, json.dumps(response_payload), ex=ttl)
                return
            except Exception as exc:
                logger.warn("Redis cache write error", error=str(exc))

        # In-memory fallback
        self._in_memory_cache[cache_key] = response_payload
        if sig_key:
            self._in_memory_cache[sig_key] = response_payload

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
