"""Integration tests on the REAL PostgreSQL branch.

Run only with ALLOW_DB_TESTS=1 and -m integration (see docs/testing.md). Each test
runs inside one outer transaction that is ROLLED BACK at the end, so nothing is left
behind. The only exception is tests marked "concurrency": they must commit, use
itest-* prefixed data and delete it in finally.

Nothing here prints or logs DATABASE_URL.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import make_engine
from tests.integration.factory import World, build_app, build_full_app

ENV_FLAG = "ALLOW_DB_TESTS"
_HERE = Path(__file__).resolve().parent


def pytest_collection_modifyitems(config, items):
    skip = pytest.mark.skip(reason=f"set {ENV_FLAG}=1 to run integration tests on the real DB")
    for item in items:
        if _HERE in Path(str(item.fspath)).resolve().parents:
            item.add_marker(pytest.mark.integration)
            # One event loop for the whole run so the pooled DB connections are reused
            # (a fresh TLS connection to Neon costs seconds).
            item.add_marker(pytest.mark.asyncio(loop_scope="session"))
            if os.environ.get(ENV_FLAG) != "1":
                item.add_marker(skip)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine():
    from app.core.config import settings

    eng = make_engine(settings.DATABASE_URL, pool_size=2, max_overflow=0)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def session(engine):
    """AsyncSession inside an outer transaction that is always rolled back.

    session.commit() inside a test only releases a SAVEPOINT.
    """
    async with engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield s
        finally:
            await s.close()
            await outer.rollback()


@pytest_asyncio.fixture(loop_scope="session")
async def world(session) -> World:
    return World(session)


@pytest_asyncio.fixture(loop_scope="session")
async def client(session):
    app = build_app(session)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture(loop_scope="session")
async def real_client(session):
    """HTTP client on the real routers (auth + user administration)."""
    transport = httpx.ASGITransport(app=build_full_app(session))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
