from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.postgres import Account, FamilyBranch
from app.repositories.family_repository import FamilyRepository
from app.schemas.family import BranchCreate, BranchUpdate, FamilyUpdate
from app.services.access_service import AccessService

class FamilyService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = FamilyRepository(db)
        self.access = AccessService(db)

    async def get_family_detail(self, family_id: str, account: Account):
        await self.access.require_family_permission(account, family_id, "family.view")
        family = await self.repo.get_family_by_id(family_id)
        if not family:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Family not found")
        return family

    async def update_family(self, family_id: str, data: FamilyUpdate, account: Account):
        await self.access.require_family_permission(account, family_id, "family.update")
        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            family = await self.repo.get_family_by_id(family_id)
            if not family:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Family not found")
            return family
        try:
            updated_family = await self.repo.update_family(family_id, update_data)
            if not updated_family:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Family not found")
            await self.db.commit()
            return updated_family
        except Exception:
            await self.db.rollback()
            raise

    async def get_branches(self, family_id: str, account: Account):
        await self.access.require_family_permission(account, family_id, "branch.view")
        if not await self.repo.get_family_by_id(family_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Family not found")
        return await self.repo.get_branches_by_family(family_id)

    async def create_branch(self, family_id: str, data: BranchCreate, account: Account):
        await self.access.require_family_permission(account, family_id, "branch.manage")
        if not await self.repo.get_family_by_id(family_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Family not found")

        # If parent_branch_id is provided, validate it belongs to the same family
        if data.parent_branch_id:
            parent_branch = await self.repo.get_branch_by_id(data.parent_branch_id)
            if not parent_branch or parent_branch.family_id != family_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid parent branch")

        branch = FamilyBranch(
            family_id=family_id,
            name=data.name,
            code=data.code or f"BR-{family_id[:8]}-{data.name[:16]}",
            parent_branch_id=data.parent_branch_id,
            branch_order=data.branch_order,
            description=data.description,
            status=data.status,
        )
        try:
            created = await self.repo.create_branch(branch)
            await self.db.commit()
            return created
        except Exception:
            await self.db.rollback()
            raise

    async def update_branch(self, family_id: str, branch_id: str, data: BranchUpdate, account: Account):
        await self.access.require_family_permission(account, family_id, "branch.manage")
        branch = await self.repo.get_branch_by_id(branch_id)
        if not branch or branch.family_id != family_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found in this family")

        update_data = data.model_dump(exclude_unset=True)
        if 'parent_branch_id' in update_data and update_data['parent_branch_id']:
            parent_branch = await self.repo.get_branch_by_id(update_data['parent_branch_id'])
            if not parent_branch or parent_branch.family_id != family_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid parent branch")
            if update_data['parent_branch_id'] == branch_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A branch cannot be its own parent")

        try:
            updated = await self.repo.update_branch(branch_id, update_data)
            await self.db.commit()
            return updated
        except Exception:
            await self.db.rollback()
            raise
