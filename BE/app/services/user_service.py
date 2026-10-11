from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.postgres import Account


async def get_users(db: AsyncSession) -> list[Account]:
    result = await db.execute(select(Account))
    return list(result.scalars().all())


async def get_user_by_id(
    db: AsyncSession, user_id: str
) -> Optional[Account]:
    result = await db.execute(select(Account).where(Account.id == user_id))
    return result.scalar_one_or_none()
