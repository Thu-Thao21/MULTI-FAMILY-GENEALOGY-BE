"""AppError and exception handlers producing the standard error envelope.

{"error": {"code": "...", "message": "...", "request_id": "..."}}

Logging rules: never log exception messages, request bodies, tokens or
DATABASE_URL. Unhandled errors log the exception class and request_id only;
the traceback is added only when settings.DEBUG is true.
"""

from __future__ import annotations

import logging
import uuid
from typing import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.core.request_id import REQUEST_ID_HEADER
from app.schemas.errors import (
    DEFAULT_ERROR_MESSAGE,
    ERROR_HTTP_STATUS,
    STATUS_DEFAULT_CODE,
    ErrorBody,
    ErrorCode,
    ErrorResponse,
)

logger = logging.getLogger("mfg.errors")


class AppError(Exception):
    """Raise from use cases/controllers; the HTTP status comes from ERROR_HTTP_STATUS."""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.code = code
        self.message = message or DEFAULT_ERROR_MESSAGE[code]
        self.status_code = ERROR_HTTP_STATUS[code]
        self.headers = dict(headers or {})
        super().__init__(code.value)  # keep str(exc) free of user data


def _request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid or str(uuid.uuid4())


def error_response(
    request: Request,
    code: ErrorCode,
    message: str | None = None,
    *,
    status_code: int | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    rid = _request_id(request)
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message or DEFAULT_ERROR_MESSAGE[code],
            request_id=rid,
        )
    )
    out_headers = {REQUEST_ID_HEADER: rid, **(headers or {})}
    return JSONResponse(
        status_code=status_code or ERROR_HTTP_STATUS[code],
        content=body.model_dump(mode="json"),
        headers=out_headers,
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(
        request, exc.code, exc.message, status_code=exc.status_code, headers=exc.headers
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    code = STATUS_DEFAULT_CODE.get(
        exc.status_code,
        ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.BAD_REQUEST,
    )
    # Plain HTTPException detail is developer-written; non-string details are dropped.
    message = exc.detail if isinstance(exc.detail, str) and exc.detail else None
    headers = getattr(exc, "headers", None)
    return error_response(
        request, code, message, status_code=exc.status_code, headers=headers
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Only field locations are reported; input values are never echoed back
    # (they may contain passwords or tokens).
    locations: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        if loc and loc not in locations:
            locations.append(loc)
    message = DEFAULT_ERROR_MESSAGE[ErrorCode.VALIDATION_ERROR]
    if locations:
        message = f"{message} Fields: {', '.join(locations[:20])}"
    return error_response(request, ErrorCode.VALIDATION_ERROR, message)


async def database_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    # Connection-level DB errors only. The message is not logged: it can embed
    # connection details.
    logger.error(
        "Database unavailable %s request_id=%s", type(exc).__name__, _request_id(request)
    )
    return error_response(request, ErrorCode.DATABASE_UNAVAILABLE)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    rid = _request_id(request)
    logger.error(
        "Unhandled %s request_id=%s",
        type(exc).__name__,
        rid,
        exc_info=exc if settings.DEBUG else None,
    )
    return error_response(request, ErrorCode.INTERNAL_ERROR)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(OperationalError, database_unavailable_handler)
    app.add_exception_handler(InterfaceError, database_unavailable_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)


class UnhandledErrorMiddleware:
    """Turn an unhandled exception into the standard 500 envelope INSIDE CORSMiddleware.

    Starlette runs the handler registered for Exception in ServerErrorMiddleware, the
    OUTERMOST layer, so that 500 would bypass CORSMiddleware and reach the browser without
    Access-Control-* headers (the frontend then sees an opaque network error and cannot
    read the body or request_id). Installed directly under CORSMiddleware, this catches
    the error first; CORS headers are then added to the envelope like any other response.

    Same body and log as unhandled_exception_handler: exception class and request_id only,
    never the message, traceback (unless DEBUG) or any internal detail in the response.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:  # noqa: BLE001 - this is the catch-all by design
            if response_started:
                raise  # headers already sent: cannot replace the response
            request = Request(scope, receive)
            response = await unhandled_exception_handler(request, exc)
            await response(scope, receive, send)
