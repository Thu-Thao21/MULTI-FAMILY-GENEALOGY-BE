from __future__ import annotations

from typing import Optional
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.postgres import Account, Person, Relationship
from app.repositories.family_repository import FamilyRepository
from app.repositories.genealogy_repository import GenealogyRepository
from app.schemas.genealogy import (
    PersonCreate,
    PersonResponse,
    PersonUpdate,
    RelationshipCreate,
    RelationshipResponse,
    TreeDataResponse,
    TreeNode,
)
from app.services.access_service import AccessService


PARENT_RELATIONSHIP_TYPES = {
    "PARENT",
    "FATHER",
    "MOTHER",
    "ADOPTIVE_PARENT",
    "STEP_PARENT",
}
VALID_RELATIONSHIP_TYPES = PARENT_RELATIONSHIP_TYPES | {"SPOUSE"}

RELATIONSHIP_TYPE_TO_DATABASE = {
    "PARENT": ("PARENT_CHILD", "BIOLOGICAL"),
    "FATHER": ("PARENT_CHILD", "BIOLOGICAL"),
    "MOTHER": ("PARENT_CHILD", "BIOLOGICAL"),
    "ADOPTIVE_PARENT": ("PARENT_CHILD", "ADOPTIVE"),
    "STEP_PARENT": ("PARENT_CHILD", "STEP"),
    "SPOUSE": ("SPOUSE", None),
}

DATABASE_PARENT_TYPE_TO_API = {
    "BIOLOGICAL": "PARENT",
    "ADOPTIVE": "ADOPTIVE_PARENT",
    "STEP": "STEP_PARENT",
    "GUARDIAN": "PARENT",
}


def _relationship_type_for_api(relationship: Relationship) -> str:
    relationship_type = relationship.relationship_type.upper()
    if relationship_type != "PARENT_CHILD":
        return relationship_type
    parent_type = (relationship.parent_type or "").upper()
    return DATABASE_PARENT_TYPE_TO_API.get(parent_type, "PARENT")


class GenealogyService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = GenealogyRepository(db)
        self.family_repo = FamilyRepository(db)
        self.access = AccessService(db)

    @staticmethod
    def _to_person_response(person: Person) -> PersonResponse:
        return PersonResponse(
            id=person.id,
            familyId=person.family_id,
            branchId=person.branch_id,
            fullName=person.full_name,
            gender=person.gender or "unknown",
            birthDate=person.birth_date,
            deathDate=person.death_date,
            generation=person.generation or 1,
            avatarUrl=person.avatar_url,
            isLiving=True if person.is_alive is None else person.is_alive,
            status=person.status,
        )

    async def _get_person_for_family(self, family_id: str, person_id: str) -> Person:
        person = await self.repo.get_person_by_id(person_id)
        if not person:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
        if str(person.family_id) != str(family_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Person does not belong to this family",
            )
        return person

    async def _validate_branch(self, family_id: str, branch_id: str | None) -> None:
        if not branch_id:
            return

        branch = await self.family_repo.get_branch_by_id(branch_id)

        print("===== DEBUG VALIDATE BRANCH =====")
        print("branch_id request =", repr(branch_id))
        print("family_id request =", repr(family_id))
        print("branch =", branch)

        if branch:
            print("branch.id =", repr(branch.id))
            print("branch.family_id =", repr(branch.family_id))
            print("branch.family_id type =", type(branch.family_id))
            print("family_id type =", type(family_id))
            print(
                "compare =",
                str(branch.family_id).strip() == str(family_id).strip()
            )

        if not branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch not found",
            )

        if str(branch.family_id).strip() != str(family_id).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Branch family mismatch: "
                    f"branch={branch.family_id}, request={family_id}"
                ),
            )

    async def get_person_for_family(
        self, family_id: str, person_id: str, account: Account
    ) -> PersonResponse:
        await self.access.require_family_permission(account, family_id, "person.view")
        return self._to_person_response(await self._get_person_for_family(family_id, person_id))

    async def get_persons_by_family(
        self,
        family_id: str,
        account: Account,
        search: Optional[str] = None,
        gender: Optional[str] = None,
        branch_id: Optional[str] = None,
        is_living: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PersonResponse]:
        await self.access.require_family_permission(account, family_id, "person.view")
        family = await self.family_repo.get_family_by_id(family_id)
        if not family:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Family not found")
        persons = await self.repo.search_persons(
            family_id, search, gender, branch_id, is_living, limit, offset
        )
        return [self._to_person_response(person) for person in persons]

    async def create_person(
        self, family_id: str, data: PersonCreate, account: Account
    ) -> PersonResponse:
        await self.access.require_family_permission(account, family_id, "person.create")
        if not await self.family_repo.get_family_by_id(family_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Family not found")
        await self._validate_branch(family_id, data.branch_id)

        person = Person(
            id=str(uuid4()),
            family_id=family_id,
            branch_id=data.branch_id,
            full_name=data.full_name,
            gender=data.gender,
            birth_date=data.birth_date,
            death_date=data.death_date,
            avatar_url=data.avatar_url,
            is_alive=data.is_alive,
            status=data.status,
            generation=1,
            created_by=account.id,
        )
        try:
            await self.repo.create_person(person)
            await self.repo.insert_closure_self(person.id, family_id)
            await self.db.commit()
            return self._to_person_response(person)
        except Exception:
            await self.db.rollback()
            raise

    async def update_person(
        self,
        family_id: str,
        person_id: str,
        data: PersonUpdate,
        account: Account,
    ) -> PersonResponse:
        await self.access.require_family_permission(account, family_id, "person.update")
        person = await self._get_person_for_family(family_id, person_id)
        update_data = data.model_dump(exclude_unset=True)
        if "branch_id" in update_data:
            await self._validate_branch(family_id, update_data["branch_id"])
        if not update_data:
            return self._to_person_response(person)

        try:
            updated = await self.repo.update_person(person_id, update_data)
            await self.db.commit()
            return self._to_person_response(updated)
        except Exception:
            await self.db.rollback()
            raise

    async def create_relationship(
        self, family_id: str, data: RelationshipCreate, account: Account
    ) -> RelationshipResponse:
        await self.access.require_family_permission(account, family_id, "relationship.manage")
        from_person = await self._get_person_for_family(family_id, data.from_member_id)
        to_person = await self._get_person_for_family(family_id, data.to_member_id)

        if from_person.id == to_person.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create relationship with self",
            )

        api_relationship_type = data.relationship_type.upper()
        if api_relationship_type not in VALID_RELATIONSHIP_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid relationship type",
            )

        database_relationship_type, database_parent_type = (
            RELATIONSHIP_TYPE_TO_DATABASE[api_relationship_type]
        )

        if api_relationship_type == "SPOUSE":
            relationship_from_id, relationship_to_id = sorted(
                (str(from_person.id), str(to_person.id))
            )
            exists = await self.repo.check_existing_spouse_relationship(
                family_id, relationship_from_id, relationship_to_id
            )
        else:
            relationship_from_id = from_person.id
            relationship_to_id = to_person.id
            exists = await self.repo.check_existing_relationship(
                family_id,
                relationship_from_id,
                relationship_to_id,
                database_relationship_type,
            )
        if exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Relationship already exists",
            )

        if (
            api_relationship_type == "FATHER"
            and (from_person.gender or "").upper() != "MALE"
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Father must be male",
            )
        if (
            api_relationship_type == "MOTHER"
            and (from_person.gender or "").upper() != "FEMALE"
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mother must be female",
            )

        if api_relationship_type in PARENT_RELATIONSHIP_TYPES:
            ancestors = await self.repo.get_ancestors(from_person.id, family_id)
            if any(item["person"].id == to_person.id for item in ancestors):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Ancestry cycle detected",
                )

        relationship = Relationship(
            id=str(uuid4()),
            family_id=family_id,
            from_member_id=relationship_from_id,
            to_member_id=relationship_to_id,
            relationship_type=database_relationship_type,
            parent_type=database_parent_type,
            status="ACTIVE",
            created_by=account.id,
        )
        try:
            created = await self.repo.create_relationship(relationship)
            if database_relationship_type == "PARENT_CHILD":
                await self.repo.insert_closure_self(from_person.id, family_id)
                await self.repo.insert_closure_self(to_person.id, family_id)
                await self.repo.rebuild_closure_for_parent_child(
                    from_person.id, to_person.id, family_id
                )
                descendants = await self.repo.get_descendants(to_person.id, family_id)
                for person in [to_person] + [item["person"] for item in descendants]:
                    max_depth = await self.repo.get_max_depth_for_descendant(person.id, family_id)
                    await self.repo.update_person(person.id, {"generation": max_depth + 1})

            await self.db.commit()
            return RelationshipResponse(
                id=created.id,
                fromMemberId=created.from_member_id,
                toMemberId=created.to_member_id,
                relationshipType=api_relationship_type,
                notes=None,
            )
        except IntegrityError as exc:
            await self.db.rollback()
            if api_relationship_type == "SPOUSE":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Spouse relationship already exists",
                ) from exc
            raise
        except Exception:
            await self.db.rollback()
            raise

    async def delete_relationship(
        self, family_id: str, relationship_id: str, account: Account
    ) -> None:
        await self.access.require_family_permission(account, family_id, "relationship.manage")
        relationship = await self.repo.get_relationship(relationship_id, family_id)
        if not relationship:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Relationship not found",
            )
        from_person = await self._get_person_for_family(
            family_id, relationship.from_member_id
        )
        to_person = await self._get_person_for_family(family_id, relationship.to_member_id)

        try:
            if relationship.relationship_type == "PARENT_CHILD":
                await self.repo.delete_closure_for_parent_child(
                    from_person.id, to_person.id, family_id
                )
                await self.repo.delete_relationship(relationship_id, family_id)
                descendants = await self.repo.get_descendants(to_person.id, family_id)
                for person in [to_person] + [item["person"] for item in descendants]:
                    max_depth = await self.repo.get_max_depth_for_descendant(person.id, family_id)
                    await self.repo.update_person(person.id, {"generation": max_depth + 1})
            elif relationship.relationship_type == "SPOUSE":
                await self.repo.delete_spouse_pair(family_id, from_person.id, to_person.id)
            else:
                await self.repo.delete_relationship(relationship_id, family_id)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

    async def get_ancestors(
        self, family_id: str, person_id: str, account: Account
    ) -> list[dict]:
        await self.access.require_family_permission(account, family_id, "relationship.view")
        await self._get_person_for_family(family_id, person_id)
        ancestors = await self.repo.get_ancestors(person_id, family_id)
        return [
            {"person": self._to_person_response(item["person"]), "depth": item["depth"]}
            for item in ancestors
        ]

    async def get_descendants(
        self, family_id: str, person_id: str, account: Account
    ) -> list[dict]:
        await self.access.require_family_permission(account, family_id, "relationship.view")
        await self._get_person_for_family(family_id, person_id)
        descendants = await self.repo.get_descendants(person_id, family_id)
        return [
            {"person": self._to_person_response(item["person"]), "depth": item["depth"]}
            for item in descendants
        ]

    async def get_tree_data(self, family_id: str, account: Account) -> TreeDataResponse:
        await self.access.require_family_permission(account, family_id, "tree.view")
        if not await self.family_repo.get_family_by_id(family_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Family not found")

        persons = await self.repo.get_persons_by_family(family_id)
        relationships = await self.repo.get_relationships_by_family(family_id)
        nodes = [
            TreeNode(
                id=person.id,
                fullName=person.full_name,
                gender=person.gender or "unknown",
                generation=person.generation or 1,
                branchId=person.branch_id,
                avatarUrl=person.avatar_url,
                status=person.status,
            )
            for person in persons
        ]

        edges: list[RelationshipResponse] = []
        spouse_pairs: set[tuple[str, str]] = set()
        for relationship in relationships:
            from_id = relationship.from_member_id
            to_id = relationship.to_member_id
            if relationship.relationship_type == "SPOUSE":
                pair = tuple(sorted((from_id, to_id)))
                if pair in spouse_pairs:
                    continue
                spouse_pairs.add(pair)
                from_id, to_id = pair
            edges.append(
                RelationshipResponse(
                    id=relationship.id,
                    fromMemberId=from_id,
                    toMemberId=to_id,
                    relationshipType=_relationship_type_for_api(relationship),
                    notes=None,
                )
            )

        return TreeDataResponse(nodes=nodes, edges=edges)
