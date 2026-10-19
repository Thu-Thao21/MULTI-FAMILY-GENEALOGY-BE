import uuid
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.postgres import Family, FamilyBranch
from typing import List, Optional


def _as_uuid(val: str | uuid.UUID | None) -> uuid.UUID | None:
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, AttributeError):
        return None


class FamilyRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_family_by_id(self, family_id: str | uuid.UUID) -> Optional[Family]:
        cid = _as_uuid(family_id)
        if not cid:
            return None
        result = await self.db.execute(select(Family).where(Family.clan_id == cid))
        return result.scalar_one_or_none()

    async def update_family(self, family_id: str | uuid.UUID, data: dict) -> Optional[Family]:
        cid = _as_uuid(family_id)
        if not cid:
            return None
        stmt = update(Family).where(Family.clan_id == cid).values(**data).returning(Family)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_branches_by_family(self, family_id: str) -> List[FamilyBranch]:
        result = await self.db.execute(
            select(FamilyBranch).where(FamilyBranch.family_id == family_id).order_by(FamilyBranch.branch_order)
        )
        return list(result.scalars().all())

    async def get_branch_by_id(self, branch_id: str) -> Optional[FamilyBranch]:
        result = await self.db.execute(select(FamilyBranch).where(FamilyBranch.id == branch_id))
        return result.scalar_one_or_none()

    async def create_branch(self, branch: FamilyBranch) -> FamilyBranch:
        self.db.add(branch)
        return branch

    async def update_branch(self, branch_id: str, data: dict) -> Optional[FamilyBranch]:
        stmt = update(FamilyBranch).where(FamilyBranch.id == branch_id).values(**data).returning(FamilyBranch)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def search_public_families(
        self,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Family]:
        stmt = select(Family).where(Family.status == "ACTIVE")
        if search:
            stmt = stmt.where(Family.name.ilike(f"%{search}%"))
        stmt = stmt.order_by(Family.name).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
