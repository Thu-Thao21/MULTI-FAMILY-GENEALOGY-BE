from __future__ import annotations

import uuid
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.postgres import AccountRole, FamilyMembership, Permission, Role, RolePermission


def _as_uuid(val: str | uuid.UUID | None) -> uuid.UUID | None:
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, AttributeError):
        return None


class AccessRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_roles(self, account_id: str | uuid.UUID, family_id: str | uuid.UUID | None) -> set[str]:
        uid = _as_uuid(account_id)
        cid = _as_uuid(family_id)
        if not uid:
            return set()

        stmt = (
            select(Role.code)
            .join(AccountRole, AccountRole.role_id == Role.role_id)
            .where(
                AccountRole.user_id == uid,
                AccountRole.revoked_at.is_(None),
                or_(AccountRole.clan_id == cid, AccountRole.clan_id.is_(None)),
            )
        )
        result = await self.db.execute(stmt)
        return set(result.scalars().all())

    async def get_active_membership(
        self, account_id: str | uuid.UUID, family_id: str | uuid.UUID
    ) -> FamilyMembership | None:
        uid = _as_uuid(account_id)
        cid = _as_uuid(family_id)
        if not uid or not cid:
            return None

        stmt = select(FamilyMembership).where(
            FamilyMembership.user_id == uid,
            FamilyMembership.clan_id == cid,
            func.upper(FamilyMembership.status) == "ACTIVE",
            FamilyMembership.revoked_at.is_(None),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_granted_permission_codes(self, role_names: set[str]) -> set[str]:
        if not role_names:
            return set()
        stmt = (
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
            .join(Role, Role.role_id == RolePermission.role_id)
            .where(func.lower(Role.code).in_([r.lower() for r in role_names]))
        )
        result = await self.db.execute(stmt)
        return set(result.scalars().all())

