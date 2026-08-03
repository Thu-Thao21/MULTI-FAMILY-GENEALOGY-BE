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
    from sqlalchemy import text, select
    from app.models.postgres import Admin, Account, AccountRole
    from app.core.security import hash_password

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        try:
            await conn.execute(text("ALTER TABLE accounts ADD COLUMN password_hash TEXT;"))
        except Exception:
            pass  # Cột đã tồn tại

    # Auto-seed default Admin if not exists
    async with async_session_maker() as session:
        res = await session.execute(select(Admin).where(Admin.username == 'admin'))
        if not res.scalar_one_or_none():
            pwd_hash = hash_password('12060805')
            session.add(Admin(
                id='admin_default_001',
                username='admin',
                email='thuthaor120608@gmail.com',
                phone='0912345678',
                full_name='Quản Trị Viên Hệ Thống',
                password_hash=pwd_hash,
                admin_code='ADM-001',
                permissions_level='super_admin',
                managed_scope='all_families',
                role='admin',
                status='active'
            ))
            res_acc = await session.execute(select(Account).where(Account.email == 'thuthaor120608@gmail.com'))
            if not res_acc.scalar_one_or_none():
                session.add(Account(
                    id='admin_default_001',
                    firebase_uid='admin_default_001',
                    username='admin',
                    email='thuthaor120608@gmail.com',
                    display_name='Quản Trị Viên Hệ Thống',
                    password_hash=pwd_hash,
                    email_verified=True,
                    status='active'
                ))
                await session.flush()
                session.add(AccountRole(
                    account_id='admin_default_001',
                    role='admin',
                    status='active'
                ))

        # Auto-seed default Family Head if not exists
        res_fh = await session.execute(select(Account).where(Account.email == 'truongtoc@gmail.com'))
        if not res_fh.scalar_one_or_none():
            pwd_hash = hash_password('12060805')
            fh_acc = Account(
                id='family_head_default_001',
                firebase_uid='family_head_default_001',
                username='truongtoc',
                email='truongtoc@gmail.com',
                display_name='Trưởng Tộc Nguyễn Văn',
                password_hash=pwd_hash,
                email_verified=True,
                status='active'
            )
            session.add(fh_acc)
            await session.flush()
            session.add(AccountRole(
                account_id='family_head_default_001',
                role='family_head',
                status='active'
            ))

        await session.commit()




async def close_db() -> None:
    await engine.dispose()