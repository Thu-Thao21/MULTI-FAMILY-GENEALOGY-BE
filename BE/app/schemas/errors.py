"""Error envelope and error codes (plan section 6, "Quy ước validation và lỗi").

Envelope: {"error": {"code": "...", "message": "...", "request_id": "..."}}
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class ErrorCode(StrEnum):
    # 400 - malformed request outside schema validation
    BAD_REQUEST = "BAD_REQUEST"
    # 400 - password reset oob_code (plan section 6: wrong/expired code -> 400)
    RESET_CODE_INVALID = "RESET_CODE_INVALID"
    RESET_CODE_EXPIRED = "RESET_CODE_EXPIRED"

    # 401 - not authenticated
    UNAUTHENTICATED = "UNAUTHENTICATED"
    INVALID_ID_TOKEN = "INVALID_ID_TOKEN"
    SESSION_INVALID = "SESSION_INVALID"
    RECENT_LOGIN_REQUIRED = "RECENT_LOGIN_REQUIRED"

    # 403 - authenticated but not allowed
    FORBIDDEN = "FORBIDDEN"
    ACCOUNT_BLOCKED = "ACCOUNT_BLOCKED"
    PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"
    TEMPORARY_PASSWORD_EXPIRED = "TEMPORARY_PASSWORD_EXPIRED"

    # 404 - resource does not exist or is not visible to the caller
    NOT_FOUND = "NOT_FOUND"

    # 405
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"

    # 409 - state conflict
    STATE_CONFLICT = "STATE_CONFLICT"
    DUPLICATE_RESOURCE = "DUPLICATE_RESOURCE"
    IDEMPOTENCY_KEY_CONFLICT = "IDEMPOTENCY_KEY_CONFLICT"

    # 422 - input validation
    VALIDATION_ERROR = "VALIDATION_ERROR"

    # 429 - rate limit
    RATE_LIMITED = "RATE_LIMITED"

    # 500 - unexpected
    INTERNAL_ERROR = "INTERNAL_ERROR"

    # 503 - dependency down (Firebase, DB, email provider)
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"


ERROR_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.RESET_CODE_INVALID: 400,
    ErrorCode.RESET_CODE_EXPIRED: 400,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.INVALID_ID_TOKEN: 401,
    ErrorCode.SESSION_INVALID: 401,
    ErrorCode.RECENT_LOGIN_REQUIRED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.ACCOUNT_BLOCKED: 403,
    ErrorCode.PASSWORD_CHANGE_REQUIRED: 403,
    ErrorCode.TEMPORARY_PASSWORD_EXPIRED: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.STATE_CONFLICT: 409,
    ErrorCode.DUPLICATE_RESOURCE: 409,
    ErrorCode.IDEMPOTENCY_KEY_CONFLICT: 409,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.PROVIDER_UNAVAILABLE: 503,
    ErrorCode.DATABASE_UNAVAILABLE: 503,
}

# Generic, non-revealing default messages. FE should branch on `code`, not `message`.
DEFAULT_ERROR_MESSAGE: dict[ErrorCode, str] = {
    ErrorCode.BAD_REQUEST: "Bad request.",
    ErrorCode.RESET_CODE_INVALID: "The password reset code is invalid.",
    ErrorCode.RESET_CODE_EXPIRED: "The password reset code has expired.",
    ErrorCode.UNAUTHENTICATED: "Authentication is required.",
    ErrorCode.INVALID_ID_TOKEN: "The identity token is invalid or revoked.",
    ErrorCode.SESSION_INVALID: "The session is invalid, expired or revoked.",
    ErrorCode.RECENT_LOGIN_REQUIRED: "Please sign in again to continue.",
    ErrorCode.FORBIDDEN: "You do not have permission to perform this action.",
    ErrorCode.ACCOUNT_BLOCKED: "This account cannot be used.",
    ErrorCode.PASSWORD_CHANGE_REQUIRED: "You must change your password first.",
    ErrorCode.TEMPORARY_PASSWORD_EXPIRED: "The temporary password has expired.",
    ErrorCode.NOT_FOUND: "Resource not found.",
    ErrorCode.METHOD_NOT_ALLOWED: "Method not allowed.",
    ErrorCode.STATE_CONFLICT: "The resource state has changed.",
    ErrorCode.DUPLICATE_RESOURCE: "The resource already exists.",
    ErrorCode.IDEMPOTENCY_KEY_CONFLICT: "Idempotency-Key was reused with a different payload.",
    ErrorCode.VALIDATION_ERROR: "Invalid input.",
    ErrorCode.RATE_LIMITED: "Too many requests. Please try again later.",
    ErrorCode.INTERNAL_ERROR: "An unexpected error occurred.",
    ErrorCode.PROVIDER_UNAVAILABLE: "An external service is temporarily unavailable.",
    ErrorCode.DATABASE_UNAVAILABLE: "The database is temporarily unavailable.",
}

# Fallback code when a plain HTTPException (no ErrorCode) is raised.
STATUS_DEFAULT_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.STATE_CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
    500: ErrorCode.INTERNAL_ERROR,
    503: ErrorCode.PROVIDER_UNAVAILABLE,
}


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody
