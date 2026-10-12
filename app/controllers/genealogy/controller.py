"""C03. Genealogy Controller (Request Handling & Genealogy Operations).

Handles:
- Manage person information
- Manage family tree
- Search & query relatives
- Ego-centric (Focus View) processing
- Ancestor / descendant query
- Relationship calculation
- Tree visualization data
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.postgres import Account
from app.schemas.genealogy import PersonCreate, PersonUpdate, RelationshipCreate
from app.services.genealogy import GenealogyService


class GenealogyController:
    def __init__(self, db: AsyncSession, account: Account):
        self.service = GenealogyService(db)
        self.account = account

    async def search_persons(
        self,
        family_id: str,
        search: Optional[str],
        gender: Optional[str],
        branch_id: Optional[str],
        is_living: Optional[bool],
        limit: int,
        offset: int,
    ):
        return await self.service.get_persons_by_family(
            family_id,
            self.account,
            search,
            gender,
            branch_id,
            is_living,
            limit,
            offset,
        )

    async def create_person(self, family_id: str, data: PersonCreate):
        return await self.service.create_person(family_id, data, self.account)

    async def get_person(self, family_id: str, person_id: str):
        return await self.service.get_person_for_family(
            family_id, person_id, self.account
        )

    async def update_person(
        self, family_id: str, person_id: str, data: PersonUpdate
    ):
        return await self.service.update_person(
            family_id, person_id, data, self.account
        )

    async def create_relationship(self, family_id: str, data: RelationshipCreate):
        return await self.service.create_relationship(family_id, data, self.account)

    async def delete_relationship(self, family_id: str, relationship_id: str):
        await self.service.delete_relationship(
            family_id, relationship_id, self.account
        )

    async def get_ancestors(self, family_id: str, person_id: str):
        return await self.service.get_ancestors(family_id, person_id, self.account)

    async def get_descendants(self, family_id: str, person_id: str):
        return await self.service.get_descendants(family_id, person_id, self.account)

    async def get_tree_data(self, family_id: str):
        return await self.service.get_tree_data(family_id, self.account)
