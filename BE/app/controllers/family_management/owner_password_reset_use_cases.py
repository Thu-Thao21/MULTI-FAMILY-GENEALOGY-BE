"""System Admin use case: issue a NEW temporary password to the Owner of a clan (Mốc E6b).

POST /admin/clans/{clan_id}/owner/temporary-password. The Owner exists but has not yet chosen their own
password (the first one was lost, or expired after 72 hours). Firebase and PostgreSQL share no
transaction, so the order is fixed and NO database transaction or lock is held across the Firebase call:

  1. CHECK (a read-only transaction, ended before Firebase is called): the clan has a current Owner,
     whose account is PENDING and still has to change the password; not LOCKED or DISABLED; the account
     was made by a provisioning job (uid own-<uuid>). A value that identifies the credential row as read
     (issued_at, updated_at) is remembered.
  2. FIREBASE: IdentityProvider.set_owner_password(uid, new_password): sets the password and revokes the
     refresh tokens. It is the ONLY password call here, and it refuses any uid that is not own-<uuid>.
  3. DATABASE, one transaction: lock the clan, then the credential row (FOR NO KEY UPDATE); check again
     that the Owner is the same, still PENDING and still has to change the password, and that the credential
     row is the one read in step 1; then temporary_password_issued_at = now, expires_at = now + 72 h,
     must_change_password = true, revoke ALL of the Owner's sessions, one audit row (ids only), commit.
  4. The EmailSender (Noop today), after the commit.

If step 3 finds that the Owner changed the password in the gap (the account is no longer PENDING), nothing
is written and the answer is 409. Step 2 has by then overwritten the Owner's own Firebase password with the
temporary one: a gap of the length of one Firebase call, written in known_issues.md (KI-25). If step 3 finds
the credential row changed (another reset won the race), nothing is written either and the answer is 409.

The temporary password lives in memory and in the one response only: not in a column, a log line, an audit
row or an error message.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from app.controllers.auth_access.use_cases import ClientInfo, UnitOfWork
from app.controllers.family_management import owner_provisioning_use_cases as base
from app.core.config import settings
from app.core.email_sender import EmailSender
from app.core.errors import AppError
from app.core.firebase import (
    IdentityProvider,
    PasswordRejected,
    ProviderUnavailable,
    ProviderUserNotFound,
    UnsafeUid,
    is_own_uid,
)
from app.core.idempotency import LOCK_TIMEOUT_SECONDS, IdempotencyStore, rollback_on_error, rollback_quietly
from app.core.request_id import get_request_id
from app.dependencies.auth import Principal
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from app.schemas.business import OwnerPasswordResetResponse
from app.schemas.errors import ErrorCode

logger = logging.getLogger("mfg.owner_password_reset")

AUDIT_ACTION = "clan.owner.temp_password_reset"
SESSIONS_REVOKED_REASON = "TEMPORARY_PASSWORD_RESET"
BLOCKED_ACCOUNT_STATUSES = ("LOCKED", "DISABLED")


@dataclass(frozen=True)
class _Seen:
    """Plain values of what the check read, so no ORM object is touched after a rollback."""

    user_id: uuid.UUID
    firebase_uid: str
    email: str
    display_name: str
    issued_at: datetime | None
    updated_at: datetime | None


def _state_error(user, cred) -> AppError | None:
    """Why this Owner cannot be given a temporary password now, or None when they can."""
    if user is None:
        return AppError(ErrorCode.STATE_CONFLICT, "The clan's Owner account was not found.")
    if user.status in BLOCKED_ACCOUNT_STATUSES:
        return AppError(
            ErrorCode.STATE_CONFLICT,
            f"The Owner account is {user.status}; a temporary password cannot be issued.",
        )
    if user.status != "PENDING":
        return AppError(
            ErrorCode.STATE_CONFLICT,
            f"The Owner account is {user.status}: the Owner has already set their own password.",
        )
    if cred is None or not cred.must_change_password:
        return AppError(
            ErrorCode.STATE_CONFLICT,
            "The Owner does not have to change the password: a temporary password cannot be issued.",
        )
    return None


async def reset_owner_password(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    family: FamilyRepository,
    idempotency: IdempotencyStore,
    provider: IdentityProvider,
    sender: EmailSender,
    principal: Principal,
    clan_id: uuid.UUID,
    client: ClientInfo,
    clock: Callable[[], datetime] | None = None,
    password_factory: Callable[[], str] | None = None,
) -> OwnerPasswordResetResponse:
    if not provider.admin_api_enabled:
        raise AppError(ErrorCode.PROVIDER_UNAVAILABLE)  # nothing written, nothing called
    clock = clock or (lambda: base.utcnow())

    seen = await _check(db=db, users=users, family=family, clan_id=clan_id)

    password = (password_factory or base._default_password)()
    try:
        await provider.set_owner_password(seen.firebase_uid, password)
    except PasswordRejected:
        logger.warning("owner.reset step=firebase rejected_password request_id=%s", get_request_id())
        raise AppError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "The identity provider rejected the generated password (password policy); try again.",
        ) from None
    except ProviderUnavailable:
        raise AppError(ErrorCode.PROVIDER_UNAVAILABLE) from None
    except ProviderUserNotFound:
        raise AppError(
            ErrorCode.STATE_CONFLICT, "The Owner has no account at the identity provider; nothing was changed."
        ) from None
    except UnsafeUid:  # checked in _check already: defence in depth
        raise AppError(ErrorCode.STATE_CONFLICT, "The Owner's account is not managed by provisioning.") from None

    expires_at = await _write(
        db=db, users=users, family=family, idempotency=idempotency, principal=principal, clan_id=clan_id,
        seen=seen, client=client, clock=clock,
    )
    delivery = await _send(sender, seen, password, expires_at)
    logger.info("owner.reset step=done clan_id=%s request_id=%s", clan_id, get_request_id())
    return OwnerPasswordResetResponse(
        clan_id=clan_id,
        user_id=seen.user_id,
        owner_email=seen.email,
        owner_display_name=seen.display_name,
        temporary_password=password,
        temporary_password_expires_at=expires_at,
        email_delivery_status=delivery.status,
    )


async def _check(*, db, users, family, clan_id) -> _Seen:
    """Step 1: read, decide, and end the transaction so no connection is held during the Firebase call."""
    try:
        clan = await family.get_clan_by_id(clan_id)
        if clan is None:
            raise AppError(ErrorCode.NOT_FOUND)
        owner = await family.get_active_owner(clan_id)
        if owner is None:
            raise AppError(ErrorCode.STATE_CONFLICT, "This clan has no Owner yet; create one first.")
        user = await users.get_user_by_id(owner.user_id)
        cred = await users.get_credential_metadata(owner.user_id)
        problem = _state_error(user, cred)
        if problem is not None:
            raise problem
        if not is_own_uid(user.firebase_uid):
            raise AppError(
                ErrorCode.STATE_CONFLICT,
                "The Owner's account was not created by provisioning; its password cannot be reset here.",
            )
        return _Seen(
            user_id=user.user_id,
            firebase_uid=user.firebase_uid,
            email=user.email,
            display_name=user.display_name,
            issued_at=cred.temporary_password_issued_at,
            updated_at=cred.updated_at,
        )
    finally:
        await rollback_quietly(db)  # nothing was written: end the transaction, release the connection


async def _write(*, db, users, family, idempotency, principal, clan_id, seen: _Seen, client, clock) -> datetime:
    """Step 3: one transaction. Lock order: clan, then the credential row. The users row is not locked."""
    async with rollback_on_error(db):
        await idempotency.set_lock_timeout(LOCK_TIMEOUT_SECONDS)
        await family.lock_clan(clan_id)
        cred = await users.lock_credential_metadata(seen.user_id)
        owner = await family.get_active_owner(clan_id)
        if owner is None or owner.user_id != seen.user_id:
            raise AppError(ErrorCode.STATE_CONFLICT, "The clan's Owner changed meanwhile; nothing was written.")
        user = await users.get_user_fresh(seen.user_id)
        problem = _state_error(user, cred)
        if problem is not None:
            logger.warning(
                "owner.reset step=db owner_state_changed clan_id=%s request_id=%s", clan_id, get_request_id()
            )
            raise problem
        if (cred.temporary_password_issued_at, cred.updated_at) != (seen.issued_at, seen.updated_at):
            raise AppError(
                ErrorCode.STATE_CONFLICT,
                "The Owner's credentials changed while the password was being reset; nothing was written. Try again.",
            )
        now = clock()
        expires_at = now + timedelta(hours=settings.OWNER_TEMP_PASSWORD_TTL_HOURS)
        cred.must_change_password = True
        cred.temporary_password_issued_at = now
        cred.temporary_password_expires_at = expires_at
        cred.updated_at = now
        revoked = await users.revoke_all_sessions(seen.user_id, reason=SESSIONS_REVOKED_REASON, now=now)
        await users.add_audit_log(
            actor_id=principal.user_id,
            action=AUDIT_ACTION,
            entity_type="user",
            entity_id=seen.user_id,
            clan_id=clan_id,
            old_data=None,
            new_data={"revoked_sessions": revoked, "request_id": get_request_id()},
            ip_address=client.ip_address,
            occurred_at=now,
        )
        await db.commit()
    return expires_at


async def _send(sender: EmailSender, seen: _Seen, password: str, expires_at: datetime):
    """After the commit. A failure to send never undoes the reset."""
    from app.core.email_sender import EmailDeliveryResult

    try:
        return await sender.send_owner_temporary_password(
            to_email=seen.email, display_name=seen.display_name, temporary_password=password,
            expires_at=expires_at,
        )
    except Exception:  # noqa: BLE001 - nothing about the message or the password is logged
        logger.warning("owner.reset email_failed request_id=%s", get_request_id())
        return EmailDeliveryResult(status="FAILED")
