"""System Admin use case: create the Business (clan) of an APPROVED registration (Mốc E, step E5).

POST /admin/business-registrations/{id}/business, Idempotency-Key required. In ONE transaction:
the idempotency row, a PENDING clan, its profile, a PENDING subscription and one audit row. No
Owner is created here (E6); the clan only becomes ACTIVE through clan.activate (E7), after an
Owner exists.

Rules:
  * the registration must be APPROVED (409 STATE_CONFLICT otherwise; the message names the status),
    must not have a clan yet (409 DUPLICATE_RESOURCE) and its requested plan must still be ACTIVE
    (409 STATE_CONFLICT; E4 checked at approval, this checks again). The plan is read from the
    database, never from the request;
  * the lock order is fixed: the idempotency row, then the registration row (FOR NO KEY UPDATE),
    then the clan and the other tables. The `users` row is never locked;
  * a clan code given by the SA that is taken is 409 DUPLICATE_RESOURCE; a generated one that is
    taken is drawn again (3 attempts in all). The unique indexes are the last line of defence: their
    IntegrityError becomes the same 409, and any OTHER IntegrityError is a bug and becomes a 500;
  * the audit row holds ids, the plan code, statuses and the request_id: no e-mail, name, phone,
    clan name or clan code (docs/security_review.md 3.5);
  * the registration keeps its status (APPROVED, final). No registration_status_history row is
    written: nothing about the registration changes; the clan's registration_id is the link;
  * the subscription dates are PROVISIONAL: it starts when the Business is created and lasts the
    plan's billing period; E7 sets them again when the clan is activated.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Callable

from sqlalchemy.exc import IntegrityError

from app.controllers.auth_access.use_cases import ClientInfo, UnitOfWork
from app.core.clan_code import generate_clan_code
from app.core.dates import add_months
from app.core.db_errors import constraint_name
from app.core.errors import AppError
from app.core.idempotency import (
    IdempotencyStore,
    IdempotentOutcome,
    IdempotentResult,
    compute_request_hash,
    run_idempotent,
    utcnow,
)
from app.core.request_id import get_request_id
from app.dependencies.auth import Principal
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from app.schemas.business import BusinessCreateRequest, BusinessCreateResponse
from app.schemas.errors import ErrorCode

logger = logging.getLogger("mfg.business_admin")

ENDPOINT = "POST /admin/business-registrations/{registration_id}/business"
CLAN_CODE_KEY = "clans_clan_code_key"
CLAN_REGISTRATION_KEY = "clans_registration_id_key"
GENERATED_CODE_ATTEMPTS = 3


def _duplicate_code() -> AppError:
    return AppError(ErrorCode.DUPLICATE_RESOURCE, "This clan code is already in use.")


def _duplicate_business() -> AppError:
    return AppError(ErrorCode.DUPLICATE_RESOURCE, "This registration already has a Business.")


async def create_business(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    family: FamilyRepository,
    idempotency: IdempotencyStore,
    principal: Principal,
    registration_id: uuid.UUID,
    body: BusinessCreateRequest,
    key: str,
    client: ClientInfo,
    now: datetime | None = None,
    code_generator: Callable[[], str] | None = None,
) -> IdempotentResult:
    request_hash = compute_request_hash(
        method="POST",
        endpoint=ENDPOINT,
        path_params={"registration_id": registration_id},
        body=body.model_dump(mode="json", exclude_none=True),
    )

    generate = code_generator or generate_clan_code  # looked up at call time
    # `now` is read once so the clan, the subscription, the audit row and the key share one instant.
    moment = now or utcnow()

    async def execute() -> IdempotentOutcome:
        registration = await family.lock_registration(registration_id)  # after the idempotency row
        if registration is None:
            raise AppError(ErrorCode.NOT_FOUND)
        if registration.status != "APPROVED":
            raise AppError(
                ErrorCode.STATE_CONFLICT,
                f"The registration is {registration.status}; only an APPROVED registration can "
                "get a Business.",
            )
        if await family.get_clan_by_registration_id(registration_id) is not None:
            raise _duplicate_business()
        plan = await family.get_plan_by_id(registration.requested_plan_id)
        if plan is None or plan.status != "ACTIVE":
            raise AppError(
                ErrorCode.STATE_CONFLICT,
                "The plan requested by this registration is no longer available.",
            )

        supplied = body.clan_code
        if supplied is not None and await family.get_clan_by_code(supplied) is not None:
            raise _duplicate_code()

        clan = None
        for _attempt in range(1 if supplied is not None else GENERATED_CODE_ATTEMPTS):
            code = supplied if supplied is not None else generate()
            try:
                clan = await family.create_clan(
                    registration_id=registration_id,
                    clan_code=code,
                    name=registration.clan_name,
                    created_by=principal.user_id,
                    now=moment,
                )
                break
            except IntegrityError as exc:
                name = constraint_name(exc)
                if name == CLAN_CODE_KEY:
                    if supplied is not None:
                        raise _duplicate_code() from None
                    continue  # a generated code collided: draw another
                if name == CLAN_REGISTRATION_KEY:
                    raise _duplicate_business() from None  # lost a race the lock should have stopped
                raise  # anything else is a bug, not input: it becomes a 500
        if clan is None:
            logger.error("business.create could not draw a free clan code request_id=%s", get_request_id())
            raise AppError(ErrorCode.INTERNAL_ERROR)

        await family.create_clan_profile(
            clan_id=clan.clan_id, origin_place=registration.origin_place, now=moment
        )
        subscription = await family.create_subscription(
            clan_id=clan.clan_id,
            plan_id=plan.plan_id,
            starts_at=moment,
            ends_at=add_months(moment, plan.billing_period_months),
            status="PENDING",
            now=moment,
        )
        await users.add_audit_log(
            actor_id=principal.user_id,
            action="business.create",
            entity_type="clan",
            entity_id=clan.clan_id,
            clan_id=clan.clan_id,
            old_data=None,
            new_data={
                "registration_id": str(registration_id),
                "plan_id": str(plan.plan_id),
                "plan_code": plan.code,
                "subscription_id": str(subscription.subscription_id),
                "clan_status": "PENDING",
                "subscription_status": "PENDING",
                "request_id": get_request_id(),
            },
            ip_address=client.ip_address,
            occurred_at=moment,
        )
        response = BusinessCreateResponse(
            clan_id=clan.clan_id,
            clan_code=clan.clan_code,
            clan_status="PENDING",
            subscription_id=subscription.subscription_id,
            plan_id=plan.plan_id,
            subscription_status="PENDING",
            starts_at=subscription.starts_at,
            ends_at=subscription.ends_at,
        )
        logger.info("business.create request_id=%s", get_request_id())
        return IdempotentOutcome(
            status=201,
            body=response.model_dump(mode="json"),
            resource_type="clan",
            resource_id=clan.clan_id,
        )

    return await run_idempotent(
        db=db,
        store=idempotency,
        actor_id=principal.user_id,
        endpoint=ENDPOINT,
        key=key,
        request_hash=request_hash,
        execute=execute,
        now=moment,
    )
