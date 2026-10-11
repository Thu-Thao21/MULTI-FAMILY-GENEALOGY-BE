from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.postgres import Account
from app.schemas.family import BranchCreate, BranchUpdate, FamilyUpdate
from app.services.family_service import FamilyService


class FamilyController:
    def __init__(self, db: AsyncSession, account: Account):
        self.service = FamilyService(db)
        self.account = account

    async def get_family(self, family_id: str):
        return await self.service.get_family_detail(family_id, self.account)

    async def update_family(self, family_id: str, data: FamilyUpdate):
        return await self.service.update_family(family_id, data, self.account)

    async def get_branches(self, family_id: str):
        return await self.service.get_branches(family_id, self.account)

    async def create_branch(self, family_id: str, data: BranchCreate):
        return await self.service.create_branch(family_id, data, self.account)

    async def update_branch(self, family_id: str, branch_id: str, data: BranchUpdate):
        return await self.service.update_branch(family_id, branch_id, data, self.account)
