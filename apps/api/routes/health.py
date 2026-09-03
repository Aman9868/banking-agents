"""Health and readiness check endpoints."""

from fastapi import APIRouter
from sqlalchemy import text
from database.connection import AsyncSessionLocal
import redis.asyncio as aioredis
from apps.api.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """Liveness probe."""
    return {"status": "ok", "service": "banking-agent-api"}


@router.get("/ready")
async def readiness_check():
    """Readiness probe checking PostgreSQL and Redis dependencies."""
    pg_ok = False
    redis_ok = False

    # Check Postgres
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            pg_ok = True
    except Exception:
        pg_ok = False

    # Check Redis
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
        redis_ok = True
    except Exception:
        redis_ok = False

    status_str = "healthy" if (pg_ok and redis_ok) else "degraded"
    return {
        "status": status_str,
        "postgres_connected": pg_ok,
        "redis_connected": redis_ok
    }

