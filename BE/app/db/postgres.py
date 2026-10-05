from __future__ import annotations

import asyncio
import sys
from typing import AsyncGenerator

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


# settings.DATABASE_URL is already normalized to postgresql+psycopg://
engine = create_async_engine(settings.DATABASE_URL, echo=False)
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
