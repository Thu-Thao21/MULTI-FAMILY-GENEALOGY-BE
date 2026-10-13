from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.postgres import AccountRole, FamilyMembership, Permission, Role, RolePermission


class AccessRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_roles(self, account_id: str, family_id: str) -> set[str]:
        result = await self.db.execute(
            select(Role.code)
            .join(AccountRole, AccountRole.role_id == Role.id)
            .where(
                AccountRole.account_id == account_id,
                AccountRole.revoked_at.is_(None),
                or_(AccountRole.family_id == family_id, AccountRole.family_id.is_(None)),
            )
        )
        return set(result.scalars().all())

    async def get_active_membership(
        self, account_id: str, family_id: str
    ) -> FamilyMembership | None:
        result = await self.db.execute(
            select(FamilyMembership).where(
                FamilyMembership.user_id == account_id,
                FamilyMembership.family_id == family_id,
                func.upper(FamilyMembership.status) == "ACTIVE",
                FamilyMembership.revoked_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_granted_permission_codes(self, role_names: set[str]) -> set[str]:
        if not role_names:
            return set()
        result = await self.db.execute(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .where(func.lower(Role.code).in_(role_names))
        )
        return set(result.scalars().all())
