"""Shared harness for the public (Guest) endpoints: the real router, the real error handlers,
fake repositories, a fake clock for the rate limiter. No database, no Firebase."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controllers.family_management.public_router import router
from app.core.errors import register_exception_handlers
from app.core.rate_limit import RateLimiters, SlidingWindowLimiter
from app.core.request_id import RequestIdMiddleware
from app.db.postgres import get_db
from app.dependencies.auth import get_user_access_repo
from app.dependencies.permissions import get_family_repo
from tests.fakes import FakeDb, FakeFamilyRepo, FakeUserAccessRepo

PREFIX = "/api/v1"
DEFAULT_IP = "203.0.113.7"  # TEST-NET-3: a documentation address


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def reg_body(**overrides) -> dict:
    """A valid registration body; every call has its own e-mail and clan name."""
    tag = uuid.uuid4().hex[:10]
    body = {
        "representative_name": "Nguyen Van A",
        "representative_email": f"applicant-{tag}@example.test",
        "clan_name": f"Ho Nguyen {tag}",
        "requested_plan_id": None,  # filled by GuestWorld.register
    }
    body.update(overrides)
    return body


class GuestWorld:
    def __init__(
        self,
        *,
        registration_max: int = 5,
        registration_window: int = 3600,
        track_max: int = 20,
        track_window: int = 600,
        max_keys: int = 10_000,
        enabled: bool = True,
        trust_proxy_headers: bool = False,
        trusted_proxy_count: int = 1,
        raise_server_exceptions: bool = True,
    ) -> None:
        self.clock = FakeClock()
        self.repo = FakeUserAccessRepo()
        self.family = FakeFamilyRepo(users=self.repo.users)
        self.db = FakeDb(repo=self.repo)
        self.limiters = RateLimiters(
            enabled=enabled,
            registration=SlidingWindowLimiter(
                registration_max, registration_window, max_keys=max_keys, clock=self.clock
            ),
            track=SlidingWindowLimiter(track_max, track_window, max_keys=max_keys, clock=self.clock),
            trust_proxy_headers=trust_proxy_headers,
            trusted_proxy_count=trusted_proxy_count,
        )
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)
        register_exception_handlers(app)
        app.include_router(router, prefix=PREFIX)
        app.state.rate_limiters = self.limiters
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_user_access_repo] = lambda: self.repo
        app.dependency_overrides[get_family_repo] = lambda: self.family
        self.app = app
        self._raise = raise_server_exceptions
        self.client = self.client_for(DEFAULT_IP)
        self.plan = self.family.add_plan("TEST-ACTIVE", price="199000.00")

    def client_for(self, ip: str) -> TestClient:
        return TestClient(self.app, client=(ip, 50000), raise_server_exceptions=self._raise)

    def body(self, **overrides) -> dict:
        body = reg_body(**overrides)
        if body.get("requested_plan_id") is None:
            body["requested_plan_id"] = str(self.plan.plan_id)
        return body

    def register(self, client: TestClient | None = None, headers: dict | None = None, **overrides):
        return (client or self.client).post(
            f"{PREFIX}/business-registrations", json=self.body(**overrides), headers=headers or {}
        )

    def track(self, code, client: TestClient | None = None):
        return (client or self.client).post(
            f"{PREFIX}/business-registrations/track", json={"tracking_code": code}
        )


def code_of(response) -> str:
    return response.json()["error"]["code"]
