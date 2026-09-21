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
    from app.models.postgres import Admin, Account, AccountRole, Family, FamilyMembership
    from app.core.security import hash_password

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

    # Auto-seed default Admin & Family Head if not exists
    try:
        async with async_session_maker() as session:
            pwd_hash = hash_password('admin123')
            res = await session.execute(select(Admin).where(Admin.username == 'admin'))
            admin = res.scalar_one_or_none()
            if not admin:
                admin = Admin(
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
                )
                session.add(admin)
            else:
                admin.password_hash = pwd_hash
                admin.status = 'active'

            res_acc = await session.execute(select(Account).where(Account.username == 'admin'))
            account = res_acc.scalar_one_or_none()
            if not account:
                account = Account(
                        id='admin_default_001',
                        firebase_uid='admin_default_001',
                        username='admin',
                        email='thuthaor120608@gmail.com',
                        display_name='Quản Trị Viên Hệ Thống',
                        password_hash=pwd_hash,
                        email_verified=True,
                        status='active'
                    )
                session.add(account)
                await session.flush()
            else:
                account.password_hash = pwd_hash
                account.status = 'active'
                account.email_verified = True

            res_role = await session.execute(
                select(AccountRole).where(
                    AccountRole.account_id == account.id,
                    AccountRole.role == 'admin',
                )
            )
            if not res_role.scalars().first():
                session.add(AccountRole(
                        account_id=account.id,
                        role='admin',
                        status='active'
                    ))

            # Fixed Family Admin demo account: familyadmin / familyadmin123
            family_admin_pwd_hash = hash_password('familyadmin123')
            res_family = await session.execute(
                select(Family).where(Family.name == 'Dòng họ Nguyễn · Nam Định')
            )
            family = res_family.scalar_one_or_none()
            if not family:
                family = Family(
                    id='family_demo_001',
                    name='Dòng họ Nguyễn · Nam Định',
                    founder_name='Cụ Nguyễn Văn An',
                    origin_place='Xuân Trường, Nam Định',
                    ancestral_house_address='Xã Xuân Hồng, Xuân Trường, Nam Định',
                    description='Dòng họ mẫu phục vụ kiểm thử giao diện quản lý gia phả.',
                    branches=['Chi Trưởng', 'Chi Hai', 'Chi Ba'],
                    status='active',
                )
                session.add(family)
                await session.flush()

            res_family_admin = await session.execute(
                select(Account).where(Account.username == 'familyadmin')
            )
            family_admin = res_family_admin.scalar_one_or_none()
            if not family_admin:
                family_admin = Account(
                    id='family_admin_demo_001',
                    firebase_uid='family_admin_demo_001',
                    username='familyadmin',
                    email='familyadmin@giaphaviet.vn',
                    display_name='Quản trị Dòng họ Demo',
                    password_hash=family_admin_pwd_hash,
                    email_verified=True,
                    status='active',
                )
                session.add(family_admin)
                await session.flush()
            else:
                family_admin.password_hash = family_admin_pwd_hash
                family_admin.status = 'active'
                family_admin.email_verified = True

            family.owner_id = family_admin.id
            family.created_by = family_admin.id

            res_family_role = await session.execute(
                select(AccountRole).where(
                    AccountRole.account_id == family_admin.id,
                    AccountRole.role == 'family_head',
                )
            )
            family_role = res_family_role.scalars().first()
            if not family_role:
                session.add(AccountRole(
                    account_id=family_admin.id,
                    role='family_head',
                    family_id=family.id,
                    status='active',
                ))
            else:
                family_role.family_id = family.id
                family_role.status = 'active'

            res_membership = await session.execute(
                select(FamilyMembership).where(
                    FamilyMembership.user_id == family_admin.id,
                    FamilyMembership.family_id == family.id,
                )
            )
            membership = res_membership.scalars().first()
            if not membership:
                session.add(FamilyMembership(
                    user_id=family_admin.id,
                    family_id=family.id,
                    membership_role='owner',
                    status='active',
                ))
            else:
                membership.membership_role = 'owner'
                membership.status = 'active'

            await session.commit()
    except Exception as e:
        print(f"[WARN] Auto-seed skipped/notice: {e}")




async def close_db() -> None:
    await engine.dispose()
