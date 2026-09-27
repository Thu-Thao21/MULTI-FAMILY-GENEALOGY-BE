from __future__ import annotations

import asyncio
import sys
from typing import AsyncGenerator

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def init_db() -> None:
    """Tạo tất cả bảng trong database và tự động thêm các cột mới nếu thiếu."""
    import app.models.postgres  # noqa: F401
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        try:
            await conn.execute(text("ALTER TABLE accounts ADD COLUMN password_hash TEXT;"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE families ADD COLUMN owner_id VARCHAR(36);"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE families ADD COLUMN branches JSON DEFAULT '[]';"))
        except Exception:
            pass


async def close_db() -> None:
    await engine.dispose()
