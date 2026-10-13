from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.postgres import Family, FamilyBranch
from typing import List, Optional

class FamilyRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_family_by_id(self, family_id: str) -> Optional[Family]:
        result = await self.db.execute(select(Family).where(Family.id == family_id))
        return result.scalar_one_or_none()

    async def update_family(self, family_id: str, data: dict) -> Optional[Family]:
        stmt = update(Family).where(Family.id == family_id).values(**data).returning(Family)
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
