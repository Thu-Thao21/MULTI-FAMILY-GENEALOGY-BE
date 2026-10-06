"""User administration use cases (Mốc F). Use cases own the transaction.

Lock order for a status change (never reverse it, see
active_system_admin_roles_for_update_stmt):
  1. every active SA grant, ORDER BY user_id (only when the new status removes access);
  2. the target user row, FOR NO KEY UPDATE.
A request that waits on step 1 holds nothing else, so it cannot be in a lock cycle.

Audit rows never contain passwords, tokens, firebase_uid or e-mail. The admin-entered
reason goes to audit_logs.reason; session revoke reasons are fixed codes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.controllers.auth_access.use_cases import (
    ClientInfo,
    UnitOfWork,
    build_membership_summaries,
)
from app.core.errors import AppError
from app.core.request_id import get_request_id
from app.dependencies.auth import BLOCKED_STATUSES, Principal
from app.dependencies.permissions import (
    BUSINESS_OWNER_ROLE,
    NON_DELEGABLE_PERMISSION_CODES,
    ensure_not_last_system_admin,
)
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from sqlalchemy.exc import IntegrityError

from app.schemas.common import Page
from app.schemas.errors import ErrorCode
from app.schemas.users import (
    AdminUserDetail,
    AdminUserListQuery,
    AdminUserSummary,
    ClanUserItem,
    ClanUserListQuery,
    FamilyAdminAssignRequest,
    FamilyAdminAssignResponse,
    FamilyAdminPermissionsResponse,
    FamilyAdminPermissionsUpdateRequest,
    UserStatusUpdateRequest,
    UserStatusUpdateResponse,
)

logger = logging.getLogger("mfg.user_admin")

FAMILY_ADMIN_ROLE = "FAMILY_ADMIN"

# PROVISIONAL (api_contract.md section 6, waiting for the lead). Same status -> 409.
STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "ACTIVE": frozenset({"LOCKED", "SUSPENDED", "DISABLED"}),
    "LOCKED": frozenset({"ACTIVE", "SUSPENDED", "DISABLED"}),
    "SUSPENDED": frozenset({"ACTIVE", "LOCKED", "DISABLED"}),
    "DISABLED": frozenset({"ACTIVE"}),
    # PENDING is activated by the first password change, not by hand.
    "PENDING": frozenset({"DISABLED"}),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user_id_from_path(raw: str | uuid.UUID) -> uuid.UUID:
    return raw if isinstance(raw, uuid.UUID) else uuid.UUID(raw)


# ----- GET /admin/users -----


async def list_users(*, users: UserAccessRepository, query: AdminUserListQuery) -> Page[AdminUserSummary]:
    rows = await users.list_users(
        status=query.status, q=query.q or None, limit=query.page_size, offset=query.offset
    )
    total = await users.count_users(status=query.status, q=query.q or None)
    return Page[AdminUserSummary](
        items=[AdminUserSummary.model_validate(u) for u in rows],
        total=total,
        page=query.page,
        page_size=query.page_size,
    )


# ----- GET /admin/users/{user_id} -----


async def get_user_detail(
    *, users: UserAccessRepository, family: FamilyRepository, user_id: uuid.UUID
) -> AdminUserDetail:
    user = await users.get_user_by_id(user_id)
    if user is None:
        raise AppError(ErrorCode.NOT_FOUND)
    cred = await users.get_credential_metadata(user_id)
    grants = await users.list_active_role_grants(user_id)
    memberships = await build_membership_summaries(
        users=users, family=family, user_id=user_id, grants=grants
    )
    base = AdminUserSummary.model_validate(user).model_dump()
    return AdminUserDetail(
        **base,
        username=user.username,
        phone=user.phone,
        email_verified=user.email_verified,
        phone_verified=user.phone_verified,
        requires_password_change=bool(
            user.first_login_required or (cred is not None and cred.must_change_password)
        ),
        updated_at=user.updated_at,
        memberships=memberships,
    )


# ----- PATCH /admin/users/{user_id}/status -----


async def update_user_status(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    principal: Principal,
    user_id: uuid.UUID,
    body: UserStatusUpdateRequest,
    client: ClientInfo,
    now: datetime | None = None,
) -> UserStatusUpdateResponse:
    target_status = body.status
    removes_access = target_status in BLOCKED_STATUSES

    # Step 1 of the lock order: the SA set, before any user row. Taking it on every
    # blocking change (not only for SA targets) keeps the order identical for all callers.
    if removes_access:
        await users.lock_active_system_admin_roles()

    # Step 2: the target row. FOR NO KEY UPDATE, so FK checks from audit inserts that
    # name this user as actor never wait on it.
    user = await users.get_user_for_update(user_id)
    if user is None:
        raise AppError(ErrorCode.NOT_FOUND)

    old_status = user.status
    if target_status not in STATUS_TRANSITIONS.get(old_status, frozenset()):
        raise AppError(
            ErrorCode.STATE_CONFLICT,
            f"A user in status {old_status} cannot be changed to {target_status}.",
        )

    # SA rows are already locked above, so this only reads and decides.
    await ensure_not_last_system_admin(users, user_id, removes_admin_access=removes_access)

    changed_at = now or _now()
    user.status = target_status
    user.updated_at = changed_at
    revoked = 0
    if removes_access:
        revoked = await users.revoke_all_sessions(
            user_id, reason=f"USER_{target_status}", now=changed_at
        )

    await users.add_audit_log(
        actor_id=principal.user_id,
        action="user.status.update",
        entity_type="user",
        entity_id=user_id,
        old_data={"status": old_status},
        new_data={
            "status": target_status,
            "revoked_sessions": revoked,
            "request_id": get_request_id(),
        },
        reason=body.reason,
        ip_address=client.ip_address,
        occurred_at=changed_at,
    )
    await db.commit()
    logger.info(
        "user.status.update from=%s to=%s revoked=%s request_id=%s",
        old_status,
        target_status,
        revoked,
        get_request_id(),
    )
    return UserStatusUpdateResponse(
        user_id=user_id,
        status=target_status,
        revoked_session_count=revoked,
        updated_at=changed_at,
    )


# ----- GET /clans/{clan_id}/users -----


async def list_clan_users(
    *,
    users: UserAccessRepository,
    family: FamilyRepository,
    clan_id: uuid.UUID,
    query: ClanUserListQuery,
) -> Page[ClanUserItem]:
    """Caller was already authorized for this clan (clan.users.list). Every query below
    filters by clan_id; roles are the roles held in THIS clan only."""
    rows = await family.list_clan_members(
        clan_id,
        membership_status=query.membership_status,
        limit=query.page_size,
        offset=query.offset,
    )
    total = await family.count_clan_members(clan_id, membership_status=query.membership_status)
    ids = [user.user_id for _membership, user in rows]
    roles = await users.list_clan_role_codes(clan_id, ids)
    fa_ids = await family.list_active_fa_user_ids(clan_id, ids)
    items = [
        ClanUserItem(
            user_id=user.user_id,
            display_name=user.display_name,
            email=user.email,
            user_status=user.status,
            membership_status=membership.status,
            roles=roles.get(user.user_id, []),
            is_family_admin=user.user_id in fa_ids,
            joined_at=membership.joined_at,
        )
        for membership, user in rows
    ]
    return Page[ClanUserItem](
        items=items, total=total, page=query.page, page_size=query.page_size
    )


# ----- permission codes that may be delegated (POST /admins and PUT .../permissions) -----


async def validate_delegable_codes(users: UserAccessRepository, wanted: set[str]) -> None:
    """Non-delegable code -> 403 FORBIDDEN (the contract's "cấp vượt quyền được ủy quyền");
    code missing from the permissions table -> 422. The non-delegable check goes first and
    needs no query. Codes are never echoed back."""
    if wanted & NON_DELEGABLE_PERMISSION_CODES:
        raise AppError(
            ErrorCode.FORBIDDEN, "One or more permission codes cannot be delegated."
        )
    unknown = wanted - await users.existing_permission_codes(sorted(wanted))
    if unknown:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Invalid input. Fields: permission_codes (unknown permission code)",
        )


# ----- PUT /clans/{clan_id}/admins/{user_id}/permissions -----


async def update_fa_permissions(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    family: FamilyRepository,
    principal: Principal,
    clan_id: uuid.UUID,
    user_id: uuid.UUID,
    body: FamilyAdminPermissionsUpdateRequest,
    client: ClientInfo,
    now: datetime | None = None,
) -> FamilyAdminPermissionsResponse:
    """Replace the permission set of the user's clan-wide FA assignment.

    Only codes present in the permissions table are accepted; no code is denied (the
    lead may add a deny list). An empty list removes every permission and keeps the
    assignment. Creating or revoking an FA assignment is not part of Mốc F.
    """
    wanted = set(body.permission_codes)
    await validate_delegable_codes(users, wanted)

    membership = await family.get_membership(clan_id, user_id)
    if membership is None or membership.status != "ACTIVE" or membership.revoked_at is not None:
        raise AppError(ErrorCode.NOT_FOUND)

    assignments = await family.lock_active_fa_assignments(clan_id, user_id)
    clan_wide = [a for a in assignments if a.branch_id is None]
    if not clan_wide:
        # No assignment, or only branch-limited ones (branches are not mapped yet).
        raise AppError(ErrorCode.NOT_FOUND)
    if len(clan_wide) > 1:
        # The DB does not forbid two active assignments (KI-08); do not guess which one.
        raise AppError(
            ErrorCode.STATE_CONFLICT,
            "The user has more than one active Family Admin assignment in this clan.",
        )
    assignment = clan_wide[0]

    current = await family.list_assignment_permission_codes(assignment.assignment_id)
    to_add, to_remove = sorted(wanted - current), sorted(current - wanted)
    changed_at = now or _now()

    if to_add or to_remove:
        await family.delete_fa_permissions(assignment.assignment_id, to_remove)
        await family.add_fa_permissions(
            assignment.assignment_id, to_add, granted_by=principal.user_id, now=changed_at
        )
        await users.add_audit_log(
            actor_id=principal.user_id,
            clan_id=clan_id,
            action="family_admin.permissions.update",
            entity_type="family_admin_assignment",
            entity_id=assignment.assignment_id,
            old_data={"user_id": str(user_id), "permission_codes": sorted(current)},
            new_data={
                "user_id": str(user_id),
                "permission_codes": sorted(wanted),
                "request_id": get_request_id(),
            },
            ip_address=client.ip_address,
            occurred_at=changed_at,
        )
        await db.commit()
        logger.info(
            "family_admin.permissions.update added=%s removed=%s request_id=%s",
            len(to_add),
            len(to_remove),
            get_request_id(),
        )

    return FamilyAdminPermissionsResponse(
        clan_id=clan_id,
        user_id=user_id,
        assignment_id=assignment.assignment_id,
        permission_codes=sorted(wanted),
        updated_at=changed_at,
    )


# ----- POST /clans/{clan_id}/admins -----


async def assign_family_admin(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    family: FamilyRepository,
    principal: Principal,
    clan_id: uuid.UUID,
    body: FamilyAdminAssignRequest,
    client: ClientInfo,
    now: datetime | None = None,
) -> FamilyAdminAssignResponse:
    """The Business Owner appoints an ACTIVE member of the clan as Family Admin.

    Creates a clan-wide assignment (branch_id NULL), its permission rows and, so that
    roles[] in /auth/me and the clan user list agree, a FAMILY_ADMIN row in user_roles.

    Concurrency: family_admin_assignments has no unique constraint (KI-08), so this code
    is the guarantee. Everything queues on the membership row (FOR NO KEY UPDATE); the
    second of two simultaneous appointments then sees the first one's assignment and gets
    409. uq_active_user_role_scope is a second, DB-level guard for the role row.
    """
    wanted = set(body.permission_codes)
    await validate_delegable_codes(users, wanted)

    target_id = body.user_id
    membership = await family.lock_membership(clan_id, target_id)
    if membership is None or membership.status != "ACTIVE" or membership.revoked_at is not None:
        raise AppError(ErrorCode.NOT_FOUND)  # not an ACTIVE member of THIS clan

    owner = await family.get_active_owner(clan_id)
    if (owner is not None and owner.user_id == target_id) or await users.has_active_role(
        target_id, BUSINESS_OWNER_ROLE, clan_id=clan_id
    ):
        raise AppError(
            ErrorCode.STATE_CONFLICT, "A clan owner cannot be appointed Family Admin."
        )

    if await family.lock_active_fa_assignments(clan_id, target_id):
        raise AppError(ErrorCode.STATE_CONFLICT, "The user is already a Family Admin of this clan.")

    role = await users.get_role_by_code(FAMILY_ADMIN_ROLE)
    if role is None:  # roles are seeded by the lead; this is a deployment error, not input
        raise RuntimeError("role FAMILY_ADMIN is missing")

    changed_at = now or _now()
    try:
        assignment = await family.create_fa_assignment(
            clan_id, target_id, assigned_by=principal.user_id, now=changed_at
        )
        await family.add_fa_permissions(
            assignment.assignment_id, sorted(wanted), granted_by=principal.user_id, now=changed_at
        )
        role_granted = False
        if not await users.has_active_role(target_id, FAMILY_ADMIN_ROLE, clan_id=clan_id):
            await users.add_clan_role(
                user_id=target_id,
                role_id=role.role_id,
                clan_id=clan_id,
                granted_by=principal.user_id,
                now=changed_at,
            )
            role_granted = True
        await users.add_audit_log(
            actor_id=principal.user_id,
            clan_id=clan_id,
            action="family_admin.assign",
            entity_type="family_admin_assignment",
            entity_id=assignment.assignment_id,
            old_data=None,
            new_data={
                "user_id": str(target_id),
                "permission_codes": sorted(wanted),
                "role_granted": role_granted,
                "request_id": get_request_id(),
            },
            ip_address=client.ip_address,
            occurred_at=changed_at,
        )
        await db.commit()
    except IntegrityError:
        # Lost a race the lock did not cover (for example a concurrent grant of the same
        # role row): nothing was written.
        await db.rollback()
        raise AppError(
            ErrorCode.STATE_CONFLICT, "The user is already a Family Admin of this clan."
        ) from None
    logger.info(
        "family_admin.assign permissions=%s role_granted=%s request_id=%s",
        len(wanted),
        role_granted,
        get_request_id(),
    )
    return FamilyAdminAssignResponse(
        clan_id=clan_id,
        user_id=target_id,
        assignment_id=assignment.assignment_id,
        permission_codes=sorted(wanted),
        created_at=changed_at,
    )


# ----- DELETE /clans/{clan_id}/admins/{user_id} -----


async def revoke_family_admin(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    family: FamilyRepository,
    principal: Principal,
    clan_id: uuid.UUID,
    user_id: uuid.UUID,
    client: ClientInfo,
    now: datetime | None = None,
) -> None:
    """The Business Owner revokes a Family Admin completely.

    Every non-revoked assignment of the user in this clan (clan-wide, branch-limited or
    duplicate) gets revoked_at, its permission rows are deleted (the history lives in
    audit_logs) and the FAMILY_ADMIN role row of the clan gets revoked_at. Effective on the
    very next request because authorize() reads the database every time. A membership that
    is no longer ACTIVE does not prevent the revoke.
    """
    if not await family.lock_active_fa_assignments(clan_id, user_id):
        raise AppError(ErrorCode.NOT_FOUND)  # not a Family Admin of this clan

    changed_at = now or _now()
    revoked_ids = await family.revoke_fa_assignments(clan_id, user_id, now=changed_at)
    previous_codes: set[str] = set()
    for assignment_id in revoked_ids:
        previous_codes |= await family.list_assignment_permission_codes(assignment_id)
    await family.delete_all_fa_permissions(clan_id, revoked_ids)
    roles_revoked = await users.revoke_clan_role(
        user_id=user_id, clan_id=clan_id, role_code=FAMILY_ADMIN_ROLE, now=changed_at
    )
    await users.add_audit_log(
        actor_id=principal.user_id,
        clan_id=clan_id,
        action="family_admin.revoke",
        entity_type="family_admin_assignment",
        entity_id=revoked_ids[0] if revoked_ids else None,
        old_data={
            "user_id": str(user_id),
            "assignment_ids": [str(i) for i in revoked_ids],
            "permission_codes": sorted(previous_codes),
        },
        new_data={
            "revoked_assignments": len(revoked_ids),
            "roles_revoked": roles_revoked,
            "request_id": get_request_id(),
        },
        ip_address=client.ip_address,
        occurred_at=changed_at,
    )
    await db.commit()
    logger.info(
        "family_admin.revoke assignments=%s roles=%s request_id=%s",
        len(revoked_ids),
        roles_revoked,
        get_request_id(),
    )
