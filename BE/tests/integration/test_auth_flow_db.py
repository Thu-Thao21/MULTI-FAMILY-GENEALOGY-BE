"""Mốc D auth flow on the real DB (rolled back). Firebase is a fake verifier.

Proves what fakes cannot: rows really land in user_sessions / login_history /
audit_logs, the failure row is COMMITTED before the error, INET/Text columns accept
what the code writes, and the queries behind /auth/me work on PostgreSQL.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import func, select

from app.controllers.auth_access.router import router
from app.core.errors import register_exception_handlers
from app.core.firebase import get_identity_provider
from app.core.request_id import RequestIdMiddleware
from app.db.postgres import get_db
from app.dependencies.permissions import owner_actions
from app.models.user_access.entities import (
    AuditLog,
    CredentialMetadata,
    LoginHistory,
    User,
    UserSession,
)
from tests.fakes import FakeIdentityProvider


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def provider() -> FakeIdentityProvider:
    return FakeIdentityProvider()


@pytest_asyncio.fixture(loop_scope="session")
async def api(session, provider):
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")

    async def db_override():
        yield session

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_identity_provider] = lambda: provider
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def login(api, provider, user, **kw):
    return await api.post(
        "/api/v1/auth/session", json={"id_token": provider.issue(user.firebase_uid, **kw)}
    )


async def history(session, user_id) -> list[tuple[bool, str | None]]:
    rows = await session.execute(
        select(LoginHistory.success, LoginHistory.failure_reason)
        .where(LoginHistory.user_id == user_id)
        .order_by(LoginHistory.occurred_at)
    )
    return [(r[0], r[1]) for r in rows]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


async def test_login_stores_hash_history_and_last_login(api, provider, session, world):
    user = await world.user(cred=dict(must_change_password=False, failed_login_count=0))
    r = await login(api, provider, user, email="login@example.test")
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]

    row = (
        await session.execute(select(UserSession).where(UserSession.user_id == user.user_id))
    ).scalar_one()
    assert row.token_jti_hash == hashlib.sha256(token.encode()).hexdigest()
    assert row.revoked_at is None and row.ip_address is not None
    assert timedelta(hours=7, minutes=59) < row.expires_at - row.created_at <= timedelta(hours=8)
    assert await history(session, user.user_id) == [(True, None)]
    identifier = await session.scalar(
        select(LoginHistory.identifier).where(LoginHistory.user_id == user.user_id)
    )
    assert identifier == "login@example.test"
    last_login = await session.scalar(select(User.last_login_at).where(User.user_id == user.user_id))
    assert last_login is not None

    me = await api.get("/api/v1/auth/me", headers=bearer(token))
    assert me.status_code == 200 and me.json()["user_id"] == str(user.user_id)


async def test_unknown_uid_creates_no_user_and_no_history(api, provider, session):
    users_before = await session.scalar(select(func.count()).select_from(User))
    history_before = await session.scalar(select(func.count()).select_from(LoginHistory))
    r = await api.post("/api/v1/auth/session", json={"id_token": provider.issue("itest-unknown-uid")})
    assert (r.status_code, r.json()["error"]["code"]) == (401, "INVALID_ID_TOKEN")
    assert await session.scalar(select(func.count()).select_from(User)) == users_before
    assert await session.scalar(select(func.count()).select_from(LoginHistory)) == history_before
    assert await session.scalar(
        select(func.count()).select_from(User).where(User.firebase_uid == "itest-unknown-uid")
    ) == 0


async def test_failed_login_history_is_committed_before_the_error(api, provider, session, world):
    """After the 403, roll back the session: only COMMITTED work survives.

    With join_transaction_mode="create_savepoint", session.commit() inside the use case
    releases the savepoint; session.rollback() discards anything not committed. If the
    use case had not committed, the history row (and the user) would vanish here.
    """
    user = await world.user("LOCKED")
    user_id = user.user_id  # rollback expires ORM objects
    r = await login(api, provider, user)
    assert (r.status_code, r.json()["error"]["code"]) == (403, "ACCOUNT_BLOCKED")

    await session.rollback()
    assert await history(session, user_id) == [(False, "ACCOUNT_BLOCKED")]
    assert await session.scalar(
        select(func.count()).select_from(UserSession).where(UserSession.user_id == user_id)
    ) == 0


async def test_id_token_older_than_password_change_is_rejected(api, provider, session, world):
    user = await world.user(
        cred=dict(must_change_password=False, failed_login_count=0, password_changed_at=utcnow())
    )
    user_id = user.user_id
    r = await login(api, provider, user, auth_time=utcnow() - timedelta(minutes=30))
    assert (r.status_code, r.json()["error"]["code"]) == (401, "INVALID_ID_TOKEN")
    await session.rollback()
    assert await history(session, user_id) == [(False, "ID_TOKEN_BEFORE_PASSWORD_CHANGE")]


async def test_temporary_password_expired_on_db(api, provider, session, world):
    user = await world.user(
        "PENDING",
        cred=dict(
            must_change_password=True,
            failed_login_count=0,
            temporary_password_expires_at=utcnow() - timedelta(minutes=1),
        ),
    )
    r = await login(api, provider, user)
    assert (r.status_code, r.json()["error"]["code"]) == (403, "TEMPORARY_PASSWORD_EXPIRED")
    assert await history(session, user.user_id) == [(False, "TEMPORARY_PASSWORD_EXPIRED")]


async def test_logout_revokes_in_db(api, provider, session, world):
    user = await world.user()
    token = (await login(api, provider, user)).json()["access_token"]
    assert (await api.post("/api/v1/auth/logout", headers=bearer(token))).status_code == 204
    row = (
        await session.execute(select(UserSession).where(UserSession.user_id == user.user_id))
    ).scalar_one()
    assert row.revoked_at is not None and row.revoke_reason == "LOGOUT"
    again = await api.get("/api/v1/auth/me", headers=bearer(token))
    assert (again.status_code, again.json()["error"]["code"]) == (401, "SESSION_INVALID")


async def test_first_password_change_end_to_end(api, provider, session, world):
    user = await world.user(
        "PENDING",
        first_login_required=True,
        cred=dict(
            must_change_password=True,
            failed_login_count=0,
            temporary_password_expires_at=utcnow() + timedelta(days=1),
        ),
    )
    old_id_token = provider.issue(user.firebase_uid, auth_time=utcnow() - timedelta(seconds=60))
    r = await api.post("/api/v1/auth/session", json={"id_token": old_id_token})
    assert r.status_code == 201 and r.json()["requires_password_change"] is True
    access = r.json()["access_token"]
    biz = await api.get("/api/v1/auth/me", headers=bearer(access))
    assert biz.status_code == 200

    r = await api.post(
        "/api/v1/auth/change-password",
        headers=bearer(access),
        json={"new_password": "brand-new-pass", "recent_id_token": provider.issue(user.firebase_uid)},
    )
    assert r.status_code == 204, r.text

    db_user = (await session.execute(select(User).where(User.user_id == user.user_id))).scalar_one()
    cred = (
        await session.execute(select(CredentialMetadata).where(CredentialMetadata.user_id == user.user_id))
    ).scalar_one()
    assert db_user.status == "ACTIVE" and db_user.first_login_required is False
    assert cred.must_change_password is False and cred.temporary_password_expires_at is None
    assert cred.password_changed_at is not None
    open_sessions = await session.scalar(
        select(func.count()).select_from(UserSession).where(
            UserSession.user_id == user.user_id, UserSession.revoked_at.is_(None)
        )
    )
    assert open_sessions == 0
    audit = (
        await session.execute(select(AuditLog).where(AuditLog.entity_id == user.user_id))
    ).scalar_one()
    assert audit.action == "auth.password_changed" and audit.new_data["status"] == "ACTIVE"
    assert "brand-new-pass" not in str(audit.new_data) + str(audit.old_data)

    stale = await api.post("/api/v1/auth/session", json={"id_token": old_id_token})
    assert (stale.status_code, stale.json()["error"]["code"]) == (401, "INVALID_ID_TOKEN")
    fresh = await login(api, provider, user, auth_time=utcnow() + timedelta(seconds=1))
    assert fresh.status_code == 201 and fresh.json()["requires_password_change"] is False


async def test_me_on_db_for_owner_and_family_admin(api, provider, world):
    clan, bo = await world.business_owner()
    fa = await world.user()
    await world.member(clan, fa)
    await world.grant(fa, "FAMILY_ADMIN", clan)
    await world.fa(clan, fa, "MEMBER_ACCOUNT_MANAGE")
    other_clan, _ = await world.business_owner("PENDING")
    await world.member(other_clan, fa)

    token = (await login(api, provider, bo)).json()["access_token"]
    [m] = (await api.get("/api/v1/auth/me", headers=bearer(token))).json()["memberships"]
    assert m["roles"] == ["BUSINESS_OWNER"] and m["permissions"] == owner_actions()

    token = (await login(api, provider, fa)).json()["access_token"]
    body = (await api.get("/api/v1/auth/me", headers=bearer(token))).json()
    by_clan = {m["clan_id"]: m for m in body["memberships"]}
    assert by_clan[str(clan.clan_id)]["permissions"] == ["MEMBER_ACCOUNT_MANAGE"]
    assert by_clan[str(other_clan.clan_id)]["permissions"] == []  # clan not ACTIVE
    assert body["permissions"] == []
