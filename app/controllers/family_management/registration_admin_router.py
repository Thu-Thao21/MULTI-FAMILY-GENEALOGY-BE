"""System Admin routes for Business registrations (api_contract.md section 4). Mounted under
/api/v1. System Admin only: anyone else gets 403 (authorization runs before the path, query,
header or body is validated). NOT rate limited: these are authenticated administrator endpoints.

Every response may hold personal data of an applicant, so it is `Cache-Control: no-store`.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.auth_access.use_cases import ClientInfo
from app.controllers.family_management import business_admin_use_cases
from app.controllers.family_management import registration_admin_use_cases as use_cases
from app.core.integrations.email_sender import EmailSender, get_email_sender
from app.core.integrations.firebase import IdentityProvider, get_identity_provider
from app.core.utils.idempotency import (
    IDEMPOTENCY_REPLAYED_HEADER,
    idempotency_key_header,
)
from app.core.utils.openapi_responses import AUTHENTICATED, error_responses
from app.db.postgres import get_db
from app.dependencies.auth import Principal, get_user_access_repo
from app.dependencies.permissions import (
    Action,
    get_family_repo,
    get_idempotency_repo,
    get_provisioning_repo,
    require_action,
)
from app.models.family.idempotency_repository import IdempotencyRepository
from app.models.family.provisioning_repository import ProvisioningRepository
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from app.schemas.business import (
    BusinessApproveAndProvisionResponse,
    BusinessCreateRequest,
    BusinessCreateResponse,
    BusinessRegistrationDetail,
    BusinessRegistrationListQuery,
    BusinessRegistrationSummary,
    RegistrationReviewRequest,
    RegistrationReviewResponse,
)
from app.schemas.common import Page
from app.schemas.errors import ErrorCode

router = APIRouter(tags=["registration-admin"])

NO_STORE = "no-store"


@router.get(
    "/admin/business-registrations",
    response_model=Page[BusinessRegistrationSummary],
    dependencies=[Depends(require_action(Action.REGISTRATION_LIST))],
    responses=error_responses(*AUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.VALIDATION_ERROR),
)
async def list_registrations(
    response: Response,
    query: BusinessRegistrationListQuery = Depends(),
    family: FamilyRepository = Depends(get_family_repo),
) -> Page[BusinessRegistrationSummary]:
    response.headers["Cache-Control"] = NO_STORE
    return await use_cases.list_registrations(family=family, query=query)


@router.get(
    "/admin/business-registrations/{registration_id}",
    response_model=BusinessRegistrationDetail,
    dependencies=[Depends(require_action(Action.REGISTRATION_READ))],
    responses=error_responses(
        *AUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.NOT_FOUND, ErrorCode.VALIDATION_ERROR
    ),
)
async def get_registration(
    registration_id: uuid.UUID,
    response: Response,
    family: FamilyRepository = Depends(get_family_repo),
) -> BusinessRegistrationDetail:
    response.headers["Cache-Control"] = NO_STORE
    return await use_cases.get_registration_detail(family=family, registration_id=registration_id)


@router.post(
    "/admin/business-registrations/{registration_id}/review",
    response_model=RegistrationReviewResponse,
    responses=error_responses(
        *AUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.STATE_CONFLICT,
        ErrorCode.VALIDATION_ERROR,
    ),
)
async def review_registration(
    registration_id: uuid.UUID,
    body: RegistrationReviewRequest,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_action(Action.REGISTRATION_REVIEW)),
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
    family: FamilyRepository = Depends(get_family_repo),
) -> RegistrationReviewResponse:
    """Approve or reject a PENDING registration.

    A rejection reason is shown to the applicant (tracking, public_reason); an approval note is
    internal. The response says which one it was (reason_visible_to_applicant).
    """
    response.headers["Cache-Control"] = NO_STORE
    return await use_cases.review_registration(
        db=db,
        users=users,
        family=family,
        principal=principal,
        registration_id=registration_id,
        body=body,
        client=ClientInfo.from_request(request),
    )


@router.post(
    "/admin/business-registrations/{registration_id}/business",
    status_code=201,
    response_model=BusinessCreateResponse,
    responses=error_responses(
        *AUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.STATE_CONFLICT,
        ErrorCode.DUPLICATE_RESOURCE,
        ErrorCode.IDEMPOTENCY_KEY_CONFLICT,
        ErrorCode.VALIDATION_ERROR,
    ),
)
async def create_business(
    registration_id: uuid.UUID,
    request: Request,
    body: Optional[BusinessCreateRequest] = None,
    principal: Principal = Depends(require_action(Action.BUSINESS_CREATE)),
    key: str = Depends(idempotency_key_header),
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
    family: FamilyRepository = Depends(get_family_repo),
    idempotency: IdempotencyRepository = Depends(get_idempotency_repo),
) -> JSONResponse:
    """Create the PENDING Business (clan, profile, subscription) of an APPROVED registration.

    The Idempotency-Key header is required. The same key with the same request replays the first
    201 (header Idempotency-Replayed: true); the same key with a different request is 409
    IDEMPOTENCY_KEY_CONFLICT. The plan comes from the registration, never from the request.
    """
    result = await business_admin_use_cases.create_business(
        db=db,
        users=users,
        family=family,
        idempotency=idempotency,
        principal=principal,
        registration_id=registration_id,
        body=body or BusinessCreateRequest(),
        key=key,
        client=ClientInfo.from_request(request),
    )
    headers = {"Cache-Control": NO_STORE}
    if result.replayed:
        headers[IDEMPOTENCY_REPLAYED_HEADER] = "true"
    return JSONResponse(status_code=result.status, content=result.body, headers=headers)


@router.post(
    "/admin/business-registrations/{registration_id}/approve-and-provision",
    response_model=BusinessApproveAndProvisionResponse,
    responses=error_responses(
        *AUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.STATE_CONFLICT,
        ErrorCode.VALIDATION_ERROR,
    ),
)
async def approve_and_provision(
    registration_id: uuid.UUID,
    request: Request,
    response: Response,
    body: Optional[BusinessCreateRequest] = None,
    principal: Principal = Depends(require_action(Action.REGISTRATION_REVIEW)),
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
    family: FamilyRepository = Depends(get_family_repo),
    jobs: ProvisioningRepository = Depends(get_provisioning_repo),
    idempotency: IdempotencyRepository = Depends(get_idempotency_repo),
    provider: IdentityProvider = Depends(get_identity_provider),
    sender: EmailSender = Depends(get_email_sender),
) -> BusinessApproveAndProvisionResponse:
    """Approve a PENDING registration, create Clan, provision Owner, send credentials email,
    and activate clan in one streamlined call.
    """
    response.headers["Cache-Control"] = NO_STORE
    return await use_cases.approve_and_provision_registration(
        db=db,
        users=users,
        family=family,
        jobs=jobs,
        idempotency=idempotency,
        provider=provider,
        sender=sender,
        principal=principal,
        registration_id=registration_id,
        client=ClientInfo.from_request(request),
        clan_code=body.clan_code if body else None,
    )


# ----- Admin Service Plans (Packages) Management -----

from decimal import Decimal
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from app.models.family.entities import SubscriptionPlan, PlanFeatureLimit


class PlanAdminCreateRequest(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    price: float = 0.0
    billing_period_months: int = 12
    max_members: Optional[int] = 500
    max_family_admins: Optional[int] = 5
    storage_mb: Optional[int] = 20480
    features: list[str] = Field(default_factory=list)
    status: str = "ACTIVE"


class PlanAdminUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    billing_period_months: Optional[int] = None
    max_members: Optional[int] = None
    max_family_admins: Optional[int] = None
    storage_mb: Optional[int] = None
    features: Optional[list[str]] = None
    status: Optional[str] = None


class PlanStatusUpdateRequest(BaseModel):
    status: str


@router.get(
    "/admin/service-plans",
    dependencies=[Depends(require_action(Action.REGISTRATION_LIST))],
)
async def list_admin_service_plans(
    db: AsyncSession = Depends(get_db),
):
    stmt = select(SubscriptionPlan).order_by(SubscriptionPlan.price.asc(), SubscriptionPlan.created_at.desc())
    res = await db.execute(stmt)
    plans = res.scalars().all()

    plan_ids = [p.plan_id for p in plans]
    feat_map: dict[uuid.UUID, list[str]] = {}
    if plan_ids:
        feat_res = await db.execute(select(PlanFeatureLimit).where(PlanFeatureLimit.plan_id.in_(plan_ids)))
        for f in feat_res.scalars().all():
            if f.enabled:
                feat_map.setdefault(f.plan_id, []).append(f.feature_code)

    items = []
    for p in plans:
        items.append({
            "id": str(p.plan_id),
            "plan_id": str(p.plan_id),
            "code": p.code,
            "name": p.name,
            "description": p.description,
            "price": float(p.price),
            "monthly_price": float(p.price) / (p.billing_period_months or 12),
            "billing_period_months": p.billing_period_months,
            "duration_months": p.billing_period_months,
            "member_limit": p.max_members,
            "storage_gb": int((p.storage_mb or 1024) / 1024),
            "status": p.status.lower(),
            "features": feat_map.get(p.plan_id, []),
            "updated_at": p.updated_at.isoformat() if p.updated_at else p.created_at.isoformat(),
        })
    return {"items": items, "total": len(items)}


@router.post(
    "/admin/service-plans",
    status_code=201,
    dependencies=[Depends(require_action(Action.REGISTRATION_REVIEW))],
)
async def create_admin_service_plan(
    body: PlanAdminCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.code == body.code))
    if existing.scalar_one_or_none():
        raise AppError(ErrorCode.DUPLICATE_RESOURCE, f"Mã gói '{body.code}' đã tồn tại.")

    plan = SubscriptionPlan(
        code=body.code.strip().upper(),
        name=body.name.strip(),
        description=body.description,
        price=Decimal(str(body.price)),
        billing_period_months=body.billing_period_months,
        max_members=body.max_members,
        max_family_admins=body.max_family_admins,
        storage_mb=body.storage_mb,
        status=body.status.upper(),
    )
    db.add(plan)
    await db.flush()

    for feat in body.features:
        if feat.strip():
            db.add(PlanFeatureLimit(
                plan_id=plan.plan_id,
                feature_code=feat.strip().upper(),
                enabled=True,
            ))
    await db.commit()
    await db.refresh(plan)

    return {
        "id": str(plan.plan_id),
        "plan_id": str(plan.plan_id),
        "code": plan.code,
        "name": plan.name,
        "status": plan.status.lower(),
        "message": "Tạo gói dịch vụ thành công."
    }


@router.put(
    "/admin/service-plans/{plan_id}",
    dependencies=[Depends(require_action(Action.REGISTRATION_REVIEW))],
)
async def update_admin_service_plan(
    plan_id: uuid.UUID,
    body: PlanAdminUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    plan_res = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.plan_id == plan_id))
    plan = plan_res.scalar_one_or_none()
    if not plan:
        raise AppError(ErrorCode.NOT_FOUND, "Không tìm thấy gói dịch vụ.")

    if body.name is not None:
        plan.name = body.name.strip()
    if body.description is not None:
        plan.description = body.description
    if body.price is not None:
        plan.price = Decimal(str(body.price))
    if body.billing_period_months is not None:
        plan.billing_period_months = body.billing_period_months
    if body.max_members is not None:
        plan.max_members = body.max_members
    if body.max_family_admins is not None:
        plan.max_family_admins = body.max_family_admins
    if body.storage_mb is not None:
        plan.storage_mb = body.storage_mb
    if body.status is not None:
        plan.status = body.status.upper()

    if body.features is not None:
        await db.execute(delete(PlanFeatureLimit).where(PlanFeatureLimit.plan_id == plan_id))
        for feat in body.features:
            if feat.strip():
                db.add(PlanFeatureLimit(
                    plan_id=plan.plan_id,
                    feature_code=feat.strip().upper(),
                    enabled=True,
                ))

    await db.commit()
    return {"id": str(plan.plan_id), "status": plan.status.lower(), "message": "Cập nhật gói thành công."}


@router.patch(
    "/admin/service-plans/{plan_id}/status",
    dependencies=[Depends(require_action(Action.REGISTRATION_REVIEW))],
)
async def toggle_admin_service_plan_status(
    plan_id: uuid.UUID,
    body: PlanStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    plan_res = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.plan_id == plan_id))
    plan = plan_res.scalar_one_or_none()
    if not plan:
        raise AppError(ErrorCode.NOT_FOUND, "Không tìm thấy gói dịch vụ.")

    plan.status = body.status.upper()
    await db.commit()
    return {"id": str(plan.plan_id), "status": plan.status.lower(), "message": "Đã đổi trạng thái gói."}


@router.delete(
    "/admin/service-plans/{plan_id}",
    dependencies=[Depends(require_action(Action.REGISTRATION_REVIEW))],
)
async def delete_admin_service_plan(
    plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    plan_res = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.plan_id == plan_id))
    plan = plan_res.scalar_one_or_none()
    if not plan:
        raise AppError(ErrorCode.NOT_FOUND, "Không tìm thấy gói dịch vụ.")

    plan.status = "RETIRED"
    await db.commit()
    return {"id": str(plan.plan_id), "status": "retired", "message": "Đã hủy kích hoạt gói dịch vụ."}

