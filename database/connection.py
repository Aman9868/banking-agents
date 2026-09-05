"""Database connection engine and session management using SQLAlchemy Asyncio."""

import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine
)
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import declarative_base
from apps.api.config import settings

Base = declarative_base()

db_url = settings.DATABASE_URL or ""
if db_url.startswith("postgres://"):
    db_url = "postgresql+asyncpg://" + db_url[len("postgres://"):]
elif db_url.startswith("postgresql://"):
    db_url = "postgresql+asyncpg://" + db_url[len("postgresql://"):]

if "channel_binding" in db_url:
    db_url = db_url.replace("channel_binding=require&", "").replace("&channel_binding=require", "").replace("channel_binding=require", "")
if "sslmode=" in db_url:
    db_url = db_url.replace("sslmode=", "ssl=")

connect_args = {}
if "sqlite" in db_url:
    connect_args["check_same_thread"] = False
elif "postgresql" in db_url:
    connect_args["statement_cache_size"] = 0

# Using NullPool for asyncpg avoids cross-event-loop connection contamination in async tests and workers
engine: AsyncEngine = create_async_engine(
    db_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    poolclass=NullPool if "postgresql" in db_url else None,
    connect_args=connect_args
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency provider for async database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

