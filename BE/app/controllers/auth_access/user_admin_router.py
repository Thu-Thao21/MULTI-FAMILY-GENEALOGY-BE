"""User administration routes (api_contract.md section 4). Mounted under /api/v1.

Every route is guarded by require_action: restricted sessions are rejected, the actor's
role/membership/assignment are re-read from the DB, and the action table in
permissions.py is the only authorization source. Authorization runs before the body or
query is validated, so a caller without access never learns about validation details.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.auth_access import user_admin_use_cases as use_cases
from app.controllers.auth_access.use_cases import ClientInfo
from app.db.postgres import get_db
from app.dependencies.auth import Principal, get_user_access_repo
from app.dependencies.permissions import Action, clan_scope_from_path, get_family_repo, require_action
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from app.schemas.common import Page
from app.schemas.users import (
    AdminUserDetail,
    AdminUserListQuery,
    AdminUserSummary,
    ClanUserItem,
    ClanUserListQuery,
    FamilyAdminPermissionsResponse,
    FamilyAdminPermissionsUpdateRequest,
    UserStatusUpdateRequest,
    UserStatusUpdateResponse,
)

router = APIRouter(tags=["user-admin"])


@router.get(
    "/admin/users",
    response_model=Page[AdminUserSummary],
    dependencies=[Depends(require_action(Action.USER_LIST))],
)
async def list_users(
    query: AdminUserListQuery = Depends(),
    users: UserAccessRepository = Depends(get_user_access_repo),
) -> Page[AdminUserSummary]:
    return await use_cases.list_users(users=users, query=query)


@router.get(
    "/admin/users/{user_id}",
    response_model=AdminUserDetail,
    dependencies=[Depends(require_action(Action.USER_READ))],
)
async def get_user(
    user_id: uuid.UUID,
    users: UserAccessRepository = Depends(get_user_access_repo),
    family: FamilyRepository = Depends(get_family_repo),
) -> AdminUserDetail:
    return await use_cases.get_user_detail(users=users, family=family, user_id=user_id)


@router.patch("/admin/users/{user_id}/status", response_model=UserStatusUpdateResponse)
async def update_user_status(
    user_id: uuid.UUID,
    body: UserStatusUpdateRequest,
    request: Request,
    principal: Principal = Depends(require_action(Action.USER_STATUS_UPDATE)),
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
) -> UserStatusUpdateResponse:
    return await use_cases.update_user_status(
        db=db,
        users=users,
        principal=principal,
        user_id=user_id,
        body=body,
        client=ClientInfo.from_request(request),
    )


@router.get(
    "/clans/{clan_id}/users",
    response_model=Page[ClanUserItem],
    dependencies=[Depends(require_action(Action.CLAN_USERS_LIST, clan_scope_from_path()))],
)
async def list_clan_users(
    clan_id: str,  # already validated by clan_scope_from_path (malformed -> 404)
    query: ClanUserListQuery = Depends(),
    users: UserAccessRepository = Depends(get_user_access_repo),
    family: FamilyRepository = Depends(get_family_repo),
) -> Page[ClanUserItem]:
    return await use_cases.list_clan_users(
        users=users, family=family, clan_id=uuid.UUID(clan_id), query=query
    )


@router.put(
    "/clans/{clan_id}/admins/{user_id}/permissions",
    response_model=FamilyAdminPermissionsResponse,
)
async def update_fa_permissions(
    clan_id: str,  # already validated by clan_scope_from_path (malformed -> 404)
    user_id: uuid.UUID,
    body: FamilyAdminPermissionsUpdateRequest,
    request: Request,
    principal: Principal = Depends(
        require_action(Action.CLAN_FA_PERMISSIONS_UPDATE, clan_scope_from_path())
    ),
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
    family: FamilyRepository = Depends(get_family_repo),
) -> FamilyAdminPermissionsResponse:
    return await use_cases.update_fa_permissions(
        db=db,
        users=users,
        family=family,
        principal=principal,
        clan_id=uuid.UUID(clan_id),
        user_id=user_id,
        body=body,
        client=ClientInfo.from_request(request),
    )
