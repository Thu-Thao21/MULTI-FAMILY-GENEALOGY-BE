from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.dependencies.auth import get_current_account, require_roles
from app.models.postgres import Account, AccountRole, AuditLog, RoleRequest
from app.schemas.auth_schemas import RoleRequestCreate, RoleRequestOut, RoleRequestReview

router = APIRouter(prefix="/auth/role-requests", tags=["role-requests"])


@router.post("", response_model=RoleRequestOut, status_code=status.HTTP_201_CREATED)
async def create_role_request(
    payload: RoleRequestCreate,
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticated member submits a request to become a 'family_head'.
    Cannot request 'admin' role directly.
    Blocks duplicate pending requests.
    """
    if payload.requested_role.lower() == "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không thể gửi yêu cầu quyền Admin công khai.",
        )

    if payload.requested_role.lower() != "family_head":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chỉ hỗ trợ gửi yêu cầu cho vai trò 'family_head'.",
        )

    # Check pending request
    stmt = select(RoleRequest).where(
        RoleRequest.account_id == account.id,
        RoleRequest.requested_role == "family_head",
        RoleRequest.status == "pending",
    )
    res = await db.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bạn đang có 1 yêu cầu làm Trưởng Họ đang chờ duyệt.",
        )

    now = datetime.now(timezone.utc)
    req_obj = RoleRequest(
        account_id=account.id,
        requested_role="family_head",
        family_id=payload.family_id,
        reason=payload.reason,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    db.add(req_obj)
    await db.commit()
    await db.refresh(req_obj)

    return req_obj


@router.get("/admin", response_model=List[RoleRequestOut])
async def list_role_requests(
    status_filter: Optional[str] = None,
    admin_account: Account = Depends(require_roles(["admin"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin lists role requests (filtered by pending/approved/rejected).
    """
    stmt = select(RoleRequest)
    if status_filter:
        stmt = stmt.where(RoleRequest.status == status_filter)
    stmt = stmt.order_by(RoleRequest.created_at.desc())

    res = await db.execute(stmt)
    return res.scalars().all()


@router.patch("/admin/{request_id}", response_model=RoleRequestOut)
async def review_role_request(
    request_id: str,
    payload: RoleRequestReview,
    admin_account: Account = Depends(require_roles(["admin"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin approves or rejects a role request.
    Upon approval, grants 'family_head' role in PostgreSQL inside a DB transaction and writes audit log.
    """
    if payload.status not in ["approved", "rejected"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Trạng thái phê duyệt phải là 'approved' hoặc 'rejected'.",
        )

    stmt = select(RoleRequest).where(RoleRequest.id == request_id)
    res = await db.execute(stmt)
    req_obj = res.scalar_one_or_none()

    if not req_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy yêu cầu nâng vai trò.",
        )

    if req_obj.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Yêu cầu này đã được xử lý (Trạng thái: {req_obj.status}).",
        )

    now = datetime.now(timezone.utc)
    req_obj.status = payload.status
    req_obj.reviewer_id = admin_account.id
    req_obj.reviewer_notes = payload.reviewer_notes
    req_obj.reviewed_at = now
    req_obj.updated_at = now

    if payload.status == "approved":
        # Check existing role
        role_stmt = select(AccountRole).where(
            AccountRole.account_id == req_obj.account_id,
            AccountRole.role == req_obj.requested_role,
        )
        role_res = await db.execute(role_stmt)
        existing_role = role_res.scalar_one_or_none()

        if not existing_role:
            new_role = AccountRole(
                account_id=req_obj.account_id,
                role=req_obj.requested_role,
                family_id=req_obj.family_id,
                status="active",
            )
            db.add(new_role)

    # Audit log
    audit = AuditLog(
        actor_id=admin_account.id,
        action=f"role_request_{payload.status}",
        target_table="role_requests",
        target_id=req_obj.id,
        details={
            "account_id": req_obj.account_id,
            "requested_role": req_obj.requested_role,
            "reviewer_notes": payload.reviewer_notes,
        },
    )
    db.add(audit)

    await db.commit()
    await db.refresh(req_obj)
    return req_obj
