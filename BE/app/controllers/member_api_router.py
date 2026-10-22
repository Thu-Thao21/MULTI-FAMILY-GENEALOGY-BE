"""Member and Family API Router for Dashboard Tree, MemberList & Relationship Finder.

Directly bridges the UI requests (/families, /members) with Neon PostgreSQL
clans, persons, and relationships.
"""

from __future__ import annotations

import csv
import io
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.models.family.entities import Clan, ClanProfile
from app.models.genealogy.entities import Person, Relationship, FamilyBranch

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


class ClanProfileUpdate(BaseModel):
    name: Optional[str] = None
    originPlace: Optional[str] = Field(None, alias="origin_place")
    history: Optional[str] = None
    ancestralHouseAddress: Optional[str] = Field(None, alias="ancestral_house_address")
    publicDescription: Optional[str] = Field(None, alias="public_description")
    founderPersonId: Optional[str] = Field(None, alias="founder_person_id")
    logoUrl: Optional[str] = Field(None, alias="logo_url")

    class Config:
        populate_by_name = True


class BranchCreate(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    parentBranchId: Optional[str] = Field(None, alias="parent_branch_id")
    leaderPersonId: Optional[str] = Field(None, alias="leader_person_id")

    class Config:
        populate_by_name = True


@router.get("/families/{family_id}/profile")
async def get_clan_profile(
    family_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get clan profile including historical and origin details."""
    try:
        f_uuid = uuid.UUID(family_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid family_id")

    clan_res = await db.execute(select(Clan).where(Clan.clan_id == f_uuid))
    clan = clan_res.scalar_one_or_none()
    if not clan:
        raise HTTPException(status_code=404, detail="Family not found")

    prof_res = await db.execute(select(ClanProfile).where(ClanProfile.clan_id == f_uuid))
    prof = prof_res.scalar_one_or_none()

    return {
        "clanId": str(clan.clan_id),
        "name": clan.name,
        "clanCode": clan.clan_code,
        "status": clan.status,
        "originPlace": prof.origin_place if prof else None,
        "history": prof.history if prof else None,
        "ancestralHouseAddress": prof.ancestral_house_address if prof else None,
        "publicDescription": prof.public_description if prof else None,
        "founderPersonId": str(prof.founder_person_id) if (prof and prof.founder_person_id) else None,
        "updatedAt": prof.updated_at.isoformat() if (prof and prof.updated_at) else None,
    }


@router.put("/families/{family_id}/profile")
async def update_clan_profile(
    family_id: str,
    data: ClanProfileUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update clan profile (BUG-012)."""
    try:
        f_uuid = uuid.UUID(family_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid family_id")

    clan_res = await db.execute(select(Clan).where(Clan.clan_id == f_uuid))
    clan = clan_res.scalar_one_or_none()
    if not clan:
        raise HTTPException(status_code=404, detail="Family not found")

    if data.name:
        clan.name = data.name.strip()

    prof_res = await db.execute(select(ClanProfile).where(ClanProfile.clan_id == f_uuid))
    prof = prof_res.scalar_one_or_none()

    f_founder = None
    if data.founderPersonId:
        try:
            f_founder = uuid.UUID(data.founderPersonId)
        except ValueError:
            pass

    if prof is None:
        prof = ClanProfile(
            clan_id=f_uuid,
            origin_place=data.originPlace,
            history=data.history,
            ancestral_house_address=data.ancestralHouseAddress,
            public_description=data.publicDescription,
            founder_person_id=f_founder,
        )
        db.add(prof)
    else:
        if data.originPlace is not None:
            prof.origin_place = data.originPlace
        if data.history is not None:
            prof.history = data.history
        if data.ancestralHouseAddress is not None:
            prof.ancestral_house_address = data.ancestralHouseAddress
        if data.publicDescription is not None:
            prof.public_description = data.publicDescription
        if data.founderPersonId is not None:
            prof.founder_person_id = f_founder

    await db.commit()
    await db.refresh(clan)

    return {
        "clanId": str(clan.clan_id),
        "name": clan.name,
        "clanCode": clan.clan_code,
        "status": clan.status,
        "originPlace": prof.origin_place if prof else None,
        "history": prof.history if prof else None,
        "ancestralHouseAddress": prof.ancestral_house_address if prof else None,
        "publicDescription": prof.public_description if prof else None,
        "founderPersonId": str(prof.founder_person_id) if (prof and prof.founder_person_id) else None,
        "updatedAt": prof.updated_at.isoformat() if (prof and prof.updated_at) else None,
    }


@router.get("/families/{family_id}/branches")
async def list_family_branches(
    family_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List branches belonging to a family."""
    try:
        f_uuid = uuid.UUID(family_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid family_id")

    stmt = select(FamilyBranch).where(FamilyBranch.family_id == f_uuid).order_by(FamilyBranch.branch_order)
    res = await db.execute(stmt)
    branches = res.scalars().all()

    counts_stmt = (
        select(Person.branch_id, func.count(Person.id))
        .where(Person.family_id == f_uuid, Person.branch_id.isnot(None))
        .group_by(Person.branch_id)
    )
    counts_res = await db.execute(counts_stmt)
    count_map = {row[0]: row[1] for row in counts_res.all()}

    return [
        {
            "id": str(b.id),
            "branchId": str(b.id),
            "familyId": str(b.family_id),
            "name": b.name,
            "code": b.code,
            "description": b.description,
            "branchOrder": b.branch_order,
            "status": b.status,
            "parentBranchId": str(b.parent_branch_id) if b.parent_branch_id else None,
            "memberCount": count_map.get(b.id, 0),
        }
        for b in branches
    ]


@router.post("/families/{family_id}/branches", status_code=status.HTTP_201_CREATED)
async def create_family_branch(
    family_id: str,
    data: BranchCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new branch with unique name constraint and leader person ID (BUG-020, BUG-024)."""
    try:
        f_uuid = uuid.UUID(family_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid family_id")

    clean_name = data.name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Tên Chi/Nhánh không được để trống")

    # Check unique name per family (BUG-020)
    existing = await db.execute(
        select(FamilyBranch).where(
            FamilyBranch.family_id == f_uuid,
            func.lower(FamilyBranch.name) == clean_name.lower(),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tên Chi/Nhánh '{clean_name}' đã tồn tại trong dòng họ.",
        )

    parent_uuid = None
    if data.parentBranchId:
        try:
            parent_uuid = uuid.UUID(data.parentBranchId)
        except ValueError:
            pass

    branch = FamilyBranch(
        family_id=f_uuid,
        name=clean_name,
        code=data.code.strip() if data.code else None,
        description=data.description,
        parent_branch_id=parent_uuid,
    )
    db.add(branch)
    await db.commit()
    await db.refresh(branch)

    return {
        "id": str(branch.id),
        "branchId": str(branch.id),
        "familyId": str(branch.family_id),
        "name": branch.name,
        "code": branch.code,
        "description": branch.description,
        "status": branch.status,
        "parentBranchId": str(branch.parent_branch_id) if branch.parent_branch_id else None,
        "memberCount": 0,
    }


@router.delete("/families/{family_id}/branches/{branch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_family_branch(
    family_id: str,
    branch_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a branch with member check protection (BUG-011)."""
    try:
        f_uuid = uuid.UUID(family_id)
        b_uuid = uuid.UUID(branch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    branch_res = await db.execute(
        select(FamilyBranch).where(FamilyBranch.id == b_uuid, FamilyBranch.family_id == f_uuid)
    )
    branch = branch_res.scalar_one_or_none()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    # Check if branch has members (BUG-011)
    cnt_res = await db.execute(
        select(func.count(Person.id)).where(Person.family_id == f_uuid, Person.branch_id == b_uuid)
    )
    member_count = cnt_res.scalar_one() or 0
    if member_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Không thể xóa Chi nhánh đang có {member_count} thành viên. Vui lòng chuyển thành viên sang Chi khác trước khi xóa.",
        )

    await db.delete(branch)
    await db.commit()


@router.get("/families/{family_id}/persons/export")
@router.get("/persons/export")
async def export_persons(
    family_id: Optional[str] = None,
    format: str = Query("csv"),
    db: AsyncSession = Depends(get_db),
):
    """Export person list as CSV (BUG-025)."""
    stmt = select(Person)
    if family_id:
        try:
            f_uuid = uuid.UUID(family_id)
            stmt = stmt.where(Person.family_id == f_uuid)
        except ValueError:
            pass

    stmt = stmt.order_by(Person.generation, Person.full_name)
    res = await db.execute(stmt)
    persons = res.scalars().all()

    branch_ids = [p.branch_id for p in persons if p.branch_id]
    branch_map = {}
    if branch_ids:
        b_res = await db.execute(select(FamilyBranch).where(FamilyBranch.id.in_(branch_ids)))
        branch_map = {b.id: b.name for b in b_res.scalars().all()}

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow([
        "STT", "Mã thành viên", "Họ và tên", "Giới tính",
        "Ngày sinh", "Ngày mất", "Tình trạng", "Đời thứ", "Chi nhánh", "Ghi chú"
    ])

    for idx, p in enumerate(persons, 1):
        g = "Nam" if (p.gender or "").upper() == "MALE" else ("Nữ" if (p.gender or "").upper() == "FEMALE" else "Khác")
        alive = "Còn sống" if p.is_alive else "Đã mất"
        b_name = branch_map.get(p.branch_id, "Chi Trưởng")
        writer.writerow([
            idx,
            str(p.id),
            p.full_name,
            g,
            p.birth_date.isoformat() if p.birth_date else "",
            p.death_date.isoformat() if p.death_date else "",
            alive,
            p.generation or 1,
            b_name,
            p.bio or ""
        ])

    csv_content = output.getvalue()
    filename = f"danh_sach_thanh_vien_{family_id or 'all'}.csv"
    return Response(
        content=csv_content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

