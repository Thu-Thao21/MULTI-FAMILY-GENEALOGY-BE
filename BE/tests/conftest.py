import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select
import asyncio

from app.main import app
from app.db.postgres import Base, get_db
from app.dependencies.auth import get_current_account
from app.models.postgres import (
    Account,
    AccountRole,
    FamilyMembership,
    Permission,
    Role,
    RolePermission,
)
from app.services.access_service import MANAGE_PERMISSIONS

# Use in-memory sqlite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session


async def override_get_current_account():
    async with TestingSessionLocal() as session:
        result = await session.execute(select(Account).where(Account.id == "test-admin"))
        return result.scalar_one()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        session.add(
            Account(
                id="test-admin",
                firebase_uid="test-admin",
                username="test-admin",
                email="test-admin@example.test",
                display_name="Test Admin",
                status="ACTIVE",
            )
        )
        session.add(
            Role(
                id="role-admin",
                code="admin",
                name="Administrator",
                is_system_role=True,
            )
        )
        session.add(
            AccountRole(
                account_id="test-admin",
                role_id="role-admin",
            )
        )
        session.add_all(
            [
                FamilyMembership(
                    user_id="test-admin", family_id=family_id, status="ACTIVE"
                )
                for family_id in ("fam1", "fam2")
            ]
        )
        for index, code in enumerate(sorted(MANAGE_PERMISSIONS)):
            permission_id = f"permission-{index}"
            session.add(
                Permission(
                    id=permission_id,
                    code=code,
                    module=code.split(".", maxsplit=1)[0],
                )
            )
            session.add(
                RolePermission(
                    role_id="role-admin",
                    permission_id=permission_id,
                )
            )
        await session.commit()
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    app.dependency_overrides[get_current_account] = override_get_current_account
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_current_account, None)
