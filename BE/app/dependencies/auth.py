"""Authentication dependency: application session -> Principal (plan section 5).

Every request:
  1. Bearer token -> SHA-256 -> user_sessions.token_jti_hash.
  2. Session must exist, not be revoked, not be expired, and must have been
     created after the last password change.
  3. users.status: LOCKED / SUSPENDED / DISABLED -> ACCOUNT_BLOCKED.
  4. credential_metadata.must_change_password AND temporary_password_expires_at
     in the past -> TEMPORARY_PASSWORD_EXPIRED.
  5. users.first_login_required OR credential_metadata.must_change_password
     -> restricted session (only /auth/me, /auth/change-password, /auth/logout).

Roles are never read from the token; authorization lives in permissions.py and
re-reads the database on every request.

No Firebase here. The ID-token exchange (POST /auth/session) lives in
app/controllers/auth_access and reuses evaluate_account() below, so a login and
every later request apply the same account rules.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Protocol

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.tokens import hash_session_token
from app.db.postgres import get_db
from app.models.user_access.entities import CredentialMetadata, User, UserSession
from app.models.user_access.repository import UserAccessRepository
from app.schemas.errors import ErrorCode

API_PREFIX = "/api/v1"

# Restricted sessions may only reach these routes. get_principal_allow_restricted
# must be attached to exactly these three routes; the path check below is an
# extra defensive layer, not the primary control.
RESTRICTED_ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        f"{API_PREFIX}/auth/me",
        f"{API_PREFIX}/auth/change-password",
        f"{API_PREFIX}/auth/logout",
    }
)

BLOCKED_STATUSES: frozenset[str] = frozenset({"LOCKED", "SUSPENDED", "DISABLED"})
USABLE_STATUSES: frozenset[str] = frozenset({"ACTIVE", "PENDING"})

_WWW_AUTH = {"WWW-Authenticate": "Bearer"}

_bearer = HTTPBearer(auto_error=False, description="Application session token")


class AuthRepository(Protocol):
    """What authentication needs from storage (real repo or test fake)."""

    async def get_session_by_token_hash(self, token_jti_hash: str) -> UserSession | None: ...

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None: ...

    async def get_credential_metadata(self, user_id: uuid.UUID) -> CredentialMetadata | None: ...


@dataclass(frozen=True)
class Principal:
    """Authenticated caller. Carries identity only, never roles or permissions."""

    user_id: uuid.UUID
    session_id: uuid.UUID
    status: str
    requires_password_change: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_invalid() -> AppError:
    return AppError(ErrorCode.SESSION_INVALID, headers=_WWW_AUTH)


async def evaluate_account(
    user: User,
    load_cred: Callable[[], Awaitable[CredentialMetadata | None]],
    *,
    now: datetime,
    issued_at: datetime,
    stale_error: Callable[[], AppError],
) -> bool:
    """Account rules shared by every request and by the ID-token exchange.

    issued_at: when the credential being used was issued (session created_at, or the
    Firebase auth_time at login). Anything issued before the latest password change is
    dead, even if the explicit revoke after the change was missed -> stale_error().

    Returns requires_password_change. Raises AppError; order matters:
    blocked status, stale credential, expired temporary password, PENDING.
    """
    if user.status in BLOCKED_STATUSES or user.status not in USABLE_STATUSES:
        # Unknown statuses are denied too (default deny).
        raise AppError(ErrorCode.ACCOUNT_BLOCKED)

    cred = await load_cred()

    if (
        cred is not None
        and cred.password_changed_at is not None
        and cred.password_changed_at > issued_at
    ):
        raise stale_error()

    must_change = bool(cred is not None and cred.must_change_password)
    requires_password_change = bool(user.first_login_required) or must_change

    if (
        must_change
        and cred is not None
        and cred.temporary_password_expires_at is not None
        and cred.temporary_password_expires_at <= now
    ):
        raise AppError(ErrorCode.TEMPORARY_PASSWORD_EXPIRED)

    # PENDING is only usable as a restricted session (temporary password flow); the
    # first successful password change moves the user to ACTIVE.
    if user.status == "PENDING" and not requires_password_change:
        raise AppError(ErrorCode.ACCOUNT_BLOCKED)

    return requires_password_change


async def resolve_principal(
    token: str,
    repo: AuthRepository,
    *,
    now: datetime | None = None,
) -> Principal:
    """Pure session -> Principal resolution. Raises AppError; never returns partial data."""
    now = now or _now()

    session = await repo.get_session_by_token_hash(hash_session_token(token))
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        raise _session_invalid()

    user = await repo.get_user_by_id(session.user_id)
    if user is None:
        raise _session_invalid()

    # Fetched lazily so a blocked account is rejected before anything else.
    async def load_cred() -> CredentialMetadata | None:
        return await repo.get_credential_metadata(user.user_id)

    requires_password_change = await evaluate_account(
        user,
        load_cred,
        now=now,
        issued_at=session.created_at,
        stale_error=_session_invalid,
    )

    return Principal(
        user_id=user.user_id,
        session_id=session.session_id,
        status=user.status,
        requires_password_change=requires_password_change,
    )


def _extract_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(ErrorCode.UNAUTHENTICATED, headers=_WWW_AUTH)
    token = credentials.credentials.strip()
    if not token or len(token) > 512:
        raise _session_invalid()
    return token


def _normalize_path(path: str) -> str:
    return path.rstrip("/") or "/"


async def get_user_access_repo(
    db: AsyncSession = Depends(get_db),
) -> UserAccessRepository:
    return UserAccessRepository(db)


async def get_principal_allow_restricted(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    repo: UserAccessRepository = Depends(get_user_access_repo),
) -> Principal:
    """Attach ONLY to /auth/me, /auth/change-password, /auth/logout."""
    principal = await resolve_principal(_extract_token(credentials), repo)
    if (
        principal.requires_password_change
        and _normalize_path(request.url.path) not in RESTRICTED_ALLOWED_PATHS
    ):
        # Defensive: the dependency was attached to a route it should not be on.
        raise AppError(ErrorCode.PASSWORD_CHANGE_REQUIRED)
    return principal


async def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    repo: UserAccessRepository = Depends(get_user_access_repo),
) -> Principal:
    """Default for every authenticated route: restricted sessions are rejected."""
    principal = await resolve_principal(_extract_token(credentials), repo)
    if principal.requires_password_change:
        raise AppError(ErrorCode.PASSWORD_CHANGE_REQUIRED)
    return principal
