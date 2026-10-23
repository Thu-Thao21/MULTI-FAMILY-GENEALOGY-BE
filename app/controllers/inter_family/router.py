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


class LinkResponse(BaseModel):
    id: str
    request_id: str = Field(alias="requestId")
    clan_a_id: str = Field(alias="clanAId")
    clan_a_name: str = Field(alias="clanAName")
    clan_b_id: str = Field(alias="clanBId")
    clan_b_name: str = Field(alias="clanBName")
    status: str
    linked_at: datetime = Field(alias="linkedAt")
    ended_at: Optional[datetime] = Field(None, alias="endedAt")


class PolicyUpdate(BaseModel):
    data_scope: Optional[str] = Field(None, alias="dataScope")
    allowed_fields: Optional[dict] = Field(None, alias="allowedFields")
    can_export: Optional[bool] = Field(None, alias="canExport")


class PolicyResponse(BaseModel):
    id: str
    link_id: str = Field(alias="linkId")
    owner_clan_id: str = Field(alias="ownerClanId")
    data_scope: str = Field(alias="dataScope")
    allowed_fields: dict = Field(alias="allowedFields")
    visibility: str
    can_export: bool = Field(alias="canExport")
    updated_at: datetime = Field(alias="updatedAt")


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


@router.get("/links", response_model=List[LinkResponse])
async def list_inter_clan_links(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    """Lists established inter-clan links (FR-BO-53..55)."""
    stmt = select(InterClanLink).order_by(InterClanLink.linked_at.desc())
    if status_filter:
        stmt = stmt.where(InterClanLink.status == status_filter.upper())
    res = await db.execute(stmt)
    links = list(res.scalars().all())

    clans_res = await db.execute(select(Clan))
    clan_map = {str(c.clan_id): c.name for c in clans_res.scalars().all()}

    output = []
    for link in links:
        a_id = str(link.clan_a_id)
        b_id = str(link.clan_b_id)
        output.append(
            LinkResponse(
                id=str(link.id),
                requestId=str(link.request_id),
                clanAId=a_id,
                clanAName=clan_map.get(a_id, "Dòng họ A"),
                clanBId=b_id,
                clanBName=clan_map.get(b_id, "Dòng họ B"),
                status=link.status,
                linkedAt=link.linked_at,
                endedAt=link.ended_at,
            )
        )
    return output


@router.delete("/links/{link_id}")
@router.post("/links/{link_id}/terminate")
async def terminate_link(
    link_id: str,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    """Terminates an inter-family connection link (FR-BO-55)."""
    link_uuid = uuid.UUID(link_id)
    res = await db.execute(select(InterClanLink).where(InterClanLink.id == link_uuid))
    link = res.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    if link.status == "TERMINATED":
        return {"status": "TERMINATED", "message": "Link already terminated"}

    link.status = "TERMINATED"
    link.ended_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "TERMINATED", "link_id": str(link.id)}


@router.get("/diagram")
async def get_network_diagram(
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    """Returns network graph nodes and edges for visualizing inter-clan relationships."""
    clans_res = await db.execute(select(Clan).where(Clan.status == "ACTIVE"))
    clans = list(clans_res.scalars().all())

    links_res = await db.execute(select(InterClanLink).where(InterClanLink.status == "ACTIVE"))
    links = list(links_res.scalars().all())

    nodes = [
        {
            "id": str(c.clan_id),
            "name": c.name,
            "code": c.clan_code,
            "status": c.status,
        }
        for c in clans
    ]

    edges = [
        {
            "id": str(l.id),
            "source": str(l.clan_a_id),
            "target": str(l.clan_b_id),
            "status": l.status,
            "linkedAt": l.linked_at.isoformat() if l.linked_at else None,
        }
        for l in links
    ]

    return {"nodes": nodes, "edges": edges}


@router.get("/links/{link_id}/policies", response_model=List[PolicyResponse])
async def get_sharing_policies(
    link_id: str,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    """Gets shared data policies configured for an inter-clan link (FR-BO-57, FR-BO-77)."""
    link_uuid = uuid.UUID(link_id)
    stmt = select(InterClanSharedPolicy).where(InterClanSharedPolicy.link_id == link_uuid)
    res = await db.execute(stmt)
    policies = list(res.scalars().all())

    return [
        PolicyResponse(
            id=str(p.id),
            linkId=str(p.link_id),
            ownerClanId=str(p.owner_clan_id),
            dataScope=p.data_scope,
            allowedFields=p.allowed_fields or {},
            visibility=p.visibility,
            canExport=p.can_export,
            updatedAt=p.updated_at,
        )
        for p in policies
    ]


@router.put("/links/{link_id}/policies")
async def update_sharing_policy(
    link_id: str,
    data: PolicyUpdate,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    """Updates shared data policy for a link (FR-BO-57, FR-BO-77)."""
    link_uuid = uuid.UUID(link_id)
    stmt = select(InterClanSharedPolicy).where(InterClanSharedPolicy.link_id == link_uuid)
    res = await db.execute(stmt)
    policy = res.scalars().first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found for this link")

    if data.data_scope is not None:
        policy.data_scope = data.data_scope
    if data.allowed_fields is not None:
        policy.allowed_fields = data.allowed_fields
    if data.can_export is not None:
        policy.can_export = data.can_export

    policy.updated_by = account.id
    policy.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "status": "SUCCESS",
        "policy_id": str(policy.id),
        "data_scope": policy.data_scope,
        "allowed_fields": policy.allowed_fields,
        "can_export": policy.can_export,
    }


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

    try:
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

            # Create default InterClanSharedPolicy for both clans atomically
            policy_a = InterClanSharedPolicy(
                id=uuid.uuid4(),
                link_id=link.id,
                owner_clan_id=req.source_clan_id,
                data_scope="BASIC",
                allowed_fields={"full_name": True, "generation": True, "gender": True, "avatar_url": True},
                visibility="INTER_FAMILY",
                can_export=False,
                updated_by=account.id,
            )
            policy_b = InterClanSharedPolicy(
                id=uuid.uuid4(),
                link_id=link.id,
                owner_clan_id=req.target_clan_id,
                data_scope="BASIC",
                allowed_fields={"full_name": True, "generation": True, "gender": True, "avatar_url": True},
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

        else:
            raise HTTPException(status_code=400, detail="Invalid review action. Must be APPROVE or REJECT.")
    except Exception:
        await db.rollback()
        raise


@router.get("/shared-tree/{target_family_id}", response_model=TreeDataResponse)
@router.get("/families/{target_family_id}/shared-tree", response_model=TreeDataResponse)
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

    # Fetch sharing policy of target family
    policy_stmt = select(InterClanSharedPolicy).where(
        InterClanSharedPolicy.link_id == link.id,
        InterClanSharedPolicy.owner_clan_id == target_uuid,
    )
    p_res = await db.execute(policy_stmt)
    policy = p_res.scalars().first()
    allowed_fields = policy.allowed_fields if policy and policy.allowed_fields else {
        "full_name": True,
        "generation": True,
        "gender": True,
        "avatar_url": True,
    }

    # Fetch persons and relationships of target clan
    persons_res = await db.execute(select(Person).where(Person.family_id == target_uuid))
    persons = list(persons_res.scalars().all())

    rels_res = await db.execute(select(Relationship).where(Relationship.family_id == target_uuid))
    relationships = list(rels_res.scalars().all())

    # Build tree nodes with privacy scoping
    nodes = [
        TreeNode(
            id=str(p.id),
            fullName=p.full_name,
            gender=p.gender or "unknown",
            generation=p.generation or 1,
            branchId=str(p.branch_id) if p.branch_id else None,
            avatarUrl=p.avatar_url if allowed_fields.get("avatar_url", True) else None,
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
