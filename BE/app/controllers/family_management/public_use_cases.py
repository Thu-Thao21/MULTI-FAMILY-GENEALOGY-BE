"""Public (Guest) use cases of Business registration (Mốc E, step E3): service plans, a new
registration and tracking by the tracking code. No authentication. Each use case owns its
transaction; the repositories only flush.

Security rules kept here:
  * the tracking code is generated here, shown once in the 201 response and never logged,
    audited or stored; only its SHA-256 is stored;
  * a registration writes its status history and one audit row, in the same transaction;
  * the audit row of a Guest has actor_id NULL and holds ids only: no e-mail, name, phone,
    clan name or tracking code (docs/security_review.md 3.5);
  * an unknown plan and an inactive plan give the same 422, so a Guest cannot probe plan ids;
  * every wrong tracking code gives the same 404;
  * the last line of defence against two identical pending registrations is the unique index
    uq_registration_pending_same_applicant: its IntegrityError becomes the same 409 as the
    check that runs first.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.controllers.auth_access.use_cases import ClientInfo, UnitOfWork
from app.core.errors import AppError
from app.core.request_id import get_request_id
from app.core.tokens import generate_tracking_code, hash_tracking_code
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from app.schemas.business import (
    BusinessRegistrationCreateRequest,
    BusinessRegistrationCreateResponse,
    BusinessRegistrationTrackRequest,
    BusinessRegistrationTrackResponse,
    PlanFeaturePublic,
    ServicePlanResponse,
)
from app.schemas.common import Page, PageParams
from app.schemas.errors import DEFAULT_ERROR_MESSAGE, ErrorCode

logger = logging.getLogger("mfg.registration")

PENDING_SAME_APPLICANT = "uq_registration_pending_same_applicant"
TRACKING_HASH_KEY = "business_registrations_tracking_code_hash_key"
PLAN_FKEY = "business_registrations_requested_plan_id_fkey"
MAX_TRACKING_CODE_ATTEMPTS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def constraint_name(exc: IntegrityError) -> str | None:
    """The unique index, constraint or foreign key the database reports (psycopg diagnostics)."""
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _invalid_plan() -> AppError:
    message = DEFAULT_ERROR_MESSAGE[ErrorCode.VALIDATION_ERROR]
    return AppError(ErrorCode.VALIDATION_ERROR, f"{message} Fields: body.requested_plan_id")


def _duplicate() -> AppError:
    return AppError(
        ErrorCode.DUPLICATE_RESOURCE, "A registration for this applicant is already pending."
    )


# ----- GET /service-plans -----


async def list_service_plans(
    *, family: FamilyRepository, query: PageParams
) -> Page[ServicePlanResponse]:
    plans = await family.list_active_plans_page(limit=query.page_size, offset=query.offset)
    total = await family.count_active_plans()
    features = await family.list_feature_limits_for_plans([p.plan_id for p in plans])
    by_plan: dict[uuid.UUID, list[PlanFeaturePublic]] = {}
    for feature in features:
        by_plan.setdefault(feature.plan_id, []).append(
            PlanFeaturePublic(
                feature_code=feature.feature_code,
                enabled=feature.enabled,
                limit_value=feature.limit_value,
            )
        )
    items = [
        ServicePlanResponse(
            plan_id=plan.plan_id,
            code=plan.code,
            name=plan.name,
            description=plan.description,
            price=plan.price,
            billing_period_months=plan.billing_period_months,
            max_members=plan.max_members,
            max_family_admins=plan.max_family_admins,
            storage_mb=plan.storage_mb,
            features=by_plan.get(plan.plan_id, []),
        )
        for plan in plans
    ]
    return Page[ServicePlanResponse](
        items=items, total=total, page=query.page, page_size=query.page_size
    )


# ----- POST /business-registrations -----


async def create_registration(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    family: FamilyRepository,
    body: BusinessRegistrationCreateRequest,
    client: ClientInfo,
    now: datetime | None = None,
) -> BusinessRegistrationCreateResponse:
    plan_id = body.requested_plan_id
    plan = await family.get_plan_by_id(plan_id)
    if plan is None or plan.status != "ACTIVE":
        raise _invalid_plan()  # same answer for "unknown" and "not selectable"

    if await family.exists_pending_registration(
        email=body.representative_email, clan_name=body.clan_name
    ):
        raise _duplicate()

    created_at = now or _now()
    for _attempt in range(MAX_TRACKING_CODE_ATTEMPTS):
        tracking_code = generate_tracking_code()
        registration_id = uuid.uuid4()
        try:
            await family.create_registration(
                registration_id=registration_id,
                requested_plan_id=plan_id,
                representative_name=body.representative_name,
                representative_email=body.representative_email,
                representative_phone=body.representative_phone,
                clan_name=body.clan_name,
                origin_place=body.origin_place,
                tracking_code_hash=hash_tracking_code(tracking_code),
                now=created_at,
            )
            await family.add_registration_status_history(
                registration_id=registration_id,
                from_status=None,
                to_status="PENDING",
                changed_by=None,
                reason=None,
                now=created_at,
            )
            await users.add_audit_log(
                actor_id=None,  # a Guest has no account
                action="registration.create",
                entity_type="business_registration",
                entity_id=registration_id,
                old_data=None,
                new_data={
                    "plan_id": str(plan_id),
                    "status": "PENDING",
                    "request_id": get_request_id(),
                },
                ip_address=client.ip_address,
                occurred_at=created_at,
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            name = constraint_name(exc)
            if name == PENDING_SAME_APPLICANT:
                raise _duplicate() from None  # lost a race the check could not see
            if name == PLAN_FKEY:
                raise _invalid_plan() from None  # the plan vanished meanwhile
            if name == TRACKING_HASH_KEY:
                continue  # a collision of 256-bit codes: draw a new one
            raise  # anything else is a bug, not input: it becomes a 500
        logger.info("registration.create request_id=%s", get_request_id())
        return BusinessRegistrationCreateResponse(
            registration_id=registration_id,
            tracking_code=tracking_code,
            status="PENDING",
            created_at=created_at,
        )
    raise RuntimeError("could not draw an unused tracking code")


# ----- POST /business-registrations/track -----


async def track_registration(
    *, family: FamilyRepository, body: BusinessRegistrationTrackRequest
) -> BusinessRegistrationTrackResponse:
    registration = await family.get_registration_by_tracking_hash(
        hash_tracking_code(body.tracking_code.get_secret_value())
    )
    if registration is None:
        raise AppError(ErrorCode.NOT_FOUND)  # every wrong code gives this one answer
    return BusinessRegistrationTrackResponse(
        clan_name=registration.clan_name,
        status=registration.status,
        # Only a rejection reason is published; nothing else leaves the system.
        public_reason=registration.rejection_reason if registration.status == "REJECTED" else None,
        submitted_at=registration.created_at,
        updated_at=registration.updated_at,
    )
