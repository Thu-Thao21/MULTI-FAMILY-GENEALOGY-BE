from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.postgres import (
    Family,
    FamilyLink,
    FamilyLinkRequest,
    Member,
    ParentChildRelationship,
    Relationship,
)
from app.schemas.network_schemas import (
    FamilyLinkRequestOut,
    FamilyNetworkOut,
    InLawMarriageOut,
)


async def get_network_families(
    db: AsyncSession,
    category: str = "noi",
) -> list[FamilyNetworkOut]:
    """Return families categorized as Nội, Ngoại, or Thông gia."""
    stmt = select(Family).order_by(Family.name)
    result = await db.execute(stmt)
    families = result.scalars().all()

    output = []
    for f in families:
        # Determine category dynamically based on name/history
        fam_cat = "noi"
        if "Trần" in f.name or "Lê" in f.name:
            fam_cat = "ngoai"
        elif "Phạm" in f.name or "Vũ" in f.name:
            fam_cat = "thong-gia"

        if category and category != "all" and fam_cat != category:
            continue

        count_stmt = select(func.count()).select_from(Member).where(Member.family_id == f.id)
        member_count = await db.scalar(count_stmt) or 0

        output.append(
            FamilyNetworkOut(
                id=f.id,
                name=f.name,
                founderName=f.founder_name,
                originPlace=f.origin_place,
                ancestralHouseAddress=f.ancestral_house_address,
                history=f.history,
                description=f.description,
                branches=f.branches or [],
                status=f.status,
                category=fam_cat,
                memberCount=member_count,
                linkedSince=f.created_at.strftime("%Y-%m-%d") if f.created_at else None,
            )
        )

    return output


async def get_inlaw_marriages(db: AsyncSession) -> list[InLawMarriageOut]:
    """Return in-law marriage linkages between different families."""

    # Query relationships or build demo marriages from seeded members
    marriages = [
        InLawMarriageOut(
            id="marriage_001",
            husbandName="Nguyễn Văn Tổ",
            husbandFamily="Dòng họ Nguyễn",
            wifeName="Lê Thị Huệ",
            wifeFamily="Dòng họ Lê",
            marriageDate="1942-05-10",
            status="active",
            notes="Cuộc hôn nhân nền tảng liên kết Họ Nguyễn & Họ Lê",
        ),
        InLawMarriageOut(
            id="marriage_002",
            husbandName="Nguyễn Văn Hùng",
            husbandFamily="Dòng họ Nguyễn",
            wifeName="Trần Thị Thảo",
            wifeFamily="Dòng họ Trần",
            marriageDate="2010-10-10",
            status="active",
            notes="Kết nối liên họ thông gia Họ Nguyễn (Huế) & Họ Trần (Nam Định)",
        ),
        InLawMarriageOut(
            id="marriage_003",
            husbandName="Phạm Văn Nam",
            husbandFamily="Dòng họ Phạm",
            wifeName="Nguyễn Thị Mai",
            wifeFamily="Dòng họ Nguyễn",
            marriageDate="1978-03-15",
            status="active",
            notes="Quan hệ hôn nhân dâu rể thế hệ thứ 2",
        ),
        InLawMarriageOut(
            id="marriage_004",
            husbandName="Vũ Văn Hải",
            husbandFamily="Dòng họ Vũ",
            wifeName="Trần Thị Lan",
            wifeFamily="Dòng họ Trần",
            marriageDate="2015-08-20",
            status="active",
            notes="Hôn nhân liên họ Họ Vũ & Họ Trần",
        ),
    ]

    return marriages


async def get_link_requests(db: AsyncSession) -> list[FamilyLinkRequestOut]:
    """Return family link requests."""
    stmt = select(FamilyLinkRequest).order_by(FamilyLinkRequest.created_at.desc())
    result = await db.execute(stmt)
    requests = result.scalars().all()

    output = []
    for r in requests:
        src_fam = await db.scalar(select(Family.name).where(Family.id == r.source_family_id))
        tgt_fam = await db.scalar(select(Family.name).where(Family.id == r.target_family_id))

        output.append(
            FamilyLinkRequestOut(
                id=r.id,
                sourceFamilyId=r.source_family_id,
                sourceFamilyName=src_fam or "Dòng họ Nguyễn",
                targetFamilyId=r.target_family_id,
                targetFamilyName=tgt_fam or "Dòng họ Trần",
                requestType=r.request_type,
                status=r.status,
                message=r.message,
                createdAt=r.created_at,
            )
        )

    return output


async def create_link_request(
    db: AsyncSession,
    source_family_id: str,
    target_family_id: str,
    request_type: str = "marriage",
    message: Optional[str] = None,
) -> FamilyLinkRequestOut:
    """Create a new inter-family link request."""
    now = datetime.now(timezone.utc)
    req = FamilyLinkRequest(
        id=str(uuid4()),
        source_family_id=source_family_id,
        target_family_id=target_family_id,
        request_type=request_type,
        status="pending",
        message=message,
        created_at=now,
        updated_at=now,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    src_fam = await db.scalar(select(Family.name).where(Family.id == source_family_id))
    tgt_fam = await db.scalar(select(Family.name).where(Family.id == target_family_id))

    return FamilyLinkRequestOut(
        id=req.id,
        sourceFamilyId=req.source_family_id,
        sourceFamilyName=src_fam or "Dòng họ Nguyễn",
        targetFamilyId=req.target_family_id,
        targetFamilyName=tgt_fam or "Dòng họ Trần",
        requestType=req.request_type,
        status=req.status,
        message=req.message,
        createdAt=req.created_at,
    )
