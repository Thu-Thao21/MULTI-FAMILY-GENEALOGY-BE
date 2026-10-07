"""System Admin use cases for Business registrations (Mốc E, step E4): list, detail, review.

Review (approve or reject) rules:
  * state machine: PENDING to APPROVED or REJECTED; both are final. Anything else is 409 and the
    message names the current status (only a System Admin can get here);
  * the registration row is locked FOR NO KEY UPDATE first, then the status is checked, so two
    reviewers at the same time cannot both succeed: the second waits, re-reads, and gets 409;
  * approving needs a plan that is still ACTIVE (409 otherwise); rejecting does not look at the
    plan. The creation of the Business (E5) checks again;
  * the registration, one status-history row and one audit row are written in ONE transaction;
  * a rejection reason is public: it is stored in registration.rejection_reason, which tracking
    shows as public_reason. An approval note is internal: it goes to the history row only;
  * the audit row holds ids, statuses and the LENGTH of the reason, never its text, and no
    e-mail, name, phone or clan name (docs/security_review.md 3.5). audit_logs.reason stays NULL;
  * only the registration row is locked and the users row never is (the audit and reviewed_by
    foreign keys need KEY SHARE on it, so FOR UPDATE there would deadlock; Mốc F lesson).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.controllers.auth_access.use_cases import ClientInfo, UnitOfWork
from app.core.errors import AppError
from app.core.request_id import get_request_id
from app.dependencies.auth import Principal
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from app.schemas.business import (
    BusinessRegistrationDetail,
    BusinessRegistrationListQuery,
    BusinessRegistrationSummary,
    RegistrationAttachmentItem,
    RegistrationReviewRequest,
    RegistrationReviewResponse,
    RegistrationStatusHistoryItem,
)
from app.schemas.common import Page
from app.schemas.errors import ErrorCode

logger = logging.getLogger("mfg.registration_admin")

PENDING = "PENDING"
DECISION_STATUS = {"APPROVED": "APPROVED", "REJECTED": "REJECTED"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ----- GET /admin/business-registrations -----


async def list_registrations(
    *, family: FamilyRepository, query: BusinessRegistrationListQuery
) -> Page[BusinessRegistrationSummary]:
    if query.created_from and query.created_to and query.created_from > query.created_to:
        # Checked here, not in the query model: a model-level error inside Depends() is not turned
        # into the 422 envelope, and authorization must run before any validation anyway.
        raise AppError(ErrorCode.VALIDATION_ERROR, "created_from must not be after created_to.")
    filters = dict(
        status=query.status, q=query.q, created_from=query.created_from, created_to=query.created_to
    )
    rows = await family.list_registrations_page(limit=query.page_size, offset=query.offset, **filters)
    total = await family.count_registrations(**filters)
    items = [
        BusinessRegistrationSummary(
            registration_id=row.registration_id,
            clan_name=row.clan_name,
            representative_name=row.representative_name,
            requested_plan_id=row.requested_plan_id,
            requested_plan_code=row.requested_plan_code,
            status=row.status,
            created_at=row.created_at,
            reviewed_at=row.reviewed_at,
        )
        for row in rows
    ]
    return Page[BusinessRegistrationSummary](
        items=items, total=total, page=query.page, page_size=query.page_size
    )


# ----- GET /admin/business-registrations/{id} -----


async def get_registration_detail(
    *, family: FamilyRepository, registration_id: uuid.UUID
) -> BusinessRegistrationDetail:
    found = await family.get_registration_with_plan(registration_id)
    if found is None:
        raise AppError(ErrorCode.NOT_FOUND)
    registration, plan_code = found[0], found[1]
    history = await family.list_registration_status_history(registration_id)
    attachments = await family.list_registration_attachments(registration_id)
    clan = await family.get_clan_by_registration_id(registration_id)
    return BusinessRegistrationDetail(
        registration_id=registration.registration_id,
        clan_name=registration.clan_name,
        representative_name=registration.representative_name,
        requested_plan_id=registration.requested_plan_id,
        requested_plan_code=plan_code,
        status=registration.status,
        created_at=registration.created_at,
        reviewed_at=registration.reviewed_at,
        representative_email=registration.representative_email,
        representative_phone=registration.representative_phone,
        origin_place=registration.origin_place,
        reviewed_by=registration.reviewed_by,
        rejection_reason=registration.rejection_reason,
        updated_at=registration.updated_at,
        clan_id=clan.clan_id if clan is not None else None,
        status_history=[
            RegistrationStatusHistoryItem(
                from_status=h.from_status,
                to_status=h.to_status,
                changed_by=h.changed_by,
                reason=h.reason,
                changed_at=h.changed_at,
            )
            for h in history
        ],
        attachments=[  # storage_key is never exposed
            RegistrationAttachmentItem(
                attachment_id=a.attachment_id,
                file_name=a.file_name,
                mime_type=a.mime_type,
                uploaded_at=a.uploaded_at,
            )
            for a in attachments
        ],
    )


# ----- POST /admin/business-registrations/{id}/review -----


async def review_registration(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    family: FamilyRepository,
    principal: Principal,
    registration_id: uuid.UUID,
    body: RegistrationReviewRequest,
    client: ClientInfo,
    now: datetime | None = None,
) -> RegistrationReviewResponse:
    registration = await family.lock_registration(registration_id)  # the ONLY lock, taken first
    if registration is None:
        raise AppError(ErrorCode.NOT_FOUND)
    current = registration.status
    if current != PENDING:
        raise AppError(
            ErrorCode.STATE_CONFLICT,
            f"The registration is {current}; only a PENDING registration can be reviewed.",
        )

    if body.decision == "APPROVED":
        plan = await family.get_plan_by_id(registration.requested_plan_id)
        if plan is None or plan.status != "ACTIVE":
            raise AppError(
                ErrorCode.STATE_CONFLICT,
                "The plan requested by this registration is no longer available; it cannot be approved.",
            )

    new_status = DECISION_STATUS[body.decision]
    reason = body.reason
    changed_at = now or _now()
    await family.apply_registration_review(
        registration,
        status=new_status,
        reviewed_by=principal.user_id,
        # Only a rejection reason is public (shown by tracking); an approval note stays internal.
        rejection_reason=reason if new_status == "REJECTED" else None,
        now=changed_at,
    )
    await family.add_registration_status_history(
        registration_id=registration_id,
        from_status=PENDING,
        to_status=new_status,
        changed_by=principal.user_id,
        reason=reason,
        now=changed_at,
    )
    await users.add_audit_log(
        actor_id=principal.user_id,
        action="registration.review",
        entity_type="business_registration",
        entity_id=registration_id,
        old_data={"status": PENDING},
        new_data={
            "status": new_status,
            "reason_length": len(reason) if reason else None,  # the length, never the text
            "request_id": get_request_id(),
        },
        ip_address=client.ip_address,
        occurred_at=changed_at,
    )
    await db.commit()
    logger.info("registration.review decision=%s request_id=%s", new_status, get_request_id())
    return RegistrationReviewResponse(
        registration_id=registration_id,
        status=new_status,
        reviewed_by=principal.user_id,
        reviewed_at=changed_at,
        reason_visible_to_applicant=new_status == "REJECTED",
    )
