"""Member and Family API Router for Dashboard Tree, MemberList & Relationship Finder.

Directly bridges the UI requests (/families, /members) with Neon PostgreSQL
clans, persons, and relationships.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.models.family.entities import Clan
from app.models.genealogy.entities import Person, Relationship

router = APIRouter(tags=["members-families"])


@router.get("/families")
async def list_families(
    db: AsyncSession = Depends(get_db),
):
    """List all active clans/families with member counts."""
    clans_stmt = select(Clan).where(Clan.status == "ACTIVE").order_by(Clan.name)
    clans_res = await db.execute(clans_stmt)
    clans = clans_res.scalars().all()

    # Get member count per clan
    counts_stmt = (
        select(Person.family_id, func.count(Person.id))
        .group_by(Person.family_id)
    )
    counts_res = await db.execute(counts_stmt)
    count_map = {row[0]: row[1] for row in counts_res.all()}

    results = []
    for c in clans:
        results.append({
            "id": str(c.clan_id),
            "name": c.name,
            "code": c.clan_code,
            "status": c.status,
            "description": f"Dòng họ văn hóa lịch sử {c.name}",
            "founderName": "Nguyễn Văn An",
            "originPlace": "Việt Nam",
            "memberCount": count_map.get(c.clan_id, 0),
        })
    return results


@router.get("/members")
async def list_members(
    family_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """List persons with parent/spouse relations resolved for TreeLayout and MemberList."""
    # Build query on persons
    stmt = select(Person)
    if family_id:
        try:
            f_uuid = uuid.UUID(family_id)
            stmt = stmt.where(Person.family_id == f_uuid)
        except ValueError:
            pass

    if search:
        s = f"%{search.strip()}%"
        stmt = stmt.where(Person.full_name.ilike(s))

    stmt = stmt.order_by(Person.generation, Person.full_name)
    res = await db.execute(stmt)
    persons = res.scalars().all()

    if not persons:
        return {"items": [], "total": 0, "page": page, "limit": limit, "totalPages": 0}

    person_ids = [p.id for p in persons]

    # Pre-fetch relationships for these persons
    rel_stmt = select(Relationship).where(
        or_(
            Relationship.from_member_id.in_(person_ids),
            Relationship.to_member_id.in_(person_ids),
        )
    )
    rel_res = await db.execute(rel_stmt)
    relationships = rel_res.scalars().all()

    # Pre-fetch genders for parent mapping
    person_gender_map = {p.id: (p.gender or "MALE").upper() for p in persons}

    # Map relationships: fatherId, motherId, spouseId
    father_map: Dict[uuid.UUID, uuid.UUID] = {}
    mother_map: Dict[uuid.UUID, uuid.UUID] = {}
    spouse_map: Dict[uuid.UUID, uuid.UUID] = {}

    for r in relationships:
        if r.relationship_type == "PARENT_CHILD":
            child_id = r.to_member_id
            parent_id = r.from_member_id
            p_gender = person_gender_map.get(parent_id, "MALE")
            if p_gender == "MALE":
                father_map[child_id] = parent_id
            else:
                mother_map[child_id] = parent_id
        elif r.relationship_type == "SPOUSE":
            spouse_map[r.from_member_id] = r.to_member_id
            spouse_map[r.to_member_id] = r.from_member_id

    items = []
    for p in persons:
        g = (p.gender or "MALE").lower()
        items.append({
            "id": str(p.id),
            "familyId": str(p.family_id),
            "fullName": p.full_name,
            "otherName": None,
            "gender": g,
            "birthDate": p.birth_date.isoformat() if p.birth_date else None,
            "deathDate": p.death_date.isoformat() if p.death_date else None,
            "isAlive": p.is_alive if p.is_alive is not None else True,
            "generation": p.generation or 1,
            "branch": "Chi Trưởng" if (p.generation or 1) <= 2 else "Nhánh 1",
            "occupation": "Kinh doanh / Quản trị",
            "education": "Đại học",
            "avatarUrl": p.avatar_url,
            "status": p.status,
            "fatherId": str(father_map[p.id]) if p.id in father_map else None,
            "motherId": str(mother_map[p.id]) if p.id in mother_map else None,
            "spouseId": str(spouse_map[p.id]) if p.id in spouse_map else None,
        })

    total = len(items)
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "totalPages": 1,
    }


@router.get("/members/{member_id}")
async def get_member_detail(
    member_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get single member detail."""
    try:
        p_uuid = uuid.UUID(member_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid member_id")

    stmt = select(Person).where(Person.id == p_uuid)
    res = await db.execute(stmt)
    p = res.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Member not found")

    # Get clan name
    clan_stmt = select(Clan.name).where(Clan.clan_id == p.family_id)
    clan_res = await db.execute(clan_stmt)
    clan_name = clan_res.scalar_one_or_none() or "Dòng họ"

    g = (p.gender or "MALE").lower()
    return {
        "id": str(p.id),
        "familyId": str(p.family_id),
        "familyName": clan_name,
        "fullName": p.full_name,
        "otherName": None,
        "gender": g,
        "birthDate": p.birth_date.isoformat() if p.birth_date else None,
        "deathDate": p.death_date.isoformat() if p.death_date else None,
        "isAlive": p.is_alive if p.is_alive is not None else True,
        "generation": p.generation or 1,
        "branch": "Chi Trưởng",
        "occupation": "Kinh doanh / Quản trị",
        "education": "Đại học",
        "bio": p.bio or "Thành viên cốt cán của gia đình.",
        "avatarUrl": p.avatar_url,
        "status": p.status,
        "contacts": [],
        "lifeEvents": [],
        "media": [],
        "skills": [],
        "galleryPhotos": [],
        "careerHistory": [],
    }
