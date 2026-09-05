import asyncio
from typing import Optional
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from apps.api.config import settings
import structlog

logger = structlog.get_logger(__name__)

# Global memory saver for test/development isolation
_memory_saver = MemorySaver()
_async_pg_saver: Optional[AsyncPostgresSaver] = None
_pool: Optional[AsyncConnectionPool] = None
_checkpointer_loop: Optional[asyncio.AbstractEventLoop] = None


async def get_checkpointer(use_postgres: bool = True):
    """
    Returns an initialized checkpointer.
    Uses AsyncPostgresSaver connected to PostgreSQL if available, otherwise MemorySaver.
    Safely re-creates the connection pool if running under a new asyncio event loop.
    """
    global _async_pg_saver, _pool, _checkpointer_loop

    if not use_postgres:
        return _memory_saver

    try:
        curr_loop = asyncio.get_running_loop()
    except RuntimeError:
        curr_loop = None

    if (
        _async_pg_saver is not None
        and _pool is not None
        and _checkpointer_loop is curr_loop
        and not getattr(_pool, "_closed", False)
    ):
        return _async_pg_saver

    if _checkpointer_loop is not curr_loop:
        _pool = None
        _async_pg_saver = None
    elif _pool is not None:
        try:
            if not getattr(_pool, "_closed", False):
                await _pool.close()
        except Exception:
            pass
        _pool = None
        _async_pg_saver = None

    try:
        # Construct psycopg sync/async connection string from POSTGRES_SYNC_URL
        conn_str = settings.POSTGRES_SYNC_URL
        _pool = AsyncConnectionPool(conninfo=conn_str, max_size=5, kwargs={"autocommit": True, "prepare_threshold": 0}, open=False)
        await _pool.open()
        _async_pg_saver = AsyncPostgresSaver(_pool)
        # Setup tables if not present
        await _async_pg_saver.setup()
        _checkpointer_loop = curr_loop
        logger.info("Durable AsyncPostgresSaver initialized successfully for LangGraph.")
        return _async_pg_saver
    except Exception as exc:
        logger.warning(
            "Could not initialize PostgreSQL checkpointer; falling back to in-memory MemorySaver",
            error=str(exc)
        )
        return _memory_saver

