"""Session resolution on the real DB: expiry, revoke, blocked users, token hashing."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import MultipleResultsFound

from app.core.errors import AppError
from app.dependencies.auth import resolve_principal
from app.models.user_access.entities import UserSession
from app.models.user_access.repository import UserAccessRepository
from app.schemas.errors import ErrorCode
from tests.integration.factory import now


async def _resolve(session, token):
    return await resolve_principal(token, UserAccessRepository(session))


async def _code(session, token) -> ErrorCode:
    with pytest.raises(AppError) as exc:
        await _resolve(session, token)
    return exc.value.code


async def test_valid_session_gives_unrestricted_principal(session, world):
    user = await world.user()
    token = await world.session_for(user)
    p = await _resolve(session, token)
    assert p.user_id == user.user_id
    assert p.requires_password_change is False


async def test_token_is_stored_as_sha256_not_raw(session, world):
    user = await world.user()
    token = await world.session_for(user)
    row = (
        await session.execute(select(UserSession).where(UserSession.user_id == user.user_id))
    ).scalar_one()
    assert row.token_jti_hash == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert len(row.token_jti_hash) == 64 and row.token_jti_hash != token
    # The raw token is not a lookup key; only its hash is.
    assert await UserAccessRepository(session).get_session_by_token_hash(token) is None


async def test_unknown_token_is_session_invalid(session):
    assert await _code(session, "no-such-token") is ErrorCode.SESSION_INVALID


async def test_expired_session_is_session_invalid(session, world):
    user = await world.user()
    token = await world.session_for(user, created_ago=timedelta(hours=9), expires_in=timedelta(hours=-1))
    assert await _code(session, token) is ErrorCode.SESSION_INVALID


async def test_revoked_session_is_session_invalid(session, world):
    user = await world.user()
    token = await world.session_for(user, revoked=True)
    assert await _code(session, token) is ErrorCode.SESSION_INVALID


async def test_active_session_query_excludes_revoked_and_expired(session, world):
    repo = UserAccessRepository(session)
    user = await world.user()
    from app.core.tokens import hash_session_token

    ok = await world.session_for(user)
    revoked = await world.session_for(user, revoked=True)
    expired = await world.session_for(user, created_ago=timedelta(hours=9), expires_in=timedelta(hours=-1))
    assert await repo.get_active_session_by_token_hash(hash_session_token(ok)) is not None
    assert await repo.get_active_session_by_token_hash(hash_session_token(revoked)) is None
    assert await repo.get_active_session_by_token_hash(hash_session_token(expired)) is None


async def test_session_created_before_password_change_is_invalid(session, world):
    user = await world.user(
        cred=dict(must_change_password=False, failed_login_count=0, password_changed_at=now())
    )
    old = await world.session_for(user, created_ago=timedelta(minutes=10))
    assert await _code(session, old) is ErrorCode.SESSION_INVALID


async def test_session_created_after_password_change_is_valid(session, world):
    user = await world.user(
        cred=dict(
            must_change_password=False,
            failed_login_count=0,
            password_changed_at=now() - timedelta(hours=1),
        )
    )
    token = await world.session_for(user, created_ago=timedelta(minutes=10))
    assert (await _resolve(session, token)).user_id == user.user_id


@pytest.mark.parametrize("status", ["LOCKED", "SUSPENDED", "DISABLED"])
async def test_blocked_user_is_account_blocked(session, world, status):
    user = await world.user(status)
    token = await world.session_for(user)
    assert await _code(session, token) is ErrorCode.ACCOUNT_BLOCKED


async def test_pending_user_without_password_flag_is_blocked(session, world):
    user = await world.user("PENDING")
    token = await world.session_for(user)
    assert await _code(session, token) is ErrorCode.ACCOUNT_BLOCKED


async def test_pending_user_with_temporary_password_gets_restricted_principal(session, world):
    user = await world.user(
        "PENDING",
        cred=dict(
            must_change_password=True,
            failed_login_count=0,
            temporary_password_expires_at=now() + timedelta(days=1),
        ),
    )
    token = await world.session_for(user)
    assert (await _resolve(session, token)).requires_password_change is True


async def test_first_login_required_gives_restricted_principal(session, world):
    user = await world.user(first_login_required=True)
    token = await world.session_for(user)
    assert (await _resolve(session, token)).requires_password_change is True


async def test_expired_temporary_password(session, world):
    user = await world.user(
        "PENDING",
        cred=dict(
            must_change_password=True,
            failed_login_count=0,
            temporary_password_expires_at=now() - timedelta(minutes=1),
        ),
    )
    token = await world.session_for(user)
    assert await _code(session, token) is ErrorCode.TEMPORARY_PASSWORD_EXPIRED


async def test_expired_temporary_timestamp_ignored_when_change_not_required(session, world):
    user = await world.user(
        cred=dict(
            must_change_password=False,
            failed_login_count=0,
            temporary_password_expires_at=now() - timedelta(days=3),
        )
    )
    token = await world.session_for(user)
    assert (await _resolve(session, token)).requires_password_change is False


async def test_db_does_not_enforce_unique_token_hash_known_issue(session, world):
    """Documents KI-04: user_sessions.token_jti_hash has no unique index.

    A duplicate hash is accepted by the DB, and the lookup then raises. Tokens are 256-bit
    random so a real collision is not expected; the point is that the DB cannot prevent it.
    """
    from app.core.tokens import hash_session_token

    a, b = await world.user(), await world.user()
    token = await world.session_for(a)
    await world.session_for(b, token=token)  # same token -> same hash, no IntegrityError
    with pytest.raises(MultipleResultsFound):
        await UserAccessRepository(session).get_session_by_token_hash(hash_session_token(token))
