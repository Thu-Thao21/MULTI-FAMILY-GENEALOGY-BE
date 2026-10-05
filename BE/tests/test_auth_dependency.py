from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.errors import AppError, register_exception_handlers
from app.core.request_id import RequestIdMiddleware
from app.core.tokens import hash_session_token
from app.dependencies.auth import (
    Principal,
    get_principal,
    get_principal_allow_restricted,
    get_user_access_repo,
    resolve_principal,
)
from app.schemas.errors import ErrorCode
from tests.fakes import NOW, FakeUserAccessRepo, make_user


async def _resolve(repo, token="tok-valid"):
    return await resolve_principal(token, repo, now=NOW)


async def _code(repo, token="tok-valid") -> ErrorCode:
    with pytest.raises(AppError) as exc:
        await _resolve(repo, token)
    return exc.value.code


# ----- resolve_principal -----


async def test_active_session_gives_unrestricted_principal():
    repo = FakeUserAccessRepo()
    user = repo.add_user(make_user())
    repo.add_session(user)
    p = await _resolve(repo)
    assert p.user_id == user.user_id and p.requires_password_change is False


async def test_only_token_hash_is_looked_up():
    repo = FakeUserAccessRepo()
    repo.add_session(repo.add_user(make_user()), "raw-secret-token")
    await _resolve(repo, "raw-secret-token")
    assert repo.seen_hashes == [hash_session_token("raw-secret-token")]
    assert "raw-secret-token" not in repo.seen_hashes


async def test_unknown_token_is_session_invalid():
    repo = FakeUserAccessRepo()
    assert await _code(repo, "nope") is ErrorCode.SESSION_INVALID


async def test_revoked_session_is_session_invalid():
    repo = FakeUserAccessRepo()
    repo.add_session(repo.add_user(make_user()), revoked_at=NOW - timedelta(minutes=1))
    assert await _code(repo) is ErrorCode.SESSION_INVALID


async def test_expired_session_is_session_invalid():
    repo = FakeUserAccessRepo()
    repo.add_session(repo.add_user(make_user()), expires_at=NOW)
    assert await _code(repo) is ErrorCode.SESSION_INVALID


async def test_session_older_than_password_change_is_invalid():
    repo = FakeUserAccessRepo()
    user = repo.add_user(make_user())
    repo.add_session(user, created_at=NOW - timedelta(hours=2))
    repo.set_cred(user, password_changed_at=NOW - timedelta(hours=1))
    assert await _code(repo) is ErrorCode.SESSION_INVALID


@pytest.mark.parametrize("status", ["LOCKED", "SUSPENDED", "DISABLED", "SOMETHING_ELSE"])
async def test_blocked_status_is_account_blocked(status):
    repo = FakeUserAccessRepo()
    repo.add_session(repo.add_user(make_user(status)))
    assert await _code(repo) is ErrorCode.ACCOUNT_BLOCKED


async def test_pending_without_password_flag_is_blocked():
    repo = FakeUserAccessRepo()
    repo.add_session(repo.add_user(make_user("PENDING")))
    assert await _code(repo) is ErrorCode.ACCOUNT_BLOCKED


async def test_pending_with_temporary_password_is_restricted():
    repo = FakeUserAccessRepo()
    user = repo.add_user(make_user("PENDING"))
    repo.add_session(user)
    repo.set_cred(user, must_change_password=True,
                  temporary_password_expires_at=NOW + timedelta(days=1))
    p = await _resolve(repo)
    assert p.requires_password_change is True and p.status == "PENDING"


async def test_first_login_required_is_restricted():
    repo = FakeUserAccessRepo()
    repo.add_session(repo.add_user(make_user(first_login_required=True)))
    assert (await _resolve(repo)).requires_password_change is True


async def test_expired_temporary_password():
    repo = FakeUserAccessRepo()
    user = repo.add_user(make_user("PENDING"))
    repo.add_session(user)
    repo.set_cred(user, must_change_password=True, temporary_password_expires_at=NOW)
    assert await _code(repo) is ErrorCode.TEMPORARY_PASSWORD_EXPIRED


async def test_expired_temp_timestamp_ignored_when_change_not_required():
    repo = FakeUserAccessRepo()
    user = repo.add_user(make_user())
    repo.add_session(user)
    repo.set_cred(user, must_change_password=False,
                  temporary_password_expires_at=NOW - timedelta(days=3))
    assert (await _resolve(repo)).requires_password_change is False


async def test_blocked_wins_over_expired_temporary_password():
    repo = FakeUserAccessRepo()
    user = repo.add_user(make_user("LOCKED"))
    repo.add_session(user)
    repo.set_cred(user, must_change_password=True,
                  temporary_password_expires_at=NOW - timedelta(days=1))
    assert await _code(repo) is ErrorCode.ACCOUNT_BLOCKED


# ----- FastAPI dependencies -----


def _client(repo: FakeUserAccessRepo) -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    @app.get("/api/v1/auth/me")
    async def me(p: Principal = Depends(get_principal_allow_restricted)):
        return {"restricted": p.requires_password_change}

    @app.get("/api/v1/business-thing")
    async def business(p: Principal = Depends(get_principal)):
        return {"ok": True}

    # Misuse on purpose: allow_restricted attached to a business route.
    @app.get("/api/v1/misattached")
    async def misattached(p: Principal = Depends(get_principal_allow_restricted)):
        return {"ok": True}

    app.dependency_overrides[get_user_access_repo] = lambda: repo
    return TestClient(app)


def _restricted_repo() -> FakeUserAccessRepo:
    # Real clock is used by the HTTP path, so expiries are relative to "now".
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    repo = FakeUserAccessRepo()
    user = repo.add_user(make_user("PENDING"))
    repo.add_session(user, created_at=now - timedelta(minutes=5),
                     expires_at=now + timedelta(hours=8))
    repo.set_cred(user, must_change_password=True,
                  temporary_password_expires_at=now + timedelta(days=1))
    return repo


def _active_repo() -> FakeUserAccessRepo:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    repo = FakeUserAccessRepo()
    user = repo.add_user(make_user())
    repo.add_session(user, created_at=now - timedelta(minutes=5),
                     expires_at=now + timedelta(hours=8))
    return repo


AUTH = {"Authorization": "Bearer tok-valid"}


def test_missing_bearer_is_unauthenticated():
    r = _client(_active_repo()).get("/api/v1/business-thing")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"
    assert r.headers["www-authenticate"] == "Bearer"


def test_invalid_bearer_is_401_session_invalid():
    r = _client(_active_repo()).get("/api/v1/business-thing", headers={"Authorization": "Bearer x"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "SESSION_INVALID"


def test_restricted_session_allowed_on_auth_me():
    r = _client(_restricted_repo()).get("/api/v1/auth/me", headers=AUTH)
    assert r.status_code == 200 and r.json() == {"restricted": True}


def test_restricted_session_blocked_on_business_route():
    r = _client(_restricted_repo()).get("/api/v1/business-thing", headers=AUTH)
    assert r.status_code == 403 and r.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"


def test_path_check_is_defense_in_depth_for_misattached_dependency():
    r = _client(_restricted_repo()).get("/api/v1/misattached", headers=AUTH)
    assert r.status_code == 403 and r.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"


def test_active_session_on_business_route():
    r = _client(_active_repo()).get("/api/v1/business-thing", headers=AUTH)
    assert r.status_code == 200
