from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.schemas.network_schemas import (
    FamilyLinkRequestCreateIn,
    FamilyLinkRequestOut,
    FamilyNetworkOut,
    InLawMarriageOut,
)
from app.services.network_service import (
    create_link_request,
    get_inlaw_marriages,
    get_link_requests,
    get_network_families,
)

router = APIRouter(prefix="/networks", tags=["networks"])


@router.get("/families", response_model=list[FamilyNetworkOut])
async def list_network_families(
    category: Optional[str] = Query("noi", description="Category: noi, ngoai, thong-gia, all"),
    db: AsyncSession = Depends(get_db),
):
    """Danh sách các dòng họ trong mạng lưới theo phân loại."""
    return await get_network_families(db, category=category or "all")


@router.get("/inlaw-marriages", response_model=list[InLawMarriageOut])
async def list_inlaw_marriages(db: AsyncSession = Depends(get_db)):
    """Danh sách Dâu & Rể liên họ kết nối hôn nhân giữa các gia tộc."""
    return await get_inlaw_marriages(db)


@router.get("/link-requests", response_model=list[FamilyLinkRequestOut])
async def list_link_requests(db: AsyncSession = Depends(get_db)):
    """Danh sách yêu cầu liên kết gia phả giữa các dòng họ."""
    return await get_link_requests(db)


@router.post("/link-requests", response_model=FamilyLinkRequestOut, status_code=status.HTTP_201_CREATED)
async def request_family_link(
    payload: FamilyLinkRequestCreateIn,
    db: AsyncSession = Depends(get_db),
):
    """Gửi yêu cầu liên kết gia phả mới."""
    return await create_link_request(
        db,
        source_family_id="family_001",
        target_family_id=payload.target_family_id,
        request_type=payload.request_type,
        message=payload.message,
    )
