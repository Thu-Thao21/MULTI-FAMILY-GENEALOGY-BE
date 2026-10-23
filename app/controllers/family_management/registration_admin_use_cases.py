"""System Admin use cases for Business registrations (M???c E, step E4): list, detail, review.

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
    foreign keys need KEY SHARE on it, so FOR UPDATE there would deadlock; M???c F lesson).
"""

from __future__ import annotations

import logging
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from app.controllers.auth_access.use_cases import ClientInfo, UnitOfWork
from app.core.config import settings
from app.core.errors import AppError
from app.core.middleware.request_id import get_request_id
from app.dependencies.auth import Principal
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from app.schemas.business import (
    BusinessRegistrationDetail,
    BusinessRegistrationListQuery,
    BusinessRegistrationSummary,
    BusinessApproveAndProvisionResponse,
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


def generate_clan_leader_email(clan_name: str, origin_place: str | None = None) -> str:
    import unicodedata, re

    def to_slug(text: str) -> str:
        text = text.replace("đ", "d").replace("Đ", "d")
        text = unicodedata.normalize("NFD", text)
        text = "".join(c for c in text if unicodedata.category(c) != "Mn")
        text = text.lower()
        text = re.sub(r"^(dong\s*ho|gia\s*pha|ho)\s+", "", text)
        text = re.sub(r"[^a-z0-9]+", "", text)
        return text

    clan_part = to_slug(clan_name) or "clan"
    origin_part = to_slug(origin_place) if origin_place else "vietnam"
    return f"{clan_part}.{origin_part}@giapha.com"


async def _provision_owner_via_firebase_rest(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    family: FamilyRepository,
    principal: Principal,
    clan_id: uuid.UUID,
    clan_name: str,
    applicant_name: str,
    applicant_email: str,
    applicant_phone: str | None,
    origin_place: str | None,
    sender: any,
) -> tuple[str, str, datetime, str]:
    from app.dependencies.permissions import BUSINESS_OWNER_ROLE

    clan_leader_email = generate_clan_leader_email(clan_name, origin_place)
    prefix, domain = clan_leader_email.split("@", 1)
    counter = 1
    while await users.get_user_by_email_ci(clan_leader_email) is not None:
        clan_leader_email = f"{prefix}{counter}@{domain}"
        counter += 1

    chars = string.ascii_letters + string.digits + "!@#$%"
    temp_pass = "".join(secrets.choice(chars) for _ in range(16))

    api_key = settings.FIREBASE_API_KEY
    if not api_key:
        raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "FIREBASE_API_KEY is not configured.")

    sign_up_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={api_key}"
    firebase_uid = None
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        while True:
            resp = await http_client.post(
                sign_up_url,
                json={
                    "email": clan_leader_email,
                    "password": temp_pass,
                    "returnSecureToken": True,
                },
            )
            data = resp.json()
            if resp.status_code == 200:
                firebase_uid = data.get("localId")
                id_token = data.get("idToken")
                if id_token:
                    update_url = f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={api_key}"
                    try:
                        await http_client.post(
                            update_url,
                            json={
                                "idToken": id_token,
                                "displayName": applicant_name,
                                "returnSecureToken": False,
                            },
                        )
                    except Exception as ue:
                        logger.warning("Failed to update Firebase display name: %s", ue)
                break

            error_msg = data.get("error", {}).get("message", "")
            if "EMAIL_EXISTS" in error_msg:
                clan_leader_email = f"{prefix}{counter}@{domain}"
                counter += 1
            else:
                logger.error("Firebase REST signUp failed: %s", data)
                raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, f"Firebase Auth error: {error_msg}")

    now = _now()
    expires_at = now + timedelta(hours=settings.OWNER_TEMP_PASSWORD_TTL_HOURS)
    role = await users.get_role_by_code(BUSINESS_OWNER_ROLE)
    if role is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "Role BUSINESS_OWNER is missing in DB.")

    existing_db_user = await users.get_user_by_email_ci(clan_leader_email)
    if existing_db_user is not None:
        user_id = existing_db_user.user_id
    else:
        user_id = uuid.uuid4()
        await users.create_user_account(
            user_id=user_id,
            firebase_uid=firebase_uid,
            email=clan_leader_email,
            display_name=applicant_name,
            phone=applicant_phone,
            status="PENDING",
            first_login_required=True,
            now=now,
        )
        cred = await users.add_credential_metadata(user_id, now=now)
        cred.must_change_password = True
        cred.temporary_password_issued_at = now
        cred.temporary_password_expires_at = expires_at
        cred.updated_at = now

    cur_membership = await family.get_membership(clan_id, user_id)
    if cur_membership is None:
        await family.create_membership(clan_id=clan_id, user_id=user_id, status="ACTIVE", now=now)

    if not await users.has_active_role(user_id, BUSINESS_OWNER_ROLE, clan_id=clan_id):
        await users.add_clan_role(
            user_id=user_id, role_id=role.role_id, clan_id=clan_id, granted_by=principal.user_id, now=now
        )

    cur_owner = await family.get_active_owner(clan_id)
    if cur_owner is None:
        await family.create_ownership(clan_id=clan_id, user_id=user_id, now=now)

    await db.commit()

    delivery_status = "FAILED"
    try:
        mail_res = await sender.send_owner_temporary_password(
            to_email=applicant_email,
            display_name=applicant_name,
            temporary_password=temp_pass,
            expires_at=expires_at,
            clan_name=clan_name,
            account_email=clan_leader_email,
        )
        if mail_res and mail_res.status:
            delivery_status = mail_res.status
    except Exception as me:
        logger.error("Failed to send credentials email: %s", me)

    return clan_leader_email, temp_pass, expires_at, delivery_status


# ----- POST /admin/business-registrations/{id}/approve-and-provision -----


async def approve_and_provision_registration(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    family: FamilyRepository,
    jobs: any,
    idempotency: any,
    provider: any,
    sender: any,
    principal: Principal,
    registration_id: uuid.UUID,
    client: ClientInfo,
    clan_code: str | None = None,
) -> BusinessApproveAndProvisionResponse:
    from app.controllers.family_management import (
        business_admin_use_cases,
        clan_admin_use_cases,
        owner_provisioning_use_cases,
    )
    from app.schemas.business import BusinessCreateRequest, OwnerProvisionRequest

    # 1. Check registration
    found = await family.get_registration_with_plan(registration_id)
    if found is None:
        raise AppError(ErrorCode.NOT_FOUND)
    registration, _ = found[0], found[1]

    # Save all values to locals BEFORE any commits expire attributes
    rep_email = str(registration.representative_email)
    rep_name = str(registration.representative_name)
    reg_clan_name = str(registration.clan_name)
    reg_origin_place = str(registration.origin_place) if registration.origin_place else None
    rep_phone = str(registration.representative_phone) if registration.representative_phone else None
    current_reg_status = str(registration.status)

    # 2. Review registration if PENDING
    if current_reg_status == PENDING:
        await review_registration(
            db=db,
            users=users,
            family=family,
            principal=principal,
            registration_id=registration_id,
            body=RegistrationReviewRequest(decision="APPROVED"),
            client=client,
        )
        current_reg_status = "APPROVED"

    if current_reg_status != "APPROVED":
        raise AppError(
            ErrorCode.STATE_CONFLICT,
            f"The registration is {current_reg_status}; only APPROVED or PENDING can be provisioned.",
        )

    # 3. Create Clan if not created yet
    clan = await family.get_clan_by_registration_id(registration_id)
    if clan is None:
        clan_key = f"auto-clan-{registration_id}"
        await business_admin_use_cases.create_business(
            db=db,
            users=users,
            family=family,
            idempotency=idempotency,
            principal=principal,
            registration_id=registration_id,
            body=BusinessCreateRequest(clan_code=clan_code),
            key=clan_key,
            client=client,
        )
        clan = await family.get_clan_by_registration_id(registration_id)
        if clan is None:
            raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to initialize clan space.")

    # 4. Provision Owner & send credentials email
    existing_owner = await family.get_active_owner(clan.clan_id)
    temp_pass = None
    expires_at = None
    delivery_status = None
    if existing_owner is None:
        clan_leader_email = generate_clan_leader_email(reg_clan_name, reg_origin_place)
        prefix, domain = clan_leader_email.split("@", 1)
        counter = 1
        while await users.get_user_by_email_ci(clan_leader_email) is not None:
            clan_leader_email = f"{prefix}{counter}@{domain}"
            counter += 1

        provision_success = False
        if getattr(provider, "admin_api_enabled", False):
            try:
                owner_key = f"auto-owner-{clan.clan_id}"
                prov = await owner_provisioning_use_cases.provision_owner(
                    db=db,
                    users=users,
                    family=family,
                    jobs=jobs,
                    idempotency=idempotency,
                    provider=provider,
                    sender=sender,
                    principal=principal,
                    clan_id=clan.clan_id,
                    body=OwnerProvisionRequest(
                        email=clan_leader_email,
                        display_name=rep_name,
                        phone=rep_phone,
                    ),
                    key=owner_key,
                    client=client,
                )
                temp_pass = prov.response.temporary_password
                expires_at = prov.response.temporary_password_expires_at
                delivery_status = prov.response.email_delivery_status
                owner_email = prov.response.owner_email or clan_leader_email
                owner_name = prov.response.owner_display_name or rep_name

                mail_res = await sender.send_owner_temporary_password(
                    to_email=rep_email,
                    display_name=rep_name,
                    temporary_password=temp_pass or "",
                    expires_at=expires_at or _now(),
                    clan_name=clan.name,
                    account_email=owner_email,
                )
                if mail_res.status:
                    delivery_status = mail_res.status
                provision_success = True
            except AppError as e:
                if e.code != ErrorCode.PROVIDER_UNAVAILABLE:
                    raise
                logger.warning("Admin SDK provider unavailable, falling back to Firebase REST: %s", e)

        if not provision_success:
            owner_email, temp_pass, expires_at, delivery_status = await _provision_owner_via_firebase_rest(
                db=db,
                users=users,
                family=family,
                principal=principal,
                clan_id=clan.clan_id,
                clan_name=clan.name,
                applicant_name=rep_name,
                applicant_email=rep_email,
                applicant_phone=rep_phone,
                origin_place=reg_origin_place,
                sender=sender,
            )
            owner_name = rep_name
    else:
        owner_user = await users.get_user_by_id(existing_owner.user_id)
        owner_email = owner_user.email if owner_user else rep_email
        owner_name = owner_user.display_name if owner_user else rep_name
        delivery_status = "SENT"

    # 5. Activate Clan if PENDING
    clan_status = clan.status
    if clan.status == "PENDING":
        try:
            await clan_admin_use_cases.activate_clan(
                db=db,
                users=users,
                family=family,
                idempotency=idempotency,
                principal=principal,
                clan_id=clan.clan_id,
                client=client,
            )
            clan_status = "ACTIVE"
        except Exception as e:
            logger.warning("Clan activation in approve_and_provision: %s", e)
            clan_refresh = await family.get_clan_by_registration_id(registration_id)
            if clan_refresh:
                clan_status = clan_refresh.status

    email_sent = delivery_status == "SENT"
    if email_sent:
        msg = f"Đã phê duyệt và gửi email tài khoản Trưởng tộc ({owner_email}) tới hộp thư {rep_email} thành công."
    else:
        msg = f"Đã phê duyệt và cấp tài khoản Trưởng tộc ({owner_email})."

    return BusinessApproveAndProvisionResponse(
        registration_id=registration_id,
        clan_id=clan.clan_id,
        clan_name=clan.name or reg_clan_name,
        status="APPROVED",
        clan_status=clan_status,
        owner_email=owner_email,
        owner_display_name=owner_name,
        temporary_password=temp_pass,
        temporary_password_expires_at=expires_at,
        email_sent=email_sent,
        email_delivery_status=delivery_status,
        message=msg,
    )

