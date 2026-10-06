"""Auth use cases (Mốc D, plan section 5-6). Use cases own the transaction.

Logging rule: only an event name, a fixed reason code and request_id. Never the ID
token, the bearer token, the Firebase UID, the email or the password.
"""

from __future__ import annotations

import ipaddress
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.errors import AppError
from app.core.firebase import IdentityProvider, InvalidIdToken, PasswordRejected, ProviderUnavailable
from app.core.request_id import get_request_id
from app.core.tokens import generate_session_token, hash_session_token
from app.dependencies.auth import Principal, evaluate_account
from app.dependencies.permissions import is_active_owner, owner_actions, system_admin_actions
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import SYSTEM_ADMIN_ROLE, UserAccessRepository
from app.schemas.auth import MembershipSummary, MeResponse, SessionCreateResponse, SessionUser
from app.schemas.errors import ErrorCode

logger = logging.getLogger("mfg.auth")

USER_AGENT_MAX_LENGTH = 512
IDENTIFIER_MAX_LENGTH = 255
STALE_ID_TOKEN_REASON = "ID_TOKEN_BEFORE_PASSWORD_CHANGE"


class UnitOfWork(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


@dataclass(frozen=True)
class ClientInfo:
    ip_address: str | None
    user_agent: str | None

    @classmethod
    def from_request(cls, request: Request) -> "ClientInfo":
        # Direct peer only: X-Forwarded-For is not trusted until a proxy setup is agreed.
        host = request.client.host if request.client else None
        try:
            ip = str(ipaddress.ip_address(host)) if host else None
        except ValueError:
            ip = None
        agent = request.headers.get("user-agent")
        return cls(ip, agent[:USER_AGENT_MAX_LENGTH] if agent else None)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log(event: str, reason: str, *, level: int = logging.INFO) -> None:
    logger.log(level, "auth.%s reason=%s request_id=%s", event, reason, get_request_id())


def _stale_id_token() -> AppError:
    return AppError(ErrorCode.INVALID_ID_TOKEN)


async def _verify(provider: IdentityProvider, token: str, *, event: str, invalid: ErrorCode):
    try:
        return await provider.verify_id_token(token)
    except InvalidIdToken as exc:
        _log(event, f"id_token_{exc.reason}")
        raise AppError(invalid) from None
    except ProviderUnavailable as exc:
        _log(event, f"provider_{exc.reason}", level=logging.WARNING)
        raise AppError(ErrorCode.PROVIDER_UNAVAILABLE) from None


# ----- POST /auth/session -----


async def create_session(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    provider: IdentityProvider,
    id_token: str,
    client: ClientInfo,
    now: datetime | None = None,
) -> SessionCreateResponse:
    identity = await _verify(provider, id_token, event="session", invalid=ErrorCode.INVALID_ID_TOKEN)
    now = now or _now()

    # Only accounts already linked by firebase_uid. Never create a user, never link by
    # e-mail. Unknown UID looks exactly like a bad token and is not written to the DB.
    user = await users.get_user_by_firebase_uid(identity.uid)
    if user is None:
        _log("session", "unknown_uid")
        raise AppError(ErrorCode.INVALID_ID_TOKEN)

    identifier = identity.email[:IDENTIFIER_MAX_LENGTH] if identity.email else None

    async def load_cred():
        return await users.get_credential_metadata(user.user_id)

    try:
        requires_password_change = await evaluate_account(
            user, load_cred, now=now, issued_at=identity.auth_time, stale_error=_stale_id_token
        )
    except AppError as exc:
        reason = STALE_ID_TOKEN_REASON if exc.code is ErrorCode.INVALID_ID_TOKEN else exc.code.value
        await users.add_login_history(
            user_id=user.user_id,
            identifier=identifier,
            success=False,
            failure_reason=reason,
            ip_address=client.ip_address,
            user_agent=client.user_agent,
            occurred_at=now,
        )
        # Commit BEFORE answering, otherwise the error path would roll the row back.
        await db.commit()
        _log("session", reason.lower())
        raise

    token = generate_session_token()
    expires_at = now + timedelta(hours=settings.SESSION_TTL_HOURS)
    await users.add_session(
        user_id=user.user_id,
        token_jti_hash=hash_session_token(token),
        created_at=now,
        expires_at=expires_at,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
    )
    user.last_login_at = now
    await users.add_login_history(
        user_id=user.user_id,
        identifier=identifier,
        success=True,
        failure_reason=None,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        occurred_at=now,
    )
    await db.commit()
    _log("session", "created")
    return SessionCreateResponse(
        access_token=token,
        expires_at=expires_at,
        user=SessionUser(
            user_id=user.user_id,
            display_name=user.display_name,
            email=user.email,
            status=user.status,
        ),
        requires_password_change=requires_password_change,
    )


# ----- GET /auth/me -----


async def build_membership_summaries(
    *,
    users: UserAccessRepository,
    family: FamilyRepository,
    user_id: uuid.UUID,
    grants: list[tuple[str, uuid.UUID | None]],
) -> list[MembershipSummary]:
    """One summary per non-revoked membership of the user (GET /auth/me and
    GET /admin/users/{id}). permissions[] is PROVISIONAL (api_contract.md section 6)."""
    memberships: list[MembershipSummary] = []
    for membership, clan in await family.list_memberships_with_clans(user_id):
        permissions: set[str] = set()
        # Nothing is effective unless both the membership and the clan are ACTIVE,
        # mirroring authorize().
        if membership.status == "ACTIVE" and clan.status == "ACTIVE":
            if await is_active_owner(user_id, clan.clan_id, users, family):
                permissions.update(owner_actions())
            permissions.update(await family.list_fa_permission_codes(clan.clan_id, user_id))
        memberships.append(
            MembershipSummary(
                clan_id=clan.clan_id,
                clan_name=clan.name,
                clan_status=clan.status,
                membership_status=membership.status,
                roles=sorted({code for code, cid in grants if cid == clan.clan_id}),
                permissions=sorted(permissions),
            )
        )
    return memberships


async def get_me(
    *, users: UserAccessRepository, family: FamilyRepository, principal: Principal
) -> MeResponse:
    """permissions[] is PROVISIONAL (api_contract.md section 6): SA/BO get policy action
    codes, FA gets the codes stored in family_admin_permissions."""
    user = await users.get_user_by_id(principal.user_id)
    if user is None:
        raise AppError(ErrorCode.SESSION_INVALID)

    grants = await users.list_active_role_grants(user.user_id)
    is_system_admin = any(code == SYSTEM_ADMIN_ROLE and clan is None for code, clan in grants)
    memberships = await build_membership_summaries(
        users=users, family=family, user_id=user.user_id, grants=grants
    )

    return MeResponse(
        user_id=user.user_id,
        display_name=user.display_name,
        status=user.status,
        memberships=memberships,
        permissions=system_admin_actions() if is_system_admin else [],
        requires_password_change=principal.requires_password_change,
    )


# ----- POST /auth/logout -----


async def logout(
    *, db: UnitOfWork, users: UserAccessRepository, principal: Principal, now: datetime | None = None
) -> None:
    await users.revoke_session(principal.session_id, reason="LOGOUT", now=now or _now())
    await db.commit()
    _log("logout", "revoked")


# ----- POST /auth/change-password -----


async def change_password(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    provider: IdentityProvider,
    principal: Principal,
    new_password: str,
    recent_id_token: str,
    client: ClientInfo,
    now: datetime | None = None,
) -> None:
    """Firebase first, then the DB in one transaction.

    Firebase and PostgreSQL share no transaction. If Firebase succeeds and the DB update
    fails, the flags stay set (account still restricted) and the call returns 503 so the
    user can retry; it never reports success when only one side changed.
    """
    identity = await _verify(
        provider, recent_id_token, event="change_password", invalid=ErrorCode.RECENT_LOGIN_REQUIRED
    )
    user = await users.get_user_by_id(principal.user_id)
    if user is None:
        raise AppError(ErrorCode.SESSION_INVALID)
    if not user.firebase_uid or identity.uid != user.firebase_uid:
        _log("change_password", "uid_mismatch")
        raise AppError(ErrorCode.RECENT_LOGIN_REQUIRED)

    checked_at = now or _now()
    if checked_at - identity.auth_time > timedelta(seconds=settings.RECENT_LOGIN_MAX_AGE_SECONDS):
        _log("change_password", "sign_in_not_recent")
        raise AppError(ErrorCode.RECENT_LOGIN_REQUIRED)

    cred = await users.get_credential_metadata(user.user_id)
    if cred is not None and cred.password_changed_at and cred.password_changed_at > identity.auth_time:
        _log("change_password", "sign_in_before_password_change")
        raise AppError(ErrorCode.RECENT_LOGIN_REQUIRED)

    try:
        await provider.set_password(identity.uid, new_password)
    except PasswordRejected:
        _log("change_password", "password_rejected_by_provider")
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "Invalid input. Fields: new_password (password policy)."
        ) from None
    except ProviderUnavailable as exc:
        _log("change_password", f"provider_{exc.reason}", level=logging.WARNING)
        raise AppError(ErrorCode.PROVIDER_UNAVAILABLE) from None

    # Timestamp taken after Firebase accepted the change: any ID token or session issued
    # before this instant is refused from now on.
    changed_at = now or _now()
    try:
        if cred is None:
            cred = await users.add_credential_metadata(user.user_id, now=changed_at)
        status_before = user.status
        cred.must_change_password = False
        cred.temporary_password_issued_at = None
        cred.temporary_password_expires_at = None
        cred.password_changed_at = changed_at
        cred.updated_at = changed_at
        user.first_login_required = False
        if user.status == "PENDING":
            # User ACCOUNT status only. Business/clan activation is a separate rule (D03).
            user.status = "ACTIVE"
        user.updated_at = changed_at
        revoked = await users.revoke_all_sessions(
            user.user_id, reason="PASSWORD_CHANGED", now=changed_at
        )
        await users.add_audit_log(
            actor_id=user.user_id,
            action="auth.password_changed",
            entity_type="user",
            entity_id=user.user_id,
            old_data={"status": status_before},
            new_data={"status": user.status, "revoked_sessions": revoked},
            ip_address=client.ip_address,
            occurred_at=changed_at,
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "auth.change_password reason=firebase_changed_db_failed error=%s request_id=%s",
            type(exc).__name__,
            get_request_id(),
        )
        raise AppError(
            ErrorCode.DATABASE_UNAVAILABLE,
            "The password was changed but the account update did not complete. Please retry.",
        ) from None
    _log("change_password", "done")
