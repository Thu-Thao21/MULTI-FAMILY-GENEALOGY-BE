"""Response security headers (Mốc H1).

- SecurityHeadersMiddleware (pure ASGI): adds X-Content-Type-Options, X-Frame-Options and
  Referrer-Policy to EVERY HTTP response, never replacing a value a handler already set.
  No Strict-Transport-Security yet: the service does not run behind HTTPS (security_review.md).
- NoStoreRoute: route class for routers whose every response, success or error, must not be
  cached (the auth router: POST /auth/session returns the access token). L-26.
"""

from __future__ import annotations

from fastapi.routing import APIRoute
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import UnhandledErrorMiddleware

SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
)

NO_STORE_HEADERS: tuple[tuple[str, str], ...] = (
    ("Cache-Control", "no-store"),
    ("Pragma", "no-cache"),
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS:
                    if name not in headers:
                        headers.append(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class NoStoreRoute(APIRoute):
    """Every response of the route carries Cache-Control: no-store and Pragma: no-cache.

    The headers are set on the way out of Route.handle, which covers the endpoint's own response
    and the error envelopes of AppError, HTTPException and validation errors (their handlers run
    inside the route in Starlette). An unhandled exception would escape the route and become a 500
    in the app-level UnhandledErrorMiddleware, past this point; wrapping the route in the same
    middleware builds that identical 500 envelope here, so it gets the headers too. Outer
    middlewares (CORS, security headers, request id) still apply to it as to any response.

    Cache-Control is replaced, not appended to: these responses must never be cached whatever a
    handler set.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._guarded_handle = UnhandledErrorMiddleware(super().handle)

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in NO_STORE_HEADERS:
                    headers[name] = value
            await send(message)

        await self._guarded_handle(scope, receive, send_no_store)
