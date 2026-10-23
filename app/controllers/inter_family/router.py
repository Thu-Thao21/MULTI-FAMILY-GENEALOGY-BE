"""Inter-Family Networking & Data Sharing Router (FR-BO-53..57, FR-BO-77)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.dependencies.auth import get_current_account
from app.models.family.entities import Clan
from app.models.genealogy.entities import Person, Relationship
from app.models.inter_family import (
    InterClanLink,
    InterClanRequest,
    InterClanSharedPolicy,
)
from app.models.postgres import Account
from app.schemas.genealogy import RelationshipResponse, TreeDataResponse, TreeNode

router = APIRouter(prefix="/networks", tags=["inter-family"])


class LinkRequestCreate(BaseModel):
    target_family_id: str = Field(alias="targetFamilyId")
    source_person_id: Optional[str] = Field(None, alias="sourcePersonId")
    target_person_id: Optional[str] = Field(None, alias="targetPersonId")
    message: Optional[str] = None


class LinkRequestReview(BaseModel):
    action: str = Field(description="'APPROVE' or 'REJECT'")
    reason: Optional[str] = None


class LinkRequestResponse(BaseModel):
    id: str
    source_family_id: str = Field(alias="sourceFamilyId")
    source_family_name: str = Field(alias="sourceFamilyName")
    target_family_id: str = Field(alias="targetFamilyId")
    target_family_name: str = Field(alias="targetFamilyName")
    status: str
    message: Optional[str] = None
    created_at: datetime = Field(alias="createdAt")


@router.get("/families")
async def get_network_families(
    category: str = Query("all"),
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    """Returns linked families or discovered clans for the network tab."""
    # Find all active links
    stmt = select(InterClanLink).where(InterClanLink.status == "ACTIVE")
    res = await db.execute(stmt)
    links = list(res.scalars().all())

    # Fetch clans to build network responses
    clans_res = await db.execute(select(Clan).where(Clan.status == "ACTIVE"))
    clans = {str(c.clan_id): c for c in clans_res.scalars().all()}

    items = []
    for c_id, clan in clans.items():
        items.append({
            "id": c_id,
            "name": clan.name,
            "code": clan.clan_code,
            "category": "thong_gia",
            "relationshipCount": 1,
            "branches": ["Nhánh chính"],
            "status": "connected" if any(str(l.clan_a_id) == c_id or str(l.clan_b_id) == c_id for l in links) else "available",
        })

    return items


@router.get("/link-requests", response_model=List[LinkRequestResponse])
async def list_link_requests(
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    """Lists inter-family connection requests."""
    stmt = (
        select(InterClanRequest)
        .order_by(InterClanRequest.created_at.desc())
        .limit(100)
    )
    res = await db.execute(stmt)
    requests = list(res.scalars().all())

    clans_res = await db.execute(select(Clan))
    clan_map = {str(c.clan_id): c.name for c in clans_res.scalars().all()}

    output = []
    for req in requests:
        s_id = str(req.source_clan_id)
        t_id = str(req.target_clan_id)
        output.append(
            LinkRequestResponse(
                id=str(req.id),
                sourceFamilyId=s_id,
                sourceFamilyName=clan_map.get(s_id, "Dòng họ nguồn"),
                targetFamilyId=t_id,
                targetFamilyName=clan_map.get(t_id, "Dòng họ đích"),
                status=req.status,
                message=req.message,
                createdAt=req.created_at,
            )
        )
    return output


@router.post("/link-requests", status_code=status.HTTP_201_CREATED, response_model=LinkRequestResponse)
async def create_link_request(
    data: LinkRequestCreate,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    """Sends an inter-clan connection request (FR-BO-53)."""
    # Find user's clan from memberships or clans
    # Fallback to source family if specified or first active clan
    clans_res = await db.execute(select(Clan).where(Clan.status == "ACTIVE").limit(2))
    all_clans = list(clans_res.scalars().all())
    if not all_clans:
        raise HTTPException(status_code=400, detail="No active clans found in system")

    target_clan_id = uuid.UUID(data.target_family_id)
    # Source clan is the first clan not equal to target
    source_clan = next((c for c in all_clans if c.clan_id != target_clan_id), all_clans[0])

    req = InterClanRequest(
        id=uuid.uuid4(),
        source_clan_id=source_clan.clan_id,
        target_clan_id=target_clan_id,
        requester_id=account.id,
        source_person_id=uuid.UUID(data.source_person_id) if data.source_person_id else None,
        target_person_id=uuid.UUID(data.target_person_id) if data.target_person_id else None,
        message=data.message,
        status="PENDING",
    )
    db.add(req)
    await db.commit()

    return LinkRequestResponse(
        id=str(req.id),
        sourceFamilyId=str(req.source_clan_id),
        sourceFamilyName=source_clan.name,
        targetFamilyId=str(req.target_clan_id),
        targetFamilyName="Dòng họ đối tác",
        status=req.status,
        message=req.message,
        createdAt=req.created_at,
    )


@router.post("/link-requests/{request_id}/review")
async def review_link_request(
    request_id: str,
    data: LinkRequestReview,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    """Approves or rejects an inter-family request (FR-BO-54)."""
    req_uuid = uuid.UUID(request_id)
    res = await db.execute(select(InterClanRequest).where(InterClanRequest.id == req_uuid))
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    if req.status != "PENDING":
        raise HTTPException(status_code=400, detail=f"Request already processed ({req.status})")

    now = datetime.now(timezone.utc)
    action = data.action.upper()
    if action == "APPROVE":
        req.status = "APPROVED"
        req.reviewed_by = account.id
        req.reviewed_at = now

        # Create active InterClanLink
        link = InterClanLink(
            id=uuid.uuid4(),
            request_id=req.id,
            clan_a_id=req.source_clan_id,
            clan_b_id=req.target_clan_id,
            status="ACTIVE",
            linked_at=now,
        )
        db.add(link)
        await db.flush()

        # Create default InterClanSharedPolicy
        policy_a = InterClanSharedPolicy(
            id=uuid.uuid4(),
            link_id=link.id,
            owner_clan_id=req.source_clan_id,
            data_scope="BASIC",
            allowed_fields={"full_name": True, "generation": True, "gender": True},
            visibility="INTER_FAMILY",
            can_export=False,
            updated_by=account.id,
        )
        policy_b = InterClanSharedPolicy(
            id=uuid.uuid4(),
            link_id=link.id,
            owner_clan_id=req.target_clan_id,
            data_scope="BASIC",
            allowed_fields={"full_name": True, "generation": True, "gender": True},
            visibility="INTER_FAMILY",
            can_export=False,
            updated_by=account.id,
        )
        db.add(policy_a)
        db.add(policy_b)

        await db.commit()
        return {"status": "APPROVED", "link_id": str(link.id)}

    elif action == "REJECT":
        req.status = "REJECTED"
        req.reviewed_by = account.id
        req.reviewed_at = now
        await db.commit()
        return {"status": "REJECTED"}

    raise HTTPException(status_code=400, detail="Invalid review action. Must be APPROVE or REJECT.")


@router.get("/shared-tree/{target_family_id}", response_model=TreeDataResponse)
async def get_shared_tree(
    target_family_id: str,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    """Accesses shared tree data of a linked family under INTER_FAMILY privacy policy (FR-BO-56, FR-BO-77)."""
    target_uuid = uuid.UUID(target_family_id)

    # Check if there is an active link involving this clan
    stmt = select(InterClanLink).where(
        InterClanLink.status == "ACTIVE",
        or_(
            InterClanLink.clan_a_id == target_uuid,
            InterClanLink.clan_b_id == target_uuid,
        ),
    )
    res = await db.execute(stmt)
    link = res.scalars().first()
    if not link:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active inter-clan link with this family",
        )

    # Fetch persons and relationships of target clan
    persons_res = await db.execute(select(Person).where(Person.family_id == target_uuid))
    persons = list(persons_res.scalars().all())

    rels_res = await db.execute(select(Relationship).where(Relationship.family_id == target_uuid))
    relationships = list(rels_res.scalars().all())

    # Build tree nodes with privacy scoping (no private bio, contact, phone, or internal notes)
    nodes = [
        TreeNode(
            id=str(p.id),
            fullName=p.full_name,
            gender=p.gender or "unknown",
            generation=p.generation or 1,
            branchId=str(p.branch_id) if p.branch_id else None,
            avatarUrl=p.avatar_url,
            isLiving=True if p.is_alive is None else p.is_alive,
            status=p.status,
        )
        for p in persons
    ]

    edges = [
        RelationshipResponse(
            id=str(r.id),
            fromMemberId=str(r.from_member_id),
            toMemberId=str(r.to_member_id),
            relationshipType=r.relationship_type,
            notes=None,
        )
        for r in relationships
    ]

    return TreeDataResponse(nodes=nodes, edges=edges)
