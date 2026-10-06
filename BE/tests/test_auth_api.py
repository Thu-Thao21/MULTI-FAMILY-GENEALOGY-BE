"""Auth API (Mốc D) over HTTP with the real router and fakes: no DB, no Firebase."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controllers.auth_access.router import router
from app.core.errors import register_exception_handlers
from app.core.firebase import PasswordRejected, ProviderUnavailable, get_identity_provider
from app.core.request_id import RequestIdMiddleware
from app.db.postgres import get_db
from app.dependencies.auth import get_user_access_repo
from app.dependencies.permissions import get_family_repo, owner_actions, system_admin_actions
from tests.fakes import FakeDb, FakeFamilyRepo, FakeIdentityProvider, FakeUserAccessRepo, make_user


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class World:
    def __init__(self) -> None:
        self.repo = FakeUserAccessRepo()
        self.family = FakeFamilyRepo()
        self.provider = FakeIdentityProvider()
        self.db = FakeDb(repo=self.repo)
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)
        register_exception_handlers(app)
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_user_access_repo] = lambda: self.repo
        app.dependency_overrides[get_family_repo] = lambda: self.family
        app.dependency_overrides[get_identity_provider] = lambda: self.provider
        self.client = TestClient(app)

    def user(self, status="ACTIVE", **cred):
        user = self.repo.add_user(make_user(status, first_login_required=cred.pop("first_login", False)))
        if cred:
            self.repo.set_cred(user, **cred)
        return user

    def login(self, user, **kw):
        return self.client.post("/api/v1/auth/session", json={"id_token": self.provider.issue(user.firebase_uid, **kw)})

    def token_for(self, user) -> str:
        r = self.login(user)
        assert r.status_code == 201, r.text
        return r.json()["access_token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def code(r):
    return r.json()["error"]["code"]


@pytest.fixture
def w() -> World:
    return World()


def restricted_cred(**extra):
    return dict(must_change_password=True, temporary_password_expires_at=utcnow() + timedelta(days=1), **extra)


# ----- POST /auth/session -----


def test_login_creates_session_and_returns_token_once(w):
    user = w.user()
    r = w.login(user)
    assert r.status_code == 201
    body = r.json()
    token = body["access_token"]
    assert body["token_type"] == "Bearer"
    assert body["requires_password_change"] is False
    assert body["user"] == {
        "user_id": str(user.user_id), "display_name": user.display_name,
        "email": user.email, "status": "ACTIVE",
    }
    assert body["expires_at"].endswith("Z")
    expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert timedelta(hours=7, minutes=59) < expires - utcnow() <= timedelta(hours=8)
    # Only SHA-256 is stored; the raw token is never a key or a value.
    stored = list(w.repo.sessions.values())
    assert [s.token_jti_hash for s in stored] == [hashlib.sha256(token.encode()).hexdigest()]
    assert token not in w.repo.sessions
    assert user.last_login_at is not None
    assert [(h.success, h.failure_reason) for h in w.repo.login_history] == [(True, None)]
    assert w.db.commits == 1
    assert "firebase_uid" not in r.text


def test_session_token_works_on_auth_me(w):
    user = w.user()
    r = w.client.get("/api/v1/auth/me", headers=bearer(w.token_for(user)))
    assert r.status_code == 200 and r.json()["user_id"] == str(user.user_id)


def test_invalid_id_token_is_401_and_not_written(w):
    users_before = dict(w.repo.users)
    r = w.client.post("/api/v1/auth/session", json={"id_token": "garbage"})
    assert (r.status_code, code(r)) == (401, "INVALID_ID_TOKEN")
    assert w.repo.login_history == [] and w.repo.sessions == {} and w.repo.users == users_before


def test_provider_unavailable_is_503(w):
    user = w.user()
    w.provider.unavailable = True
    r = w.login(user)
    assert (r.status_code, code(r)) == (503, "PROVIDER_UNAVAILABLE")


def test_unknown_uid_is_rejected_without_creating_a_user(w):
    w.user()
    users_before = dict(w.repo.users)
    token = w.provider.issue("uid-nobody-knows")
    r = w.client.post("/api/v1/auth/session", json={"id_token": token})
    assert (r.status_code, code(r)) == (401, "INVALID_ID_TOKEN")
    # Same answer as a bad token (no enumeration), nothing created, nothing in the DB.
    assert r.json()["error"]["message"] == w.client.post(
        "/api/v1/auth/session", json={"id_token": "garbage"}
    ).json()["error"]["message"]
    assert w.repo.users == users_before
    assert w.repo.sessions == {} and w.repo.login_history == [] and w.db.commits == 0


def test_same_email_different_uid_is_not_linked(w):
    user = w.user()
    token = w.provider.issue("another-uid", email=user.email)
    r = w.client.post("/api/v1/auth/session", json={"id_token": token})
    assert (r.status_code, code(r)) == (401, "INVALID_ID_TOKEN")
    assert w.repo.sessions == {}


@pytest.mark.parametrize("status", ["LOCKED", "SUSPENDED", "DISABLED"])
def test_blocked_user_failure_is_committed_before_the_error(w, status):
    user = w.user(status)
    r = w.login(user)
    assert (r.status_code, code(r)) == (403, "ACCOUNT_BLOCKED")
    assert w.repo.sessions == {}
    # The failure row was committed (snapshot taken at commit), not just added.
    assert [(h.user_id, h.success, h.failure_reason) for h in w.db.committed_login_history] == [
        (user.user_id, False, "ACCOUNT_BLOCKED")
    ]


def test_pending_without_password_flag_is_blocked(w):
    r = w.login(w.user("PENDING"))
    assert (r.status_code, code(r)) == (403, "ACCOUNT_BLOCKED")


def test_expired_temporary_password_is_403_and_logged(w):
    user = w.user("PENDING", must_change_password=True,
                  temporary_password_expires_at=utcnow() - timedelta(minutes=1))
    r = w.login(user)
    assert (r.status_code, code(r)) == (403, "TEMPORARY_PASSWORD_EXPIRED")
    assert [h.failure_reason for h in w.db.committed_login_history] == ["TEMPORARY_PASSWORD_EXPIRED"]


def test_id_token_older_than_password_change_is_rejected(w):
    user = w.user(password_changed_at=utcnow() - timedelta(minutes=5))
    r = w.login(user, auth_time=utcnow() - timedelta(minutes=10))
    assert (r.status_code, code(r)) == (401, "INVALID_ID_TOKEN")
    assert [h.failure_reason for h in w.db.committed_login_history] == [
        "ID_TOKEN_BEFORE_PASSWORD_CHANGE"
    ]
    assert w.repo.sessions == {}
    # Signing in again after the change is fine.
    assert w.login(user, auth_time=utcnow() - timedelta(seconds=5)).status_code == 201


def test_pending_user_with_temporary_password_gets_restricted_session(w):
    r = w.login(w.user("PENDING", **restricted_cred()))
    assert r.status_code == 201 and r.json()["requires_password_change"] is True


@pytest.mark.parametrize("body", [{}, {"id_token": ""}, {"id_token": "x", "extra": 1}])
def test_session_body_validation(w, body):
    r = w.client.post("/api/v1/auth/session", json=body)
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")


def test_no_token_or_uid_in_logs(w, caplog):
    caplog.set_level(logging.DEBUG)
    blocked = w.user("LOCKED")
    id_token = w.provider.issue(blocked.firebase_uid)
    w.client.post("/api/v1/auth/session", json={"id_token": id_token})
    w.client.post("/api/v1/auth/session", json={"id_token": "garbage-secret-token"})
    ok = w.user()
    ok_id_token = w.provider.issue(ok.firebase_uid)
    access = w.client.post("/api/v1/auth/session", json={"id_token": ok_id_token}).json()["access_token"]
    text = caplog.text
    for secret in (id_token, ok_id_token, "garbage-secret-token", access, blocked.firebase_uid,
                   ok.firebase_uid, blocked.email):
        assert secret not in text


# ----- GET /auth/me -----


def test_me_for_system_admin_business_owner_and_family_admin(w):
    sa, bo, fa = w.user(), w.user(), w.user()
    w.repo.grant(sa, "SYSTEM_ADMIN")
    clan = w.family.add_clan("ACTIVE")
    w.repo.grant(bo, "BUSINESS_OWNER", clan.clan_id)
    w.family.add_owner(clan, bo)
    w.family.add_member(clan, bo)
    w.family.add_member(clan, fa)
    w.repo.grant(fa, "FAMILY_ADMIN", clan.clan_id)
    w.family.add_fa(clan, fa, "MEMBER_ACCOUNT_MANAGE")

    me_sa = w.client.get("/api/v1/auth/me", headers=bearer(w.token_for(sa))).json()
    assert me_sa["permissions"] == system_admin_actions() and me_sa["memberships"] == []

    me_bo = w.client.get("/api/v1/auth/me", headers=bearer(w.token_for(bo))).json()
    assert me_bo["permissions"] == []
    [m] = me_bo["memberships"]
    assert m["clan_id"] == str(clan.clan_id) and m["roles"] == ["BUSINESS_OWNER"]
    assert m["permissions"] == owner_actions()

    me_fa = w.client.get("/api/v1/auth/me", headers=bearer(w.token_for(fa))).json()
    [m] = me_fa["memberships"]
    assert m["roles"] == ["FAMILY_ADMIN"] and m["permissions"] == ["MEMBER_ACCOUNT_MANAGE"]


def test_me_lists_roles_but_no_permissions_when_clan_not_active(w):
    bo = w.user()
    clan = w.family.add_clan("PENDING")
    w.repo.grant(bo, "BUSINESS_OWNER", clan.clan_id)
    w.family.add_owner(clan, bo)
    w.family.add_member(clan, bo)
    [m] = w.client.get("/api/v1/auth/me", headers=bearer(w.token_for(bo))).json()["memberships"]
    assert m["clan_status"] == "PENDING" and m["roles"] == ["BUSINESS_OWNER"] and m["permissions"] == []


def test_me_works_for_restricted_session(w):
    user = w.user("PENDING", **restricted_cred())
    r = w.client.get("/api/v1/auth/me", headers=bearer(w.token_for(user)))
    assert r.status_code == 200 and r.json()["requires_password_change"] is True


# ----- POST /auth/logout -----


def test_logout_revokes_the_current_session_only(w):
    user = w.user()
    t1, t2 = w.token_for(user), w.token_for(user)
    r = w.client.post("/api/v1/auth/logout", headers=bearer(t1))
    assert r.status_code == 204 and r.content == b""
    again = w.client.get("/api/v1/auth/me", headers=bearer(t1))
    assert (again.status_code, code(again)) == (401, "SESSION_INVALID")
    assert w.client.get("/api/v1/auth/me", headers=bearer(t2)).status_code == 200


def test_logout_without_token_is_401(w):
    r = w.client.post("/api/v1/auth/logout")
    assert (r.status_code, code(r)) == (401, "UNAUTHENTICATED")


# ----- POST /auth/change-password -----


def change(w, access, recent, password="new-password-123"):
    return w.client.post(
        "/api/v1/auth/change-password",
        headers=bearer(access),
        json={"new_password": password, "recent_id_token": recent},
    )


def test_first_password_change_activates_account_and_revokes_sessions(w):
    user = w.user("PENDING", first_login=True, **restricted_cred())
    old_id_token = w.provider.issue(user.firebase_uid, auth_time=utcnow() - timedelta(seconds=60))
    access = w.client.post("/api/v1/auth/session", json={"id_token": old_id_token}).json()["access_token"]
    other = w.token_for(user)

    r = change(w, access, w.provider.issue(user.firebase_uid))
    assert r.status_code == 204
    assert w.provider.password_changes == [user.firebase_uid]
    cred = w.repo.creds[user.user_id]
    assert user.status == "ACTIVE" and user.first_login_required is False
    assert cred.must_change_password is False and cred.temporary_password_expires_at is None
    assert cred.password_changed_at is not None
    for token in (access, other):  # every app session is gone
        assert code(w.client.get("/api/v1/auth/me", headers=bearer(token))) == "SESSION_INVALID"
    # The ID token from before the change can no longer be exchanged...
    r = w.client.post("/api/v1/auth/session", json={"id_token": old_id_token})
    assert (r.status_code, code(r)) == (401, "INVALID_ID_TOKEN")
    # ...a fresh sign-in can, and the session is no longer restricted.
    fresh = w.login(user, auth_time=utcnow() + timedelta(seconds=1))
    assert fresh.status_code == 201 and fresh.json()["requires_password_change"] is False
    assert w.repo.audit[-1]["action"] == "auth.password_changed"
    assert w.repo.audit[-1]["old_data"] == {"status": "PENDING"}
    assert "new-password-123" not in str(w.repo.audit)


def test_change_password_rejects_token_of_another_user(w):
    user, other = w.user(), w.user()
    r = change(w, w.token_for(user), w.provider.issue(other.firebase_uid))
    assert (r.status_code, code(r)) == (401, "RECENT_LOGIN_REQUIRED")
    assert w.provider.password_changes == []


def test_change_password_requires_recent_sign_in(w):
    user = w.user()
    stale = w.provider.issue(user.firebase_uid, auth_time=utcnow() - timedelta(seconds=301))
    r = change(w, w.token_for(user), stale)
    assert (r.status_code, code(r)) == (401, "RECENT_LOGIN_REQUIRED")
    assert w.provider.password_changes == []


def test_change_password_with_invalid_recent_token(w):
    r = change(w, w.token_for(w.user()), "garbage")
    assert (r.status_code, code(r)) == (401, "RECENT_LOGIN_REQUIRED")


def test_change_password_provider_down_changes_nothing(w):
    user = w.user("PENDING", **restricted_cred())
    access = w.token_for(user)
    w.provider.set_password_error = ProviderUnavailable("down")
    r = change(w, access, w.provider.issue(user.firebase_uid))
    assert (r.status_code, code(r)) == (503, "PROVIDER_UNAVAILABLE")
    assert user.status == "PENDING" and w.repo.creds[user.user_id].must_change_password is True
    assert w.client.get("/api/v1/auth/me", headers=bearer(access)).status_code == 200


def test_change_password_policy_rejection_is_422(w):
    user = w.user()
    w.provider.set_password_error = PasswordRejected()
    r = change(w, w.token_for(user), w.provider.issue(user.firebase_uid))
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")
    assert "new-password-123" not in r.text


def test_change_password_db_failure_after_firebase_is_503_with_request_id(w):
    user = w.user("PENDING", **restricted_cred())
    access = w.token_for(user)
    w.db.fail_commit = True
    r = change(w, access, w.provider.issue(user.firebase_uid))
    assert (r.status_code, code(r)) == (503, "DATABASE_UNAVAILABLE")
    assert r.json()["error"]["request_id"] == r.headers["X-Request-ID"]
    assert w.provider.password_changes == [user.firebase_uid] and w.db.rollbacks == 1


def test_change_password_too_short_never_reaches_firebase(w):
    user = w.user()
    r = change(w, w.token_for(user), w.provider.issue(user.firebase_uid), password="12345")
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")
    assert "12345" not in r.text and w.provider.password_changes == []


def test_restricted_session_still_blocked_on_business_routes_by_dependency():
    """Covered in test_auth_dependency.py; listed here so the Mốc D surface is complete."""
    from app.dependencies.auth import RESTRICTED_ALLOWED_PATHS

    assert RESTRICTED_ALLOWED_PATHS == {
        "/api/v1/auth/me", "/api/v1/auth/change-password", "/api/v1/auth/logout"
    }
