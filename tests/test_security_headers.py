"""Response security headers (Mốc H1) over HTTP with the real middleware stack (create_app) and
fakes: no DB, no Firebase.

- L-26: every response of the auth router, success or error, is Cache-Control: no-store and
  Pragma: no-cache.
- SecurityHeadersMiddleware: X-Content-Type-Options, X-Frame-Options and Referrer-Policy on every
  response, including the 500 envelope of UnhandledErrorMiddleware and a CORS preflight, without
  replacing a header a handler set.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Response
from fastapi.testclient import TestClient

from app.routers import health
from app.controllers.auth_access.router import router as auth_router
from app.controllers.family_management.public_router import router as public_router
from app.core.integrations.firebase import get_identity_provider
from app.core.security.tokens import hash_tracking_code
from app.db.postgres import get_db
from app.dependencies.auth import get_user_access_repo
from app.dependencies.permissions import get_family_repo
from app.main import create_app
from tests.fakes import FakeDb, FakeFamilyRepo, FakeIdentityProvider, FakeUserAccessRepo, make_user

ORIGIN = "http://localhost:5173"  # in FRONTEND_ORIGINS (tests/conftest.py)
SECURITY = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
}


class World:
    def __init__(self) -> None:
        self.repo = FakeUserAccessRepo()
        self.family = FakeFamilyRepo(users=self.repo.users)
        self.provider = FakeIdentityProvider()
        self.db = FakeDb(repo=self.repo)
        app = create_app()  # the real middleware order and exception handlers
        app.include_router(health.router, prefix="/api")
        app.include_router(auth_router, prefix="/api/v1")
        app.include_router(public_router, prefix="/api/v1")

        @app.get("/api/v1/_test/boom")
        async def boom():
            raise RuntimeError("simulated bug")

        @app.get("/api/v1/_test/framed")
        async def framed():
            return Response(headers={"X-Frame-Options": "SAMEORIGIN"})

        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_user_access_repo] = lambda: self.repo
        app.dependency_overrides[get_family_repo] = lambda: self.family
        app.dependency_overrides[get_identity_provider] = lambda: self.provider
        self.app = app
        self.client = TestClient(app)

    def user(self):
        return self.repo.add_user(make_user("ACTIVE"))

    def login(self, user):
        return self.client.post(
            "/api/v1/auth/session", json={"id_token": self.provider.issue(user.firebase_uid)}
        )

    def token(self, user) -> str:
        now = datetime.now(timezone.utc)
        return self.repo.seed_session(
            user, token="tok-h1-" + user.firebase_uid, created_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(hours=8),
        )


@pytest.fixture
def w() -> World:
    return World()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_no_store(r) -> None:
    assert r.headers["cache-control"] == "no-store", r.headers
    assert r.headers["pragma"] == "no-cache", r.headers


def assert_security_headers(r) -> None:
    for name, value in SECURITY.items():
        assert r.headers.get(name) == value, (name, r.headers)


# ----- auth router: no-store on success and on error (L-26) -----


def test_session_201_with_the_access_token_is_no_store(w):
    r = w.login(w.user())
    assert r.status_code == 201 and "access_token" in r.json()
    assert_no_store(r)
    assert_security_headers(r)


def test_session_401_is_no_store(w):
    r = w.client.post("/api/v1/auth/session", json={"id_token": "garbage"})
    assert (r.status_code, r.json()["error"]["code"]) == (401, "INVALID_ID_TOKEN")
    assert_no_store(r)


def test_session_422_validation_error_is_no_store(w):
    r = w.client.post("/api/v1/auth/session", json={})
    assert r.status_code == 422
    assert_no_store(r)


def test_me_is_no_store_on_200_and_on_401(w):
    user = w.user()
    r = w.client.get("/api/v1/auth/me", headers=bearer(w.token(user)))
    assert r.status_code == 200
    assert_no_store(r)
    r = w.client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert_no_store(r)


def test_logout_is_no_store_on_204_and_on_401(w):
    user = w.user()
    r = w.client.post("/api/v1/auth/logout", headers=bearer(w.token(user)))
    assert r.status_code == 204
    assert_no_store(r)
    r = w.client.post("/api/v1/auth/logout")
    assert r.status_code == 401
    assert_no_store(r)


def test_change_password_error_is_no_store(w):
    user = w.user()
    r = w.client.post("/api/v1/auth/change-password", headers=bearer(w.token(user)), json={})
    assert r.status_code == 422
    assert_no_store(r)


def test_an_unhandled_error_in_an_auth_route_is_a_500_still_no_store_and_with_cors(w):
    def broken_repo():
        raise RuntimeError("simulated bug")

    w.app.dependency_overrides[get_user_access_repo] = broken_repo
    r = w.client.post(
        "/api/v1/auth/session", json={"id_token": "anything"}, headers={"Origin": ORIGIN}
    )
    assert (r.status_code, r.json()["error"]["code"]) == (500, "INTERNAL_ERROR")
    assert "simulated bug" not in r.text
    assert_no_store(r)
    assert_security_headers(r)
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert r.headers["x-request-id"] == r.json()["error"]["request_id"]


# ----- security headers on every response -----


def test_health_has_the_security_headers_and_no_hsts(w):
    r = w.client.get("/api/health")
    assert r.status_code == 200
    assert_security_headers(r)
    assert "strict-transport-security" not in r.headers


def test_service_plans_have_the_security_headers(w):
    w.family.add_plan("TEST-H1")
    r = w.client.get("/api/v1/service-plans")
    assert r.status_code == 200 and r.json()["items"]
    assert_security_headers(r)
    # Not an auth route: not forced to no-store.
    assert "pragma" not in r.headers


def test_a_500_envelope_has_the_security_headers_and_the_cors_headers(w):
    r = w.client.get("/api/v1/_test/boom", headers={"Origin": ORIGIN})
    assert (r.status_code, r.json()["error"]["code"]) == (500, "INTERNAL_ERROR")
    assert_security_headers(r)
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert r.headers["x-request-id"] == r.json()["error"]["request_id"]


def test_a_cors_preflight_has_the_security_headers(w):
    r = w.client.options(
        "/api/v1/auth/session",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert_security_headers(r)
    assert "x-request-id" in r.headers


def test_a_header_set_by_the_handler_is_not_replaced(w):
    r = w.client.get("/api/v1/_test/framed")
    assert r.status_code == 200
    assert r.headers.get_list("x-frame-options") == ["SAMEORIGIN"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_a_404_has_the_security_headers(w):
    r = w.client.get("/api/v1/no-such-route")
    assert r.status_code == 404
    assert_security_headers(r)


# ----- family_management keeps its own no-store unchanged -----


def test_family_management_no_store_is_unchanged(w):
    plan = w.family.add_plan("TEST-H1")
    registration = w.family.add_registration(plan)
    registration.tracking_code_hash = hash_tracking_code("TRACK-H1-0001")
    r = w.client.post(
        "/api/v1/business-registrations/track", json={"tracking_code": "TRACK-H1-0001"}
    )
    assert r.status_code == 200, r.text
    assert r.headers.get_list("cache-control") == ["no-store"]
    assert "pragma" not in r.headers  # H1 only adds Pragma on the auth router
    assert_security_headers(r)
