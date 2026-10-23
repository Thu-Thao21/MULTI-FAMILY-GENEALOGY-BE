from __future__ import annotations

import asyncio
import sys
from typing import AsyncGenerator

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# Neon closes idle connections (its pooler, and the compute when it auto-suspends), so a pooled
# connection can be dead when it is next used.
#   pool_pre_ping    a cheap round trip when a connection is taken from the pool: a dead one is
#                    replaced before the request uses it (a drop in the MIDDLE of a transaction
#                    is still an error: it becomes 503 DATABASE_UNAVAILABLE).
#   pool_recycle     never reuse a connection older than 30 minutes.
#   connect_timeout  a connect that hangs (compute waking up, network) fails after 15 s instead
#                    of never.
ENGINE_OPTIONS: dict = {
    "pool_pre_ping": True,
    "pool_recycle": 1800,
    "connect_args": {"connect_timeout": 15},
}


def make_engine(url: str | None = None, **overrides) -> AsyncEngine:
    """The one way an engine is built (the application and the integration tests share it).

    `overrides` replace or add options, e.g. pool_size / max_overflow / poolclass / echo.
    """
    return create_async_engine(url or settings.DATABASE_URL, **{**ENGINE_OPTIONS, **overrides})


# settings.DATABASE_URL is already normalized to postgresql+psycopg://
engine = make_engine(echo=False)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def check_db() -> None:
    """Connectivity probe only. Does not create or alter schema."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def init_db() -> None:
    """Startup connectivity check. Does not create tables or run migrations."""
    await check_db()


async def close_db() -> None:
    await engine.dispose()
