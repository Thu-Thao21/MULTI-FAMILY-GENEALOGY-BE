from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.postgres import User
from app.schemas.user import UserRegister

async def create_user(db: AsyncSession, payload: UserRegister) -> User:
    user_obj = User(
        username=payload.username,
        email=payload.email_or_phone if "@" in payload.email_or_phone else None,
        phone=payload.email_or_phone if "@" not in payload.email_or_phone else None,
        full_name=payload.display_name,
        password_hash=payload.password,
    )
    db.add(user_obj)
    await db.commit()
    await db.refresh(user_obj)
    return user_obj

async def get_users(db: AsyncSession) -> List[User]:
    result = await db.execute(select(User))
    return list(result.scalars().all())

async def get_user_by_id(db: AsyncSession, user_id: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
