"""Request ID middleware (pure ASGI).

- Reuses an incoming X-Request-ID only if it is a safe token (8-128 chars of
  [A-Za-z0-9._-]); otherwise generates a UUID4. Untrusted values never reach logs.
- Stores it in request.state.request_id and in a contextvar for logging.
- Adds X-Request-ID to every HTTP response (unless a handler already set it).
"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    return request_id_ctx.get()


def _resolve(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name == b"x-request-id":
            try:
                candidate = value.decode("ascii")
            except UnicodeDecodeError:
                break
            if _SAFE_REQUEST_ID.match(candidate):
                return candidate
            break
    return str(uuid.uuid4())


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _resolve(scope)
        # Mutate the shared state dict so outer middleware (ServerErrorMiddleware,
        # i.e. the 500 handler) sees the same request_id via request.state.
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_ctx.set(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if REQUEST_ID_HEADER not in headers:
                    headers.append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_ctx.reset(token)
