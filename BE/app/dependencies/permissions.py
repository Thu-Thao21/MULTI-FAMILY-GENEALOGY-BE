"""Authorization policy (plan section 9). Default deny.

authorize(principal, action, scope) re-reads roles, membership, ownership and
Family Admin assignments from the database on every call. Nothing comes from
the token.

Decisions (C2, see docs/api_contract.md "Giả định"):
  - SA and BO are decided by role code (user_roles + roles.code).
    role_permissions is NOT consulted and is not seeded.
  - FA is decided by family_admin_assignments + family_admin_permissions.
  - BO = active BUSINESS_OWNER grant in that clan + active ownership row
    (clan_ownership_history.ended_at IS NULL) + ACTIVE membership.
  - FA = ACTIVE membership + non-revoked assignment in that clan holding the
    permission code + branch coverage (assignment.branch_id NULL covers the clan,
    otherwise it must equal the resource branch_id).
  - Clan-scope actions require clans.status = ACTIVE. SA (system scope) and
    /auth/* routes are not affected.
  - Caller cannot see the clan (no ACTIVE membership) -> NOT_FOUND (404).
    Caller is in the clan but lacks permission or the clan is not ACTIVE
    -> FORBIDDEN (403).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Callable, Protocol

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.postgres import get_db
from app.dependencies.auth import Principal, get_principal, get_user_access_repo
from app.models.family.entities import Clan, ClanMembership, ClanOwnershipHistory
from app.models.family.repository import FamilyRepository
from app.models.user_access.entities import User as UserEntity
from app.models.user_access.repository import SYSTEM_ADMIN_ROLE, UserAccessRepository
from app.schemas.errors import ErrorCode

BUSINESS_OWNER_ROLE = "BUSINESS_OWNER"


class Action(StrEnum):
    # System scope, System Admin only.
    REGISTRATION_LIST = "registration.list"
    REGISTRATION_READ = "registration.read"
    REGISTRATION_REVIEW = "registration.review"
    BUSINESS_CREATE = "business.create"
    CLAN_OWNER_PROVISION = "clan.owner.provision"
    PROVISIONING_JOB_READ = "provisioning_job.read"
    CLAN_ACTIVATE = "clan.activate"
    USER_LIST = "user.list"
    USER_READ = "user.read"
    USER_STATUS_UPDATE = "user.status.update"
    # Clan scope.
    CLAN_USERS_LIST = "clan.users.list"
    CLAN_FA_PERMISSIONS_UPDATE = "clan.fa_permissions.update"
    CLAN_FA_ASSIGN = "clan.fa.assign"
    CLAN_FA_REVOKE = "clan.fa.revoke"


class ScopeKind(Enum):
    SYSTEM = "system"
    CLAN = "clan"


@dataclass(frozen=True)
class Rule:
    scope: ScopeKind
    allow_owner: bool = False
    fa_permission: str | None = None

    def describe(self) -> str:
        if self.scope is ScopeKind.SYSTEM:
            return "SA (role SYSTEM_ADMIN, clan_id NULL)"
        who = []
        if self.allow_owner:
            who.append("BO")
        if self.fa_permission:
            who.append(f"FA with {self.fa_permission}")
        return " or ".join(who) + "; clan ACTIVE" if who else "nobody"


_SA = Rule(ScopeKind.SYSTEM)

ACTION_RULES: dict[Action, Rule] = {
    Action.REGISTRATION_LIST: _SA,
    Action.REGISTRATION_READ: _SA,
    Action.REGISTRATION_REVIEW: _SA,
    Action.BUSINESS_CREATE: _SA,
    Action.CLAN_OWNER_PROVISION: _SA,
    Action.PROVISIONING_JOB_READ: _SA,
    Action.CLAN_ACTIVATE: _SA,
    Action.USER_LIST: _SA,
    Action.USER_READ: _SA,
    Action.USER_STATUS_UPDATE: _SA,
    Action.CLAN_USERS_LIST: Rule(
        ScopeKind.CLAN, allow_owner=True, fa_permission="MEMBER_ACCOUNT_MANAGE"
    ),
    # BO only: "không cấp vượt quyền được ủy quyền" -> FA cannot edit FA permissions.
    Action.CLAN_FA_PERMISSIONS_UPDATE: Rule(ScopeKind.CLAN, allow_owner=True),
    # Appointing / revoking a Family Admin is BO only, like editing their permissions.
    Action.CLAN_FA_ASSIGN: Rule(ScopeKind.CLAN, allow_owner=True),
    Action.CLAN_FA_REVOKE: Rule(ScopeKind.CLAN, allow_owner=True),
}

# Permission codes that exist in the permissions table but may NOT be delegated to a
# Family Admin (POST /clans/{id}/admins and PUT .../permissions answer 403 FORBIDDEN).
# ADMIN_MANAGE ("Quản lý Family Admin") would let a Family Admin manage Family Admins,
# which is reserved to the Business Owner. The lead may extend this set (KI-09).
NON_DELEGABLE_PERMISSION_CODES: frozenset[str] = frozenset({"ADMIN_MANAGE"})


@dataclass(frozen=True)
class ResourceScope:
    clan_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None

    @classmethod
    def system(cls) -> "ResourceScope":
        return cls()

    @classmethod
    def clan(cls, clan_id: uuid.UUID, branch_id: uuid.UUID | None = None) -> "ResourceScope":
        return cls(clan_id=clan_id, branch_id=branch_id)


class RoleRepository(Protocol):
    async def has_active_role(
        self, user_id: uuid.UUID, role_code: str, *, clan_id: uuid.UUID | None
    ) -> bool: ...


class ClanAccessRepository(Protocol):
    async def get_clan_by_id(self, clan_id: uuid.UUID) -> Clan | None: ...

    async def get_membership(
        self, clan_id: uuid.UUID, user_id: uuid.UUID
    ) -> ClanMembership | None: ...

    async def get_active_owner(self, clan_id: uuid.UUID) -> ClanOwnershipHistory | None: ...

    async def list_active_fa_grants(
        self, clan_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, uuid.UUID | None, str]]: ...


def _forbidden() -> AppError:
    return AppError(ErrorCode.FORBIDDEN)


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND)


async def is_active_owner(
    user_id: uuid.UUID,
    clan_id: uuid.UUID,
    roles: RoleRepository,
    family: ClanAccessRepository,
) -> bool:
    """Role BUSINESS_OWNER in this clan + the active ownership row is the user's.

    Membership and clan status are checked by the caller (authorize does it first).
    """
    if not await roles.has_active_role(user_id, BUSINESS_OWNER_ROLE, clan_id=clan_id):
        return False
    owner = await family.get_active_owner(clan_id)
    return owner is not None and owner.ended_at is None and owner.user_id == user_id


async def _is_active_owner(
    principal: Principal,
    clan_id: uuid.UUID,
    roles: RoleRepository,
    family: ClanAccessRepository,
) -> bool:
    return await is_active_owner(principal.user_id, clan_id, roles, family)


def system_admin_actions() -> list[str]:
    """Action codes an active System Admin may perform (GET /auth/me, provisional)."""
    return sorted(a.value for a, r in ACTION_RULES.items() if r.scope is ScopeKind.SYSTEM)


def owner_actions() -> list[str]:
    """Clan action codes an effective Business Owner may perform (GET /auth/me, provisional)."""
    return sorted(
        a.value for a, r in ACTION_RULES.items() if r.scope is ScopeKind.CLAN and r.allow_owner
    )


async def _fa_covers(
    principal: Principal,
    scope: ResourceScope,
    permission_code: str,
    family: ClanAccessRepository,
) -> bool:
    assert scope.clan_id is not None
    for _assignment_id, branch_id, code in await family.list_active_fa_grants(
        scope.clan_id, principal.user_id
    ):
        if code != permission_code:
            continue
        # NULL branch on the assignment = whole clan. A branch-limited assignment
        # only covers resources of that exact branch (branches are not mapped yet,
        # so sub-branch inheritance is not supported).
        if branch_id is None or branch_id == scope.branch_id:
            return True
    return False


async def authorize(
    principal: Principal,
    action: Action | str,
    scope: ResourceScope,
    *,
    roles: RoleRepository,
    family: ClanAccessRepository,
) -> None:
    """Raise AppError unless the principal may perform action on scope."""
    try:
        rule = ACTION_RULES[Action(action)]
    except (ValueError, KeyError):
        raise _forbidden() from None  # unknown action: default deny

    if rule.scope is ScopeKind.SYSTEM:
        if await roles.has_active_role(principal.user_id, SYSTEM_ADMIN_ROLE, clan_id=None):
            return
        raise _forbidden()

    # Clan scope.
    if scope.clan_id is None:
        raise _forbidden()  # misconfigured route: deny

    clan = await family.get_clan_by_id(scope.clan_id)
    if clan is None:
        raise _not_found()
    membership = await family.get_membership(scope.clan_id, principal.user_id)
    if membership is None or membership.status != "ACTIVE" or membership.revoked_at is not None:
        raise _not_found()  # do not reveal other clans
    if clan.status != "ACTIVE":
        raise _forbidden()

    if rule.allow_owner and await _is_active_owner(principal, scope.clan_id, roles, family):
        return
    if rule.fa_permission and await _fa_covers(principal, scope, rule.fa_permission, family):
        return
    raise _forbidden()


# ----- Last System Admin guard -----


class SystemAdminGuardRepository(Protocol):
    async def lock_active_system_admin_roles(self) -> None: ...

    async def get_user_by_id(self, user_id: uuid.UUID) -> UserEntity | None: ...

    async def has_active_role(
        self, user_id: uuid.UUID, role_code: str, *, clan_id: uuid.UUID | None
    ) -> bool: ...

    async def count_active_system_admins(
        self, *, exclude_user_id: uuid.UUID | None = None
    ) -> int: ...


async def ensure_not_last_system_admin(
    repo: SystemAdminGuardRepository,
    target_user_id: uuid.UUID,
    *,
    removes_admin_access: bool,
) -> None:
    """Block an operation that would leave zero ACTIVE System Admins.

    Call INSIDE the same transaction as the status change / SA role revoke,
    before writing. It row-locks every active SA grant (SELECT ... FOR UPDATE),
    so two concurrent requests locking two different SAs are serialized.

    removes_admin_access: True when setting status LOCKED/SUSPENDED/DISABLED or
    revoking the SYSTEM_ADMIN role. Applies to self-lock as well.
    """
    if not removes_admin_access:
        return
    await repo.lock_active_system_admin_roles()

    target = await repo.get_user_by_id(target_user_id)
    if target is None or target.status != "ACTIVE":
        return  # target does not count as an active SA today
    if not await repo.has_active_role(target_user_id, SYSTEM_ADMIN_ROLE, clan_id=None):
        return
    if await repo.count_active_system_admins(exclude_user_id=target_user_id) == 0:
        raise AppError(
            ErrorCode.STATE_CONFLICT,
            "This would leave no active System Admin.",
        )


# ----- FastAPI wiring -----

ScopeResolver = Callable[[Request], ResourceScope]


def system_scope(_request: Request) -> ResourceScope:
    return ResourceScope.system()


def clan_scope_from_path(param: str = "clan_id") -> ScopeResolver:
    def resolve(request: Request) -> ResourceScope:
        raw = request.path_params.get(param)
        try:
            return ResourceScope.clan(uuid.UUID(str(raw)))
        except (TypeError, ValueError):
            raise _not_found() from None

    return resolve


async def get_family_repo(db: AsyncSession = Depends(get_db)) -> FamilyRepository:
    return FamilyRepository(db)


def require_action(action: Action, scope: ScopeResolver = system_scope):
    """Dependency factory: authenticate (non-restricted) + authorize action.

    Never use with get_principal_allow_restricted: business actions always
    reject restricted sessions.
    """

    async def dependency(
        request: Request,
        principal: Principal = Depends(get_principal),
        roles: UserAccessRepository = Depends(get_user_access_repo),
        family: FamilyRepository = Depends(get_family_repo),
    ) -> Principal:
        await authorize(principal, action, scope(request), roles=roles, family=family)
        return principal

    return dependency
