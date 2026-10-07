"""User administration contracts (plan section 8, 9).

No credential metadata beyond requires_password_change (no failed_login_count,
locked_until, temporary password timestamps, firebase_uid).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal, Optional

from pydantic import Field, StringConstraints, field_validator

from app.schemas.auth import MembershipStatus, MembershipSummary, UserStatus
from app.schemas.common import (
    MultilineText,
    PageParams,
    RequestModel,
    ResponseModel,
    UserSearchText,
    UtcDatetime,
)

# Target statuses an SA may set. PENDING is provisioning-only, not a manual target.
UserStatusTarget = Literal["ACTIVE", "LOCKED", "SUSPENDED", "DISABLED"]
# family_admin_permissions.permission_code is varchar(100).
PermissionCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"
    ),
]


# ----- GET /admin/users, GET /admin/users/{id} (SA) -----


class AdminUserListQuery(PageParams):
    status: Optional[UserStatus] = None
    q: Optional[UserSearchText] = Field(
        default=None,
        description="Search on email / display_name. Control characters are rejected (422).",
    )


class AdminUserSummary(ResponseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    status: UserStatus
    last_login_at: Optional[UtcDatetime] = None
    created_at: UtcDatetime


class AdminUserDetail(AdminUserSummary):
    username: Optional[str] = None
    phone: Optional[str] = None
    email_verified: bool
    phone_verified: bool
    requires_password_change: bool
    updated_at: UtcDatetime
    memberships: list[MembershipSummary] = Field(default_factory=list)


# ----- PATCH /admin/users/{id}/status (SA) -----


class UserStatusUpdateRequest(RequestModel):
    status: UserStatusTarget
    reason: MultilineText


class UserStatusUpdateResponse(ResponseModel):
    user_id: uuid.UUID
    status: UserStatus
    revoked_session_count: int = Field(
        ge=0, description="Sessions revoked by this change (LOCKED/SUSPENDED/DISABLED)."
    )
    updated_at: UtcDatetime


# ----- GET /clans/{id}/users (BO or delegated FA) -----


class ClanUserListQuery(PageParams):
    membership_status: Optional[MembershipStatus] = None


class ClanUserItem(ResponseModel):
    user_id: uuid.UUID
    display_name: str
    email: str
    user_status: UserStatus
    membership_status: MembershipStatus
    roles: list[str] = Field(default_factory=list)
    is_family_admin: bool
    joined_at: Optional[UtcDatetime] = None


# ----- PUT /clans/{id}/admins/{user_id}/permissions (BO) -----


class FamilyAdminPermissionsUpdateRequest(RequestModel):
    """Full replacement of the FA permission set. Empty list removes all."""

    permission_codes: list[PermissionCode] = Field(max_length=100)

    @field_validator("permission_codes")
    @classmethod
    def _no_duplicates(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("permission_codes must not contain duplicates")
        return value


# ----- POST /clans/{id}/admins (BO) -----


class FamilyAdminAssignRequest(RequestModel):
    """Appoint an ACTIVE member of the clan as Family Admin for the WHOLE clan.

    permission_codes is the initial set and may be empty. There is no branch_id: branch
    scoped assignments are not created through the API (branches are not mapped yet).
    """

    user_id: uuid.UUID
    permission_codes: list[PermissionCode] = Field(default_factory=list, max_length=100)

    @field_validator("permission_codes")
    @classmethod
    def _no_duplicates(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("permission_codes must not contain duplicates")
        return value


class FamilyAdminAssignResponse(ResponseModel):
    clan_id: uuid.UUID
    user_id: uuid.UUID
    assignment_id: uuid.UUID
    permission_codes: list[str]
    created_at: UtcDatetime


class FamilyAdminPermissionsResponse(ResponseModel):
    clan_id: uuid.UUID
    user_id: uuid.UUID
    assignment_id: uuid.UUID
    permission_codes: list[str] = Field(description="Effective permission set after update.")
    updated_at: UtcDatetime
