"""System Admin use cases on a clan: activate it, and read it (Mốc E, step E7).

POST /admin/clans/{clan_id}/activate: PENDING -> ACTIVE. The activation is the SA's MANUAL CONFIRMATION
(decision D03): there is no payment check (payment is Sprint 6, KI-19) and a trial plan and a paid plan
take the same road. ONE transaction, ONE commit, no Idempotency-Key: it is a one-way change like the
review of a registration. After a lost response the second call is a 409 that says the clan is ACTIVE,
and that 409 means the first call SUCCEEDED.

Conditions, all checked under the locks (each failure is a 409 STATE_CONFLICT that names what is wrong,
never an e-mail or a name):
  1. the clan is PENDING (the message names the current status; 404 when there is no such clan);
  2. the clan has a current Owner (clan_ownership_history.ended_at IS NULL), whose membership is ACTIVE
     and not revoked and who still holds the BUSINESS_OWNER role in the clan: exactly what authorize()
     needs, so the Owner can really work once the clan is ACTIVE;
  3. the Owner's account is PENDING or ACTIVE: not LOCKED, DISABLED or SUSPENDED (an unknown status is
     refused too). The Owner need NOT have changed the password yet (Q1);
  4. exactly one subscription of the clan is PENDING and none is ACTIVE;
  5. the plan of that subscription is still ACTIVE (Q2). There is no endpoint to change the plan of a
     subscription: docs/known_issues.md KI-32 says how an operator clears the clan.

Effect: clans.status = ACTIVE, activated_at = updated_at = now; the subscription becomes ACTIVE with
starts_at = now and ends_at = starts_at + the plan's billing period in calendar months (add_months);
one audit row (ids, statuses, dates, plan code, request_id: no e-mail, name or phone).

Lock order: the clan row, then the subscription rows of the clan (ORDER BY subscription_id), both FOR NO
KEY UPDATE; everything else is read without a lock and the `users` row is never locked. Owner
provisioning locks the idempotency row, the clan, then the job, so the two cannot deadlock: both take the
clan first.

GET /admin/clans/{clan_id}: read only, no lock. Status, dates, registration id, a summary of the
subscription, the Owner's user id and the id and status of the latest Owner job. No e-mail, name, phone,
Firebase uid or clan name.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from app.controllers.auth_access.use_cases import ClientInfo, UnitOfWork
from app.core.dates import add_months
from app.core.errors import AppError
from app.core.idempotency import LOCK_TIMEOUT_SECONDS, IdempotencyStore, rollback_on_error, utcnow
from app.core.request_id import get_request_id
from app.dependencies.auth import Principal
from app.models.family.provisioning_repository import ProvisioningRepository
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from app.schemas.business import (
    ClanActivateResponse,
    ClanDetailResponse,
    ClanOwnerJobSummary,
    ClanSubscriptionSummary,
)
from app.schemas.errors import ErrorCode

logger = logging.getLogger("mfg.clan_admin")

BUSINESS_OWNER_ROLE = "BUSINESS_OWNER"
OWNER_ACCOUNT_STATUSES = ("PENDING", "ACTIVE")  # anything else, known or not, is refused


def _conflict(message: str) -> AppError:
    return AppError(ErrorCode.STATE_CONFLICT, message)


async def activate_clan(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    family: FamilyRepository,
    idempotency: IdempotencyStore,
    principal: Principal,
    clan_id: uuid.UUID,
    client: ClientInfo,
    now: datetime | None = None,
) -> ClanActivateResponse:
    moment = now or utcnow()  # looked up at call time; ONE instant for the clan, the subscription and the audit row
    async with rollback_on_error(db):
        await idempotency.set_lock_timeout(LOCK_TIMEOUT_SECONDS)  # SET LOCAL: this transaction only
        clan = await family.lock_clan(clan_id)  # lock order: the clan ...
        if clan is None:
            raise AppError(ErrorCode.NOT_FOUND)
        if clan.status != "PENDING":
            since = f" (activated at {clan.activated_at.isoformat()})" if clan.status == "ACTIVE" and clan.activated_at else ""
            raise _conflict(f"The clan is {clan.status}{since}; only a PENDING clan can be activated.")
        subscriptions = await family.lock_subscriptions(clan_id)  # ... then its subscriptions

        owner = await family.get_active_owner(clan_id)
        if owner is None:
            raise _conflict("The clan has no Owner yet; create the Owner first.")
        membership = await family.get_membership(clan_id, owner.user_id)
        if membership is None or membership.status != "ACTIVE" or membership.revoked_at is not None:
            raise _conflict("The Owner of the clan is not an active member of it.")
        if not await users.has_active_role(owner.user_id, BUSINESS_OWNER_ROLE, clan_id=clan_id):
            raise _conflict("The Owner of the clan does not hold the Business Owner role.")
        owner_account = await users.get_user_by_id(owner.user_id)
        if owner_account is None or owner_account.status not in OWNER_ACCOUNT_STATUSES:
            status = owner_account.status if owner_account is not None else "missing"
            raise _conflict(f"The Owner account is {status}; a clan cannot be activated with it.")

        if any(s.status == "ACTIVE" for s in subscriptions):
            raise _conflict("The clan already has an ACTIVE subscription.")
        pending = [s for s in subscriptions if s.status == "PENDING"]
        if not pending:
            raise _conflict("The clan has no PENDING subscription to activate.")
        if len(pending) > 1:
            raise _conflict("The clan has more than one PENDING subscription; the data must be fixed first.")
        subscription = pending[0]
        plan = await family.get_plan_by_id(subscription.plan_id)
        if plan is None or plan.status != "ACTIVE":
            raise _conflict("The plan of the subscription is no longer available.")

        starts_at = moment
        ends_at = add_months(moment, plan.billing_period_months)
        await family.activate_clan(clan, now=moment)
        await family.activate_subscription(subscription, starts_at=starts_at, ends_at=ends_at)
        await users.add_audit_log(
            actor_id=principal.user_id,
            action="clan.activate",
            entity_type="clan",
            entity_id=clan_id,
            clan_id=clan_id,
            old_data={"status": "PENDING", "subscription_status": "PENDING"},
            new_data={
                "status": "ACTIVE",
                "subscription_id": str(subscription.subscription_id),
                "subscription_status": "ACTIVE",
                "plan_id": str(plan.plan_id),
                "plan_code": plan.code,
                "owner_user_id": str(owner.user_id),
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "request_id": get_request_id(),
            },
            ip_address=client.ip_address,
            occurred_at=moment,
        )
        response = ClanActivateResponse(
            clan_id=clan_id,
            status="ACTIVE",
            activated_at=moment,
            subscription_id=subscription.subscription_id,
            subscription_status="ACTIVE",
            starts_at=starts_at,
            ends_at=ends_at,
        )
        await db.commit()
    logger.info("clan.activate clan_id=%s request_id=%s", clan_id, get_request_id())
    return response


async def get_clan(
    *, family: FamilyRepository, jobs: ProvisioningRepository, clan_id: uuid.UUID
) -> ClanDetailResponse:
    clan = await family.get_clan_by_id(clan_id)
    if clan is None:
        raise AppError(ErrorCode.NOT_FOUND)
    subscriptions = await family.list_subscriptions(clan_id)
    # the subscription that matters: the ACTIVE one, else a PENDING one, else the latest
    chosen = next((s for s in subscriptions if s.status == "ACTIVE"), None) or next(
        (s for s in subscriptions if s.status == "PENDING"), None
    ) or (subscriptions[0] if subscriptions else None)
    summary = None
    if chosen is not None:
        plan = await family.get_plan_by_id(chosen.plan_id)
        summary = ClanSubscriptionSummary(
            subscription_id=chosen.subscription_id,
            plan_id=chosen.plan_id,
            plan_code=plan.code if plan is not None else None,
            status=chosen.status,
            starts_at=chosen.starts_at,
            ends_at=chosen.ends_at,
        )
    owner = await family.get_active_owner(clan_id)
    job = await jobs.latest_for_clan(clan_id)
    return ClanDetailResponse(
        clan_id=clan.clan_id,
        clan_code=clan.clan_code,
        status=clan.status,
        registration_id=clan.registration_id,
        created_at=clan.created_at,
        activated_at=clan.activated_at,
        subscription=summary,
        owner_user_id=owner.user_id if owner is not None else None,
        last_owner_job=(
            ClanOwnerJobSummary(job_id=job.job_id, status=job.status, needs_cleanup=job.needs_cleanup)
            if job is not None
            else None
        ),
    )
