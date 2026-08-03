from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.models.postgres import Member
from app.schemas.member_schemas import (
    FamilyOut,
    MemberCreateIn,
    MemberDetailOut,
    MemberListOut,
    MemberUpdateIn,
)
from app.services.member_service import (
    get_families,
    get_member_detail,
    get_members,
)

router = APIRouter(tags=["members"])


@router.get("/members", response_model=MemberListOut)
async def list_members(
    family_id: Optional[str] = Query(None, alias="family_id"),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Danh sách thành viên có phân trang + tìm kiếm."""
    return await get_members(db, family_id=family_id, search=search, page=page, limit=limit)


@router.get("/members/{member_id}", response_model=MemberDetailOut)
async def get_member(member_id: str, db: AsyncSession = Depends(get_db)):
    """Chi tiết thành viên kèm contacts, life events, media, skills."""
    detail = await get_member_detail(db, member_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Không tìm thấy thành viên.")
    return detail


@router.post("/members", response_model=MemberDetailOut, status_code=status.HTTP_201_CREATED)
async def create_member(payload: MemberCreateIn, db: AsyncSession = Depends(get_db)):
    """Tạo thành viên mới."""
    now = datetime.now(timezone.utc)
    new_member = Member(
        id=str(uuid4()),
        family_id=payload.family_id,
        full_name=payload.full_name,
        other_name=payload.other_name,
        gender=payload.gender,
        birth_date=payload.birth_date,
        is_alive=payload.is_alive,
        branch=payload.branch,
        occupation=payload.occupation,
        education=payload.education,
        bio=payload.bio,
        generation=payload.generation,
        status="alive" if payload.is_alive else "deceased",
        created_at=now,
        updated_at=now,
    )
    db.add(new_member)
    await db.commit()
    await db.refresh(new_member)

    detail = await get_member_detail(db, new_member.id)
    return detail


@router.put("/members/{member_id}", response_model=MemberDetailOut)
async def update_member(member_id: str, payload: MemberUpdateIn, db: AsyncSession = Depends(get_db)):
    """Cập nhật thông tin thành viên."""
    from sqlalchemy import select

    result = await db.execute(select(Member).where(Member.id == member_id))
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Không tìm thấy thành viên.")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(member, field, value)

    member.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(member)

    detail = await get_member_detail(db, member.id)
    return detail


@router.get("/families", response_model=list[FamilyOut])
async def list_families(db: AsyncSession = Depends(get_db)):
    """Danh sách dòng họ."""
    return await get_families(db)
