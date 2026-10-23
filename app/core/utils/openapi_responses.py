"""Shared OpenAPI `responses=` metadata (documentation only, no behaviour change).

Every error status is documented with the real envelope (ErrorResponse) and the list of
error codes that can occur there, taken from docs/api_contract.md section 2 and from what
the code actually raises. FastAPI's default 422 (HTTPValidationError) does not match the
envelope the app returns, so each route declares 422 explicitly here.

Use:  @router.get(..., responses=error_responses(*AUTHENTICATED, ErrorCode.NOT_FOUND))
"""

from __future__ import annotations

from typing import Any

from app.schemas.errors import ERROR_HTTP_STATUS, ErrorCode, ErrorResponse

# Every authenticated route (api_contract.md section 2, last paragraph) plus what
# resolve_principal can raise. PASSWORD_CHANGE_REQUIRED is excluded for the three routes
# a restricted session may use (see AUTHENTICATED_RESTRICTED_OK).
AUTHENTICATED_RESTRICTED_OK: tuple[ErrorCode, ...] = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.SESSION_INVALID,
    ErrorCode.ACCOUNT_BLOCKED,
    ErrorCode.TEMPORARY_PASSWORD_EXPIRED,
    ErrorCode.DATABASE_UNAVAILABLE,
    ErrorCode.INTERNAL_ERROR,
)
AUTHENTICATED: tuple[ErrorCode, ...] = AUTHENTICATED_RESTRICTED_OK + (
    ErrorCode.PASSWORD_CHANGE_REQUIRED,
)
# Any route that touches the database or can fail unexpectedly.
BASE: tuple[ErrorCode, ...] = (ErrorCode.DATABASE_UNAVAILABLE, ErrorCode.INTERNAL_ERROR)


def error_responses(*codes: ErrorCode) -> dict[int | str, dict[str, Any]]:
    """Group error codes by HTTP status into the `responses=` dict of a route."""
    by_status: dict[int, list[str]] = {}
    for code in dict.fromkeys(codes):  # de-duplicate, keep order
        by_status.setdefault(ERROR_HTTP_STATUS[code], []).append(code.value)
    return {
        status: {
            "model": ErrorResponse,
            "description": "Error codes: " + ", ".join(names),
        }
        for status, names in sorted(by_status.items())
    }
