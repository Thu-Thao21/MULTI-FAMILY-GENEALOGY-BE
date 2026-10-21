"""Rate limit of POST /auth/session (Mốc H2, KI-06), over HTTP with the real middleware stack
(create_app), the real auth router and fakes: no DB, no Firebase. A fake clock, no sleeping.

- Over the limit: 429 RATE_LIMITED envelope with request_id, Retry-After, and still the no-store
  headers of the auth router (NoStoreRoute, Mốc H1), the security headers and CORS.
- The limiter runs before the Firebase ID token is verified: refused calls never reach Firebase,
  and failed logins (bad token, bad body) count.
- RATE_LIMIT_ENABLED=false never refuses; the session limiter counts apart from registration and
  track; an unknown limiter name is an error, never "no limit".
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.controllers.auth_access.router import router as auth_router
from app.controllers.family_management.public_router import router as public_router
from app.core.errors import AppError
from app.core.firebase import get_identity_provider
from app.core.rate_limit import (
    LIMITER_NAMES,
    RateLimiters,
    SlidingWindowLimiter,
    build_rate_limiters,
    rate_limited,
)
from app.core.startup_checks import find_config_problems
from app.db.postgres import get_db
from app.dependencies.auth import get_user_access_repo
from app.dependencies.permissions import get_family_repo
from app.main import create_app
from tests.fakes import FakeDb, FakeFamilyRepo, FakeIdentityProvider, FakeUserAccessRepo, make_user
from tests.guest_harness import FakeClock
from tests.test_startup_checks import make_settings

ORIGIN = "http://localhost:5173"  # in FRONTEND_ORIGINS (tests/conftest.py)
IP = "203.0.113.20"  # TEST-NET-3
OTHER_IP = "198.51.100.20"  # TEST-NET-2
SESSION_MAX = 3
SESSION_WINDOW = 600


def make_limiters(*, enabled: bool = True, clock=None, session_max: int = SESSION_MAX,
                  registration_max: int = 5, track_max: int = 20) -> RateLimiters:
    clock = clock or FakeClock()
    return RateLimiters(
        enabled=enabled,
        registration=SlidingWindowLimiter(registration_max, 3600, clock=clock),
        track=SlidingWindowLimiter(track_max, 600, clock=clock),
        session=SlidingWindowLimiter(session_max, SESSION_WINDOW, clock=clock),
    )


class World:
    def __init__(self, *, limiters: RateLimiters | None = None) -> None:
        self.clock = FakeClock()
        self.repo = FakeUserAccessRepo()
        self.family = FakeFamilyRepo(users=self.repo.users)
        self.provider = FakeIdentityProvider()
        self.verified: list[str] = []  # every ID token that reached the (fake) Firebase
        verify = self.provider.verify_id_token

        async def counting_verify(id_token: str):
            self.verified.append(id_token)
            return await verify(id_token)

        self.provider.verify_id_token = counting_verify
        self.db = FakeDb(repo=self.repo)
        app = create_app()  # the real middleware order and exception handlers
        app.include_router(auth_router, prefix="/api/v1")
        app.include_router(public_router, prefix="/api/v1")
        self.limiters = limiters or make_limiters(clock=self.clock)
        app.state.rate_limiters = self.limiters
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_user_access_repo] = lambda: self.repo
        app.dependency_overrides[get_family_repo] = lambda: self.family
        app.dependency_overrides[get_identity_provider] = lambda: self.provider
        self.app = app
        self.client = self.client_for(IP)

    def client_for(self, ip: str) -> TestClient:
        return TestClient(self.app, client=(ip, 4000))

    def login(self, client: TestClient | None = None, **headers):
        user = self.repo.add_user(make_user("ACTIVE"))
        return (client or self.client).post(
            "/api/v1/auth/session",
            json={"id_token": self.provider.issue(user.firebase_uid)},
            headers=headers,
        )

    def track(self, client: TestClient | None = None):
        return (client or self.client).post(
            "/api/v1/business-registrations/track", json={"tracking_code": "TRACK-H2-UNKNOWN-0001"}
        )


@pytest.fixture
def w() -> World:
    return World()


def request_from(ip: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": (ip, 1)})


# ----- over the limit -----


def test_the_call_over_the_limit_is_a_429_with_retry_after_no_store_and_the_security_headers(w):
    assert [w.login().status_code for _ in range(SESSION_MAX)] == [201] * SESSION_MAX
    r = w.login(**{"X-Request-ID": "h2-login-req-0001", "Origin": ORIGIN})
    assert r.status_code == 429
    assert r.json() == {"error": {
        "code": "RATE_LIMITED", "message": "Too many requests. Try again later.",
        "request_id": "h2-login-req-0001"}}
    assert r.headers["x-request-id"] == "h2-login-req-0001"
    assert r.headers["retry-after"] == str(SESSION_WINDOW)
    # NoStoreRoute (Mốc H1) covers the 429 too.
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["pragma"] == "no-cache"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    # The browser can read the 429 and its Retry-After.
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert "retry-after" in r.headers["access-control-expose-headers"].lower()
    assert "access_token" not in r.text


def test_retry_after_counts_down_and_the_window_frees_itself(w):
    for _ in range(SESSION_MAX):
        assert w.login().status_code == 201
    w.clock.advance(SESSION_WINDOW - 100)
    r = w.login()
    assert (r.status_code, r.headers["retry-after"]) == (429, "100")
    w.clock.advance(100)
    assert w.login().status_code == 201


def test_a_refused_login_never_reaches_firebase(w):
    for _ in range(SESSION_MAX + 4):
        w.login()
    assert len(w.verified) == SESSION_MAX


def test_failed_logins_and_invalid_bodies_count_too(w):
    """A password-spraying client is slowed down: bad tokens and bad bodies use up the window."""
    r = w.client.post("/api/v1/auth/session", json={"id_token": "garbage"})
    assert r.status_code == 401
    r = w.client.post("/api/v1/auth/session", json={})
    assert r.status_code == 422
    r = w.client.post("/api/v1/auth/session", json={"id_token": "garbage-again"})
    assert r.status_code == 401
    r = w.login()  # a valid token, but the window is full
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "RATE_LIMITED"


def test_the_limit_is_per_caller_address(w):
    for _ in range(SESSION_MAX):
        assert w.login().status_code == 201
    assert w.login().status_code == 429
    assert w.login(w.client_for(OTHER_IP)).status_code == 201


def test_only_the_login_is_limited_not_the_other_auth_routes(w):
    for _ in range(SESSION_MAX + 1):
        w.login()
    # /auth/me answers 401 (no token), never 429: the limiter is on POST /auth/session only.
    assert all(w.client.get("/api/v1/auth/me").status_code == 401 for _ in range(SESSION_MAX + 2))


# ----- disabled -----


def test_rate_limit_enabled_false_never_refuses_and_stores_nothing():
    settings = make_settings(RATE_LIMIT_ENABLED=False, RATE_LIMIT_SESSION_MAX=1)
    w = World(limiters=build_rate_limiters(settings, clock=FakeClock()))
    assert all(w.login().status_code == 201 for _ in range(10))
    assert len(w.limiters.session) == 0


# ----- independent of registration and track -----


def test_a_full_session_window_does_not_block_track_and_a_full_track_window_does_not_block_login():
    w = World(limiters=make_limiters(session_max=1, track_max=1))
    # Login window full: track still reaches the endpoint (404 for an unknown code, not 429).
    assert w.login().status_code == 201
    assert w.login().status_code == 429
    assert w.track().status_code == 404
    # Track window full (another caller): the login still works.
    other = w.client_for(OTHER_IP)
    assert w.track(other).status_code == 404
    assert w.track(other).status_code == 429
    assert w.login(other).status_code == 201
    assert len(w.limiters.registration) == 0


def test_the_three_limiters_count_apart():
    limiters = make_limiters(session_max=1, registration_max=1, track_max=1)
    request = request_from(IP)
    for name in LIMITER_NAMES:
        limiters.enforce(name, request)  # the first call of each passes
    for name in LIMITER_NAMES:
        with pytest.raises(AppError):
            limiters.enforce(name, request)
    assert [len(limiters.limiter(name)) for name in LIMITER_NAMES] == [1, 1, 1]


# ----- unknown names are errors -----


@pytest.mark.parametrize("enabled", [True, False])
def test_enforce_with_an_unknown_name_is_an_error_even_when_disabled(enabled):
    limiters = make_limiters(enabled=enabled)
    with pytest.raises(ValueError, match="unknown rate limiter 'login'"):
        limiters.enforce("login", request_from(IP))
    with pytest.raises(ValueError):
        limiters.limiter("Session")


def test_declaring_a_route_with_an_unknown_limiter_fails_at_once():
    with pytest.raises(ValueError, match="unknown rate limiter 'sesion'"):
        rate_limited("sesion")


# ----- configuration -----


def test_the_session_limiter_reads_its_settings():
    limiters = build_rate_limiters(make_settings())
    assert (limiters.session.limit, limiters.session.window) == (20, 600.0)
    limiters = build_rate_limiters(
        make_settings(RATE_LIMIT_SESSION_MAX=500, RATE_LIMIT_SESSION_WINDOW_SECONDS=60)
    )
    assert (limiters.session.limit, limiters.session.window) == (500, 60.0)
    # registration and track keep their defaults
    assert (limiters.registration.limit, limiters.registration.window) == (5, 3600.0)
    assert (limiters.track.limit, limiters.track.window) == (20, 600.0)


@pytest.mark.parametrize("name", ["RATE_LIMIT_SESSION_MAX", "RATE_LIMIT_SESSION_WINDOW_SECONDS"])
def test_a_non_positive_session_setting_stops_the_startup(name):
    problems = find_config_problems(make_settings(**{name: 0}), {})
    assert problems == [f"{name} must be a positive integer"]
