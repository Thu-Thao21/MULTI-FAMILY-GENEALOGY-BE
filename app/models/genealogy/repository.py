"""M03. Genealogy Model - Data Access Repository."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import and_, delete, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.genealogy.entities import Person, PersonClosure, Relationship


class GenealogyRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_person_by_id(self, person_id: str) -> Optional[Person]:
        result = await self.db.execute(select(Person).where(Person.id == person_id))
        return result.scalar_one_or_none()

    async def get_persons_by_family(self, family_id: str) -> List[Person]:
        result = await self.db.execute(
            select(Person)
            .where(Person.family_id == family_id)
            .order_by(Person.generation, Person.full_name)
        )
        return list(result.scalars().all())

    async def search_persons(
        self,
        family_id: str,
        search: Optional[str] = None,
        gender: Optional[str] = None,
        branch_id: Optional[str] = None,
        is_living: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Person]:
        stmt = select(Person).where(Person.family_id == family_id)
        if search:
            stmt = stmt.where(Person.full_name.ilike(f"%{search}%"))
        if gender:
            stmt = stmt.where(Person.gender == gender)
        if branch_id:
            stmt = stmt.where(Person.branch_id == branch_id)
        if is_living is not None:
            stmt = stmt.where(Person.is_alive == is_living)
        stmt = stmt.order_by(Person.generation, Person.full_name).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create_person(self, person: Person) -> Person:
        self.db.add(person)
        await self.db.flush()
        return person

    async def update_person(self, person_id: str, data: dict) -> Optional[Person]:
        result = await self.db.execute(
            update(Person).where(Person.id == person_id).values(**data).returning(Person)
        )
        return result.scalar_one_or_none()

    async def get_relationship(
        self, relationship_id: str, family_id: str
    ) -> Optional[Relationship]:
        result = await self.db.execute(
            select(Relationship).where(
                Relationship.id == relationship_id,
                Relationship.family_id == family_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_relationships_by_family(self, family_id: str) -> List[Relationship]:
        result = await self.db.execute(
            select(Relationship).where(Relationship.family_id == family_id)
        )
        return list(result.scalars().all())

    async def create_relationship(self, relationship: Relationship) -> Relationship:
        self.db.add(relationship)
        await self.db.flush()
        return relationship

    async def check_existing_relationship(
        self, family_id: str, from_id: str, to_id: str, rel_type: str
    ) -> bool:
        result = await self.db.execute(
            select(Relationship.id).where(
                Relationship.family_id == family_id,
                Relationship.from_member_id == from_id,
                Relationship.to_member_id == to_id,
                Relationship.relationship_type == rel_type,
            )
        )
        return result.scalars().first() is not None

    async def check_existing_spouse_relationship(
        self, family_id: str, first_id: str, second_id: str
    ) -> bool:
        result = await self.db.execute(
            select(Relationship.id).where(
                Relationship.family_id == family_id,
                Relationship.relationship_type == "SPOUSE",
                or_(
                    and_(
                        Relationship.from_member_id == first_id,
                        Relationship.to_member_id == second_id,
                    ),
                    and_(
                        Relationship.from_member_id == second_id,
                        Relationship.to_member_id == first_id,
                    ),
                ),
            )
        )
        return result.scalars().first() is not None

    async def delete_relationship(self, relationship_id: str, family_id: str) -> bool:
        result = await self.db.execute(
            delete(Relationship).where(
                Relationship.id == relationship_id,
                Relationship.family_id == family_id,
            )
        )
        return result.rowcount > 0

    async def delete_spouse_pair(
        self, family_id: str, first_id: str, second_id: str
    ) -> None:
        await self.db.execute(
            delete(Relationship).where(
                Relationship.family_id == family_id,
                Relationship.relationship_type == "SPOUSE",
                or_(
                    and_(
                        Relationship.from_member_id == first_id,
                        Relationship.to_member_id == second_id,
                    ),
                    and_(
                        Relationship.from_member_id == second_id,
                        Relationship.to_member_id == first_id,
                    ),
                ),
            )
        )

    async def insert_closure_self(self, person_id: str, family_id: str) -> None:
        await self.db.execute(
            text(
                """
                INSERT INTO person_closure (ancestor_id, descendant_id, depth)
                SELECT person_id, person_id, 0
                FROM persons
                WHERE person_id = :person_id AND clan_id = :family_id
                ON CONFLICT DO NOTHING
                """
            ),
            {"person_id": person_id, "family_id": family_id},
        )

    async def rebuild_closure_for_parent_child(
        self, parent_id: str, child_id: str, family_id: str
    ) -> None:
        await self.db.execute(
            text(
                """
                INSERT INTO person_closure (ancestor_id, descendant_id, depth)
                SELECT a.ancestor_id, c.descendant_id, a.depth + c.depth + 1
                FROM person_closure a
                CROSS JOIN person_closure c
                JOIN persons ancestor ON ancestor.person_id = a.ancestor_id
                JOIN persons descendant ON descendant.person_id = c.descendant_id
                WHERE a.descendant_id = :parent_id
                  AND c.ancestor_id = :child_id
                  AND ancestor.clan_id = :family_id
                  AND descendant.clan_id = :family_id
                ON CONFLICT DO NOTHING
                """
            ),
            {"family_id": family_id, "parent_id": parent_id, "child_id": child_id},
        )

    async def delete_closure_for_parent_child(
        self, parent_id: str, child_id: str, family_id: str
    ) -> None:
        await self.db.execute(
            text(
                """
                DELETE FROM person_closure
                WHERE ancestor_id IN (
                    SELECT pc.ancestor_id
                    FROM person_closure pc
                    JOIN persons p ON p.person_id = pc.ancestor_id
                    WHERE pc.descendant_id = :parent_id AND p.clan_id = :family_id
                )
                  AND descendant_id IN (
                    SELECT pc.descendant_id
                    FROM person_closure pc
                    JOIN persons p ON p.person_id = pc.descendant_id
                    WHERE pc.ancestor_id = :child_id AND p.clan_id = :family_id
                )
                """
            ),
            {"family_id": family_id, "parent_id": parent_id, "child_id": child_id},
        )

    async def get_max_depth_for_descendant(
        self, descendant_id: str, family_id: str
    ) -> int:
        result = await self.db.execute(
            select(PersonClosure.depth)
            .join(Person, Person.id == PersonClosure.ancestor_id)
            .where(
                PersonClosure.descendant_id == descendant_id,
                Person.family_id == family_id,
            )
            .order_by(PersonClosure.depth.desc())
            .limit(1)
        )
        return result.scalar_one_or_none() or 0

    async def get_ancestors(self, person_id: str, family_id: str) -> List[dict]:
        result = await self.db.execute(
            select(Person, PersonClosure.depth)
            .join(PersonClosure, Person.id == PersonClosure.ancestor_id)
            .where(
                PersonClosure.descendant_id == person_id,
                PersonClosure.depth > 0,
                Person.family_id == family_id,
            )
            .order_by(PersonClosure.depth)
        )
        return [{"person": row[0], "depth": row[1]} for row in result.all()]

    async def get_descendants(self, person_id: str, family_id: str) -> List[dict]:
        result = await self.db.execute(
            select(Person, PersonClosure.depth)
            .join(PersonClosure, Person.id == PersonClosure.descendant_id)
            .where(
                PersonClosure.ancestor_id == person_id,
                PersonClosure.depth > 0,
                Person.family_id == family_id,
            )
            .order_by(PersonClosure.depth)
        )
        return [{"person": row[0], "depth": row[1]} for row in result.all()]
