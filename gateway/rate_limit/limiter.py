"""Production-grade Redis sliding-window rate limiter middleware."""

import time
from typing import Optional, Dict, List
import redis.asyncio as aioredis
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from apps.api.config import settings
import structlog

logger = structlog.get_logger(__name__)


class SlidingWindowRateLimiter:
    def __init__(self, requests_per_minute: int = 60):
        self.rpm = requests_per_minute
        self.window_seconds = 60
        self.redis_url = settings.REDIS_URL
        self._redis_client: Optional[aioredis.Redis] = None
        self._in_memory_timestamps: Dict[str, List[float]] = {}

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
                logger.warning("Redis not available for rate limiting; falling back to in-memory window", error=str(exc))
                self._redis_client = None
        return self._redis_client

    async def is_rate_limited(self, identifier: str) -> tuple[bool, int, int]:
        """
        Calculates sliding window rate limit for identifier.
        Returns: (is_limited: bool, remaining_requests: int, reset_seconds: int)
        """
        now = time.time()
        window_start = now - self.window_seconds
        client = await self._get_client()

        if client:
            try:
                key = f"ratelimit:{identifier}"
                pipe = client.pipeline()
                # 1. Remove timestamps outside current window
                pipe.zremrangebyscore(key, 0, window_start)
                # 2. Add current timestamp
                pipe.zadd(key, {str(now): now})
                # 3. Count elements in window
                pipe.zcard(key)
                # 4. Set key expiration
                pipe.expire(key, self.window_seconds)
                results = await pipe.execute()

                current_count = results[2]
                remaining = max(0, self.rpm - current_count)
                is_limited = current_count > self.rpm
                return is_limited, remaining, self.window_seconds
            except Exception as exc:
                logger.warn("Redis rate limit check error", error=str(exc))

        # In-memory sliding window fallback
        timestamps = self._in_memory_timestamps.get(identifier, [])
        # Filter timestamps within current window
        valid_ts = [t for t in timestamps if t > window_start]
        valid_ts.append(now)
        self._in_memory_timestamps[identifier] = valid_ts

        current_count = len(valid_ts)
        remaining = max(0, self.rpm - current_count)
        is_limited = current_count > self.rpm
        return is_limited, remaining, self.window_seconds


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 120):
        super().__init__(app)
        self.limiter = SlidingWindowRateLimiter(requests_per_minute=requests_per_minute)

    async def dispatch(self, request: Request, call_next):
        # Exclude static assets, docs, and health check endpoints
        path = request.url.path
        if path.startswith("/static") or path in ["/docs", "/openapi.json", "/health", "/readiness", "/"]:
            return await call_next(request)

        # Identify client by IP or customer header
        client_ip = request.client.host if request.client else "unknown"
        client_id = request.headers.get("X-Customer-ID", client_ip)

        is_limited, remaining, reset_secs = await self.limiter.is_rate_limited(client_id)

        if is_limited:
            logger.warn("Rate limit exceeded", client_id=client_id, path=path)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down and try again."},
                headers={
                    "Retry-After": str(reset_secs),
                    "X-RateLimit-Limit": str(self.limiter.rpm),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_secs)
                }
            )

        response: Response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limiter.rpm)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_secs)
        return response

