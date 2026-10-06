"""CORS on every kind of response, including unhandled 500s (Mốc G).

A browser only lets frontend JavaScript read a response that carries Access-Control-*
headers. The 500 envelope used to bypass CORSMiddleware (ServerErrorMiddleware is the
outermost layer); UnhandledErrorMiddleware now catches it inside CORS.
"""

from __future__ import annotations

import logging

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

import app.core.errors as errors_module
from app.core.errors import AppError
from app.main import app as real_app
from app.main import create_app
from app.schemas.errors import ErrorCode

ORIGINS = ["http://localhost:5173", "http://localhost:8080"]
FOREIGN = "http://evil.example"
SECRET_DETAIL = "internal-detail-password=hunter2-DATABASE_URL=postgres://u:p@h/db"


class Body(BaseModel):
    name: str


def build_probe_app():
    """A fresh app with the real middleware stack plus routes that fail in every way."""
    application = create_app()
    router = APIRouter()

    @router.get("/probe/ok")
    async def ok():
        return {"ok": True}

    @router.get("/probe/unauthenticated")
    async def unauthenticated():
        raise AppError(ErrorCode.UNAUTHENTICATED)

    @router.get("/probe/forbidden")
    async def forbidden():
        raise AppError(ErrorCode.FORBIDDEN)

    @router.post("/probe/validate")
    async def validate(body: Body):
        return body

    @router.get("/probe/db-down")
    async def db_down():
        raise OperationalError("SELECT 1", {}, Exception(SECRET_DETAIL))

    @router.get("/probe/boom")
    async def boom():
        raise RuntimeError(SECRET_DETAIL)

    application.include_router(router)
    return application


@pytest.fixture
def probe() -> TestClient:
    # raise_server_exceptions=False: a browser would see the 500, so must the test.
    return TestClient(build_probe_app(), raise_server_exceptions=False)


@pytest.fixture
def real() -> TestClient:
    return TestClient(real_app, raise_server_exceptions=False)


def assert_cors_ok(response, origin: str) -> None:
    assert response.headers.get("access-control-allow-origin") == origin
    assert response.headers.get("access-control-allow-credentials") == "true"
    exposed = response.headers.get("access-control-expose-headers", "")
    assert "X-Request-ID" in exposed and "Retry-After" in exposed
    assert "Origin" in response.headers.get("vary", "")


def assert_envelope(response, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "request_id"}
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize("origin", ORIGINS)
@pytest.mark.parametrize(
    "method,path,kwargs,status,code",
    [
        ("get", "/probe/ok", {}, 200, None),
        ("get", "/probe/unauthenticated", {}, 401, "UNAUTHENTICATED"),
        ("get", "/probe/forbidden", {}, 403, "FORBIDDEN"),
        ("get", "/probe/no-such-route", {}, 404, "NOT_FOUND"),
        ("delete", "/probe/ok", {}, 405, "METHOD_NOT_ALLOWED"),
        ("post", "/probe/validate", {"json": {}}, 422, "VALIDATION_ERROR"),
        ("get", "/probe/db-down", {}, 503, "DATABASE_UNAVAILABLE"),
        ("get", "/probe/boom", {}, 500, "INTERNAL_ERROR"),
    ],
    ids=["200", "401", "403", "404", "405", "422", "503-db", "500"],
)
def test_every_response_kind_carries_cors_headers(probe, origin, method, path, kwargs, status, code):
    r = getattr(probe, method)(path, headers={"Origin": origin}, **kwargs)
    assert r.status_code == status
    if code:
        assert_envelope(r, status, code)
    assert_cors_ok(r, origin)
    assert r.headers["X-Request-ID"]


def test_unhandled_500_is_the_standard_envelope_without_internal_detail(probe, caplog):
    caplog.set_level(logging.DEBUG)
    r = probe.get("/probe/boom", headers={"Origin": ORIGINS[0]})
    assert_envelope(r, 500, "INTERNAL_ERROR")
    assert r.json()["error"]["message"] == "An unexpected error occurred."
    for leaked in (SECRET_DETAIL, "hunter2", "RuntimeError", "Traceback", "boom"):
        assert leaked not in r.text
    # Log: exception class + request_id only (no message, no traceback unless DEBUG).
    assert "Unhandled RuntimeError request_id=" + r.headers["X-Request-ID"] in caplog.text
    assert "hunter2" not in caplog.text and "Traceback" not in caplog.text


def test_500_response_stays_clean_even_with_debug_logging(probe, monkeypatch, caplog):
    """DEBUG only adds the traceback to the SERVER log, never to the response."""
    monkeypatch.setattr(errors_module.settings, "DEBUG", True)
    caplog.set_level(logging.DEBUG)
    r = probe.get("/probe/boom", headers={"Origin": ORIGINS[0]})
    assert_envelope(r, 500, "INTERNAL_ERROR")
    assert "hunter2" not in r.text and "Traceback" not in r.text
    assert_cors_ok(r, ORIGINS[0])


def test_db_unavailable_does_not_leak_the_driver_message(probe, caplog):
    caplog.set_level(logging.DEBUG)
    r = probe.get("/probe/db-down", headers={"Origin": ORIGINS[0]})
    assert_envelope(r, 503, "DATABASE_UNAVAILABLE")
    assert "hunter2" not in r.text and "hunter2" not in caplog.text


@pytest.mark.parametrize("path", ["/probe/ok", "/probe/forbidden", "/probe/boom"])
def test_foreign_origin_gets_no_cors_headers_on_any_response(probe, path):
    r = probe.get(path, headers={"Origin": FOREIGN})
    # Without Access-Control-Allow-Origin the browser refuses to expose the response to the
    # foreign page. (Starlette still adds its static allow-credentials/expose headers;
    # they grant nothing on their own.)
    assert "access-control-allow-origin" not in r.headers
    assert r.headers["X-Request-ID"]  # request_id still present


def test_no_origin_header_means_no_cors_headers(probe):
    assert "access-control-allow-origin" not in probe.get("/probe/boom").headers


def test_request_id_is_generated_or_echoed_even_on_500(probe):
    echoed = probe.get("/probe/boom", headers={"X-Request-ID": "frontend-req-12345"})
    assert echoed.headers["X-Request-ID"] == "frontend-req-12345"
    assert echoed.json()["error"]["request_id"] == "frontend-req-12345"
    invalid = probe.get("/probe/boom", headers={"X-Request-ID": "bad id with spaces"})
    assert invalid.headers["X-Request-ID"] != "bad id with spaces"


@pytest.mark.parametrize("origin", ORIGINS)
def test_preflight_allows_the_headers_the_frontend_sends(probe, origin):
    r = probe.options(
        "/probe/ok",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key,x-request-id",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == origin
    allowed = r.headers["access-control-allow-headers"].lower()
    for header in ("authorization", "content-type", "idempotency-key", "x-request-id"):
        assert header in allowed
    methods = r.headers["access-control-allow-methods"]
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        assert method in methods
    assert r.headers["X-Request-ID"]


def test_preflight_from_foreign_origin_is_refused(probe):
    r = probe.options(
        "/probe/ok",
        headers={"Origin": FOREIGN, "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 400 and "access-control-allow-origin" not in r.headers


def test_real_app_error_responses_have_cors(real):
    """Same checks on the real app's routes (no database needed for these)."""
    origin = ORIGINS[0]
    r = real.get("/api/v1/auth/me", headers={"Origin": origin})
    assert_envelope(r, 401, "UNAUTHENTICATED")
    assert_cors_ok(r, origin)
    r = real.post("/api/v1/auth/session", headers={"Origin": origin}, json={})
    assert_envelope(r, 422, "VALIDATION_ERROR")
    assert_cors_ok(r, origin)
    r = real.get("/api/v1/does-not-exist", headers={"Origin": origin})
    assert_envelope(r, 404, "NOT_FOUND")
    assert_cors_ok(r, origin)
    r = real.get("/api/health", headers={"Origin": origin})
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert_cors_ok(r, origin)


def test_middleware_order_is_request_id_then_cors_then_unhandled_error():
    """Pins the order that makes the 500 envelope pass through CORS (outermost first)."""
    names = [m.cls.__name__ for m in real_app.user_middleware]
    assert names == ["RequestIdMiddleware", "CORSMiddleware", "UnhandledErrorMiddleware"]


def test_response_already_started_is_not_replaced():
    """If the body has begun streaming the middleware must re-raise, not send a 2nd start."""
    import asyncio

    from app.core.errors import UnhandledErrorMiddleware

    sent: list[dict] = []

    async def failing_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("after start")

    async def send(message):
        sent.append(message)

    async def run():
        mw = UnhandledErrorMiddleware(failing_app)
        with pytest.raises(RuntimeError):
            await mw({"type": "http", "headers": [], "state": {}}, None, send)

    asyncio.run(run())
    assert [m["type"] for m in sent] == ["http.response.start"]
