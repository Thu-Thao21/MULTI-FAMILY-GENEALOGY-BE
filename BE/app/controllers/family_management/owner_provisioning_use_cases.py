"""System Admin use cases: create the Owner of a clan through Firebase, and read a job (Mốc E6a).

POST /admin/clans/{clan_id}/owner (Idempotency-Key required). Firebase and PostgreSQL share no
transaction, so the work is a JOB made of short database transactions with Firebase calls BETWEEN
them. Every transaction is committed before a Firebase call starts: a call never runs while a
transaction or a connection is held open (the call goes through asyncio.to_thread, at most
FIREBASE_CALL_TIMEOUT_SECONDS each).

  T1  claim the Idempotency-Key, lock the clan, run every check, insert the job (PENDING), commit.
  T2  claim the job: RUNNING, attempt_count + 1, a lease of PROVISIONING_LEASE_SECONDS, commit.
      -- Firebase: get_user(own-<job_id>); create_user, or set_password when it already exists --
  T3  firebase_user_created = true (and a heartbeat on the lease), commit.
  T4  the users row (PENDING, must change the password), credential_metadata (temporary password
      issued now, expires in OWNER_TEMP_PASSWORD_TTL_HOURS), membership, BUSINESS_OWNER role, ownership,
      job SUCCEEDED, the idempotency key COMPLETED, audit, commit.
      -- then the EmailSender (Noop today) --

Rules:
  * the Firebase uid is own-<job_id>; a clean-up deletes ONLY that uid, never a user found by e-mail;
  * FENCING: a run writes its result only while the job is RUNNING and its attempt_count is the one it
    was started with. The lease clock is not consulted;
  * COMPENSATION on a final failure: FAILED with needs_cleanup (and firebase_user_created) is COMMITTED
    FIRST, then delete_user(own-<job_id>) is tried (even when we are not sure the user exists), then the
    flags are lowered. If the delete fails the flags stay up and keep the clan and the e-mail blocked.
    ONE exception, UID_MISMATCH: a user under own-<job_id> whose e-mail is not the job's is NOT ours to
    judge. It is never deleted: the job becomes FAILED without needs_cleanup and a person looks at it;
  * a temporary failure of attempt N >= PROVISIONING_MAX_ATTEMPTS is final;
  * the temporary password exists only in memory and in the one response. The idempotency row stores
    {job_id, status, clan_id, user_id}; a replay answers with those and nulls (never the password);
  * the audit rows (one per job state change) hold ids, statuses and error codes: no e-mail, name,
    phone, Firebase uid or password.
Lock order: idempotency row, clan, job; the `users` row is never locked.

Mốc E6b adds, on the same job and the same steps:
  * retry_job    POST /admin/provisioning-jobs/{id}/retry   a new run of FAILED_RETRYABLE, of a stuck PENDING,
                 of a RUNNING whose lease ran out; or only the Firebase clean-up of a FAILED job that still
                 owes it (no password is made then). A retry that succeeds ALWAYS makes a new password and
                 shows it once. The original Idempotency-Key, if it is still IN_PROGRESS, is completed (or
                 released on a failure): it is found through the job, not through the key text;
  * abandon_job  POST /admin/provisioning-jobs/{id}/abandon  give up: FAILED; the clean-up of own-<job_id> is
                 tried whenever a run ever started; never a RUNNING job whose lease is alive;
  * list_jobs    GET /admin/provisioning-jobs.
Both Owner flows (this module and the temporary-password reset) set a password only through
IdentityProvider.set_owner_password, which accepts nothing but an own-<uuid>.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from sqlalchemy.exc import IntegrityError, OperationalError

from app.controllers.auth_access.use_cases import ClientInfo, UnitOfWork
from app.controllers.family_management import provisioning_state as state
from app.core.config import settings
from app.core.db_errors import constraint_name
from app.core.email_sender import EmailDeliveryResult, EmailSender
from app.core.errors import AppError
from app.core.firebase import (
    IdentityProvider,
    PasswordRejected,
    ProviderEmailTaken,
    ProviderInvalidUser,
    ProviderUnavailable,
    ProviderUserExists,
    ProviderUserNotFound,
    UnsafeUid,
    own_uid,
)
from app.core.idempotency import (
    LOCK_TIMEOUT_SECONDS,
    REPLAY,
    IN_PROGRESS,
    IdempotencyStore,
    claim_idempotency,
    complete_idempotency,
    compute_request_hash,
    rollback_on_error,
    rollback_quietly,
    utcnow,
)
from app.core.passwords import generate_temporary_password
from app.core.request_id import get_request_id
from app.dependencies.auth import Principal
from app.models.family.provisioning_repository import ProvisioningRepository
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from app.schemas.business import (
    OwnerProvisionRequest,
    OwnerProvisionResponse,
    ProvisioningJobListQuery,
    ProvisioningJobResponse,
)
from app.schemas.common import Page
from app.schemas.errors import ErrorCode

logger = logging.getLogger("mfg.owner_provisioning")

ENDPOINT = "POST /admin/clans/{clan_id}/owner"
BUSINESS_OWNER_ROLE = "BUSINESS_OWNER"
IN_PROGRESS_RETRY_AFTER = "5"
JOB_RESOURCE = "provisioning_job"
LIVE_PER_CLAN_INDEX = "uq_provisioning_job_live_per_clan"
LIVE_EMAIL_INDEX = "uq_provisioning_job_live_email"
USER_EMAIL_CONSTRAINTS = ("users_email_key", "uq_users_email_lower")
ACTIVE_OWNER_INDEX = "uq_active_clan_owner"


# ----- failures: what is stored on the job (error_code), whether it can be retried, what the caller sees -----


@dataclass(frozen=True)
class Failure:
    code: str
    retryable: bool
    error: ErrorCode
    message: str  # may contain {job_id}
    compensate: bool = True  # a final failure deletes Firebase user own-<job_id> (False: never touch it)


FAILURES: dict[str, Failure] = {
    f.code: f
    for f in (
        Failure("PROVIDER_UNAVAILABLE", True, ErrorCode.PROVIDER_UNAVAILABLE,
                "The identity provider is unavailable; job {job_id} can be retried."),
        Failure("PASSWORD_POLICY_REJECTED", True, ErrorCode.PROVIDER_UNAVAILABLE,
                "The identity provider rejected the generated password (password policy); "
                "job {job_id} can be retried."),
        Failure("DATABASE_UNAVAILABLE", True, ErrorCode.DATABASE_UNAVAILABLE,
                "The database was unavailable; job {job_id} can be retried."),
        Failure("INTERNAL_ERROR", True, ErrorCode.INTERNAL_ERROR,
                "An unexpected error occurred; job {job_id} can be retried."),
        Failure("PROVIDER_EMAIL_TAKEN", False, ErrorCode.DUPLICATE_RESOURCE,
                "This e-mail address is already used by another account at the identity provider."),
        Failure("PROVIDER_REJECTED_USER", False, ErrorCode.STATE_CONFLICT,
                "The identity provider refused the owner data; job {job_id} failed."),
        Failure("UID_MISMATCH", False, ErrorCode.STATE_CONFLICT,
                "The identity provider holds an unexpected user for job {job_id}; it was left untouched "
                "and needs a manual check.", compensate=False),
        Failure("OWNER_EMAIL_EXISTS", False, ErrorCode.DUPLICATE_RESOURCE,
                "An account with this e-mail address already exists."),
        Failure("CLAN_STATE_CHANGED", False, ErrorCode.STATE_CONFLICT,
                "The clan changed while the Owner was being created; job {job_id} failed."),
    )
}


class _StepFailed(Exception):
    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.code)
        self.failure = failure


class _LostLease(Exception):
    """Another run has taken the job over (its attempt_count moved on): this run writes nothing."""


@dataclass(frozen=True)
class JobRun:
    """Plain values of a running job, so no ORM object is touched after a rollback."""

    job_id: uuid.UUID
    clan_id: uuid.UUID
    attempt: int
    email: str
    display_name: str
    uid: str
    actor_id: uuid.UUID
    ip_address: str | None


@dataclass(frozen=True)
class ProvisionResult:
    status: int
    response: OwnerProvisionResponse
    replayed: bool


def _error(failure: Failure, job_id: uuid.UUID, *, exhausted: bool = False, attempts: int = 0) -> AppError:
    if exhausted:
        return AppError(
            ErrorCode.STATE_CONFLICT,
            f"Job {job_id} failed {attempts} times and can no longer be retried ({failure.code}).",
        )
    return AppError(failure.error, failure.message.format(job_id=job_id))


async def _lock_key(idempotency: IdempotencyStore, job_id: uuid.UUID):
    """The Idempotency-Key row that is working on this job, found by the job (not by the key text), so a
    RETRY sent by another administrator, with no key of its own, completes or releases the original one.
    None when there is none (a failure releases it)."""
    return await idempotency.lock_by_resource(resource_type=JOB_RESOURCE, resource_id=job_id)


def _lost_lease_error() -> AppError:
    return AppError(ErrorCode.STATE_CONFLICT, "This run was replaced by a newer attempt of the same job.")


def _in_progress_error(job_id: uuid.UUID | None) -> AppError:
    where = f" as job {job_id}" if job_id else ""
    return AppError(
        ErrorCode.STATE_CONFLICT,
        f"This request is already in progress{where}; retry shortly.",
        headers={"Retry-After": IN_PROGRESS_RETRY_AFTER},
    )


async def _audit(
    users: UserAccessRepository,
    *,
    event: str,
    from_status: str | None,
    to_status: str,
    attempt: int,
    at: datetime,
    ip_address: str | None,
    actor_id: uuid.UUID,
    job_id: uuid.UUID,
    clan_id: uuid.UUID,
    error_code: str | None = None,
    needs_cleanup: bool | None = None,
    user_id: uuid.UUID | None = None,
) -> None:
    """One audit row per job state change: ids, statuses and the error code. Nothing personal."""
    await users.add_audit_log(
        actor_id=actor_id,
        action="provisioning_job.transition",
        entity_type="provisioning_job",
        entity_id=job_id,
        clan_id=clan_id,
        old_data={"status": from_status} if from_status else None,
        new_data={
            "event": event,
            "status": to_status,
            "attempt_count": attempt,
            "error_code": error_code,
            "needs_cleanup": needs_cleanup,
            "user_id": str(user_id) if user_id else None,
            "request_id": get_request_id(),
        },
        ip_address=ip_address,
        occurred_at=at,
    )


# ----- POST /admin/clans/{clan_id}/owner -----


async def provision_owner(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    family: FamilyRepository,
    jobs: ProvisioningRepository,
    idempotency: IdempotencyStore,
    provider: IdentityProvider,
    sender: EmailSender,
    principal: Principal,
    clan_id: uuid.UUID,
    body: OwnerProvisionRequest,
    key: str,
    client: ClientInfo,
    clock: Callable[[], datetime] | None = None,
    password_factory: Callable[[], str] | None = None,
) -> ProvisionResult:
    if not provider.admin_api_enabled:
        raise AppError(ErrorCode.PROVIDER_UNAVAILABLE)  # nothing written: no job, no key

    clock = clock or (lambda: utcnow())  # looked up at call time, so a test can replace utcnow

    request_hash = compute_request_hash(
        method="POST",
        endpoint=ENDPOINT,
        path_params={"clan_id": clan_id},
        body=body.model_dump(mode="json", exclude_none=True),
    )
    accepted = await _accept(
        db=db, users=users, family=family, jobs=jobs, idempotency=idempotency, principal=principal,
        clan_id=clan_id, body=body, key=key, client=client, request_hash=request_hash, clock=clock,
    )
    if isinstance(accepted, ProvisionResult):
        return accepted  # a replay of a finished request
    run = await _start(db=db, users=users, jobs=jobs, idempotency=idempotency, run=accepted, clock=clock)
    return await _execute(
        db=db, users=users, family=family, jobs=jobs, idempotency=idempotency, provider=provider,
        sender=sender, run=run, clock=clock, password_factory=password_factory, status=201,
    )


async def _execute(
    *, db, users, family, jobs, idempotency, provider, sender, run: JobRun, clock, password_factory, status: int
) -> ProvisionResult:
    """Everything after the job is RUNNING (T2 done): Firebase, then T3 and T4, or the failure record.
    Shared by the first run and by a retry; `status` is the HTTP status of the success."""
    password = (password_factory or _default_password)()
    try:
        await _firebase_step(provider, run, password)
        await _mark_created(db=db, idempotency=idempotency, jobs=jobs, run=run, clock=clock)
        user_id, issued_at, expires_at = await _finish(
            db=db, users=users, family=family, jobs=jobs, idempotency=idempotency, run=run, clock=clock
        )
    except _LostLease:
        raise _lost_lease_error() from None
    except _StepFailed as exc:
        raise await _record_failure(
            db=db, users=users, jobs=jobs, idempotency=idempotency, provider=provider, run=run,
            failure=exc.failure, clock=clock,
        ) from None

    delivery = await _send(sender, run, password, expires_at)
    logger.info("owner.provision job_id=%s step=done request_id=%s", run.job_id, get_request_id())
    return ProvisionResult(
        status=status,
        replayed=False,
        response=OwnerProvisionResponse(
            job_id=run.job_id,
            status="SUCCEEDED",
            clan_id=run.clan_id,
            user_id=user_id,
            owner_email=run.email,
            owner_display_name=run.display_name,
            temporary_password=password,
            temporary_password_expires_at=expires_at,
            email_delivery_status=delivery.status,
        ),
    )


def _default_password() -> str:
    return generate_temporary_password(require_symbol=settings.OWNER_TEMP_PASSWORD_REQUIRE_SYMBOL)


# ----- T1: accept the request -----


async def _owner_info(family: FamilyRepository, clan, body: OwnerProvisionRequest):
    """Where the Owner's data comes from: the body (an override) or else the representative of the
    Business registration the clan was created from."""
    registration = (
        await family.get_registration_by_id(clan.registration_id) if clan.registration_id else None
    )
    email = body.email or (registration.representative_email if registration else None)
    display_name = body.display_name or (registration.representative_name if registration else None)
    phone = body.phone or (registration.representative_phone if registration else None)
    missing = [name for name, value in (("email", email), ("display_name", display_name)) if not value]
    if missing:
        message = AppError(ErrorCode.VALIDATION_ERROR).message
        raise AppError(
            ErrorCode.VALIDATION_ERROR, f"{message} Fields: {', '.join('body.' + m for m in missing)}"
        )
    return email, display_name, phone


async def _accept(
    *, db, users, family, jobs, idempotency, principal, clan_id, body, key, client, request_hash, clock
) -> "ProvisionResult | JobRun":
    now = clock()
    async with rollback_on_error(db):
        claim = await claim_idempotency(
            idempotency, actor_id=principal.user_id, endpoint=ENDPOINT, key=key,
            request_hash=request_hash, now=now,
        )
        if claim.outcome == REPLAY:
            stored = claim.row.response_body or {}
            return ProvisionResult(  # the stored form has NO password and no personal data
                status=claim.row.response_status or 201,
                replayed=True,
                response=OwnerProvisionResponse(
                    job_id=stored["job_id"], status=stored["status"], clan_id=stored["clan_id"],
                    user_id=stored.get("user_id"),
                ),
            )
        if claim.outcome == IN_PROGRESS:
            raise _in_progress_error(claim.row.resource_id)

        clan = await family.lock_clan(clan_id)
        if clan is None:
            raise AppError(ErrorCode.NOT_FOUND)
        if clan.status != "PENDING":
            raise AppError(
                ErrorCode.STATE_CONFLICT,
                f"The clan is {clan.status}; an Owner can only be provisioned for a PENDING clan.",
            )
        if await family.get_active_owner(clan_id) is not None:
            raise AppError(ErrorCode.STATE_CONFLICT, "This clan already has an Owner.")
        email, display_name, phone = await _owner_info(family, clan, body)

        blockers = await jobs.list_blocking(clan_id=clan_id, email=email)
        for job in blockers:  # a Firebase clean-up that is still owed blocks first (the clan or the e-mail)
            if job.needs_cleanup:
                raise AppError(
                    ErrorCode.STATE_CONFLICT,
                    f"Provisioning job {job.job_id} still needs a clean-up at the identity provider; "
                    "finish it first.",
                )
        for job in blockers:
            if job.clan_id == clan_id:
                raise AppError(
                    ErrorCode.STATE_CONFLICT,
                    f"Provisioning job {job.job_id} of this clan is {job.status}; continue it instead "
                    "of starting a new one.",
                )
            raise AppError(
                ErrorCode.DUPLICATE_RESOURCE,
                "A provisioning job for this e-mail address is already in progress.",
            )
        if await users.get_user_by_email_ci(email) is not None:
            raise AppError(ErrorCode.DUPLICATE_RESOURCE, "An account with this e-mail address already exists.")

        job_id = uuid.uuid4()
        try:
            await jobs.insert_pending(
                job_id=job_id, clan_id=clan_id, requested_by=principal.user_id, email=email,
                display_name=display_name, phone=phone, now=now,
            )
        except IntegrityError as exc:  # the unique indexes are the last line of defence
            name = constraint_name(exc)
            if name == LIVE_PER_CLAN_INDEX:
                raise AppError(ErrorCode.STATE_CONFLICT, "This clan already has a provisioning job.") from None
            if name == LIVE_EMAIL_INDEX:
                raise AppError(
                    ErrorCode.DUPLICATE_RESOURCE,
                    "A provisioning job for this e-mail address is already in progress.",
                ) from None
            raise
        await idempotency.set_resource(claim.row, resource_type=JOB_RESOURCE, resource_id=job_id)
        await _audit(
            users, event="created", from_status=None, to_status=state.PENDING, attempt=0, at=now,
            ip_address=client.ip_address, actor_id=principal.user_id, job_id=job_id, clan_id=clan_id,
        )
        await db.commit()
    return JobRun(
        job_id=job_id, clan_id=clan_id, attempt=0, email=email, display_name=display_name,
        uid=own_uid(job_id), actor_id=principal.user_id, ip_address=client.ip_address,
    )


# ----- T2: start the run -----


async def _start(*, db, users, jobs, idempotency, run: JobRun, clock) -> JobRun:
    now = clock()
    async with rollback_on_error(db):
        await idempotency.set_lock_timeout(LOCK_TIMEOUT_SECONDS)
        job = await jobs.lock(run.job_id)
        if job is None:
            raise AppError(ErrorCode.INTERNAL_ERROR)
        try:
            state.decide_claim(
                job, now, lease_seconds=settings.PROVISIONING_LEASE_SECONDS,
                max_attempts=settings.PROVISIONING_MAX_ATTEMPTS, fresh=True,
            )
        except state.ClaimDenied:
            raise AppError(ErrorCode.STATE_CONFLICT, f"Job {run.job_id} cannot be started now.") from None
        from_status = job.status
        await jobs.mark_running(
            job, now=now, lease_expires_at=now + timedelta(seconds=settings.PROVISIONING_LEASE_SECONDS)
        )
        attempt = job.attempt_count
        await _audit(
            users, event="started", from_status=from_status, to_status=state.RUNNING, attempt=attempt,
            at=now, ip_address=run.ip_address, actor_id=run.actor_id, job_id=run.job_id, clan_id=run.clan_id,
        )
        await db.commit()
    return JobRun(**{**run.__dict__, "attempt": attempt})


# ----- the Firebase step: no database transaction is open -----


async def _firebase_step(provider: IdentityProvider, run: JobRun, password: str) -> None:
    """Make sure the Firebase user own-<job_id> exists and holds `password`. The e-mail and the uid are
    never used to look up or delete anything but this job's own user."""
    try:
        existing = await provider.get_user(run.uid)
        if existing is not None:
            if (existing.email or "").lower() != run.email.lower():
                raise _StepFailed(FAILURES["UID_MISMATCH"])
            await provider.set_owner_password(run.uid, password)  # ours (an earlier attempt): a new password
            return
        try:
            await provider.create_user(
                uid=run.uid, email=run.email, display_name=run.display_name, password=password
            )
        except ProviderUserExists:  # a parallel run of this same job got there first: it is ours
            await provider.set_owner_password(run.uid, password)
    except (ProviderUnavailable, ProviderUserNotFound):  # gone between get_user and the password: try again
        raise _StepFailed(FAILURES["PROVIDER_UNAVAILABLE"]) from None
    except PasswordRejected:
        raise _StepFailed(FAILURES["PASSWORD_POLICY_REJECTED"]) from None
    except ProviderEmailTaken:
        raise _StepFailed(FAILURES["PROVIDER_EMAIL_TAKEN"]) from None
    except ProviderInvalidUser:
        raise _StepFailed(FAILURES["PROVIDER_REJECTED_USER"]) from None
    except UnsafeUid:
        raise _StepFailed(FAILURES["INTERNAL_ERROR"]) from None


# ----- T3 and T4: short transactions after Firebase -----


async def _phase(db: UnitOfWork, work: Callable[[], Awaitable], classify: Callable[[IntegrityError], Failure | None] | None = None):
    """Run one database transaction of the job. A database outage is a temporary failure of the JOB
    (recorded afterwards); a lost lease is _LostLease; anything unexpected is rolled back and re-raised."""
    try:
        return await work()
    except OperationalError:
        await rollback_quietly(db)
        raise _StepFailed(FAILURES["DATABASE_UNAVAILABLE"]) from None
    except IntegrityError as exc:
        await rollback_quietly(db)
        failure = classify(exc) if classify else None
        if failure is None:
            logger.error("owner.provision unexpected integrity error constraint=%s request_id=%s",
                         constraint_name(exc), get_request_id())
            raise _StepFailed(FAILURES["INTERNAL_ERROR"]) from None
        raise _StepFailed(failure) from None
    except BaseException:
        await rollback_quietly(db)
        raise


def _classify_finish(exc: IntegrityError) -> Failure | None:
    name = constraint_name(exc) or ""
    if name in USER_EMAIL_CONSTRAINTS:
        return FAILURES["OWNER_EMAIL_EXISTS"]
    if name == ACTIVE_OWNER_INDEX:
        return FAILURES["CLAN_STATE_CHANGED"]
    return None


async def _mark_created(*, db, idempotency, jobs, run: JobRun, clock) -> None:
    async def work():
        await idempotency.set_lock_timeout(LOCK_TIMEOUT_SECONDS)
        job = await jobs.lock(run.job_id)
        if not state.holds_attempt(job, run.attempt):
            raise _LostLease()
        now = clock()
        await jobs.mark_firebase_user_created(
            job, now=now, lease_expires_at=now + timedelta(seconds=settings.PROVISIONING_LEASE_SECONDS)
        )
        await db.commit()

    await _phase(db, work)


async def _finish(*, db, users, family, jobs, idempotency, run: JobRun, clock):
    async def work():
        await idempotency.set_lock_timeout(LOCK_TIMEOUT_SECONDS)
        # lock order: the idempotency row, the clan, the job
        key_row = await _lock_key(idempotency, run.job_id)
        clan = await family.lock_clan(run.clan_id)
        job = await jobs.lock(run.job_id)
        if not state.holds_attempt(job, run.attempt):
            raise _LostLease()
        if clan is None or clan.status != "PENDING" or await family.get_active_owner(run.clan_id) is not None:
            raise _StepFailed(FAILURES["CLAN_STATE_CHANGED"])
        role = await users.get_role_by_code(BUSINESS_OWNER_ROLE)
        if role is None:
            logger.error("owner.provision role %s is missing request_id=%s", BUSINESS_OWNER_ROLE, get_request_id())
            raise _StepFailed(FAILURES["INTERNAL_ERROR"])

        now = clock()
        expires_at = now + timedelta(hours=settings.OWNER_TEMP_PASSWORD_TTL_HOURS)
        user_id = uuid.uuid4()
        await users.create_user_account(
            user_id=user_id, firebase_uid=run.uid, email=run.email, display_name=run.display_name,
            phone=job.phone, status="PENDING", first_login_required=True, now=now,
        )
        cred = await users.add_credential_metadata(user_id, now=now)
        cred.must_change_password = True
        cred.temporary_password_issued_at = now
        cred.temporary_password_expires_at = expires_at
        cred.updated_at = now
        await family.create_membership(clan_id=run.clan_id, user_id=user_id, status="ACTIVE", now=now)
        await users.add_clan_role(
            user_id=user_id, role_id=role.role_id, clan_id=run.clan_id, granted_by=run.actor_id, now=now
        )
        await family.create_ownership(clan_id=run.clan_id, user_id=user_id, now=now)
        await jobs.finish_succeeded(job, user_id=user_id, now=now)
        await _audit(
            users, event="succeeded", from_status=state.RUNNING, to_status=state.SUCCEEDED,
            attempt=run.attempt, at=now, ip_address=run.ip_address, actor_id=run.actor_id,
            job_id=run.job_id, clan_id=run.clan_id, user_id=user_id,
        )
        if key_row is not None and key_row.status == "IN_PROGRESS":  # never holds the password nor personal data
            await complete_idempotency(
                idempotency, key_row, response_status=201,
                response_body={
                    "job_id": str(run.job_id), "status": state.SUCCEEDED,
                    "clan_id": str(run.clan_id), "user_id": str(user_id),
                },
                resource_type=JOB_RESOURCE, resource_id=run.job_id,
            )
        await db.commit()
        return user_id, now, expires_at

    return await _phase(db, work, _classify_finish)


async def _send(sender: EmailSender, run: JobRun, password: str, expires_at: datetime) -> EmailDeliveryResult:
    """After the commit. A failure to send never undoes the Owner: the job is SUCCEEDED."""
    try:
        return await sender.send_owner_temporary_password(
            to_email=run.email, display_name=run.display_name, temporary_password=password,
            expires_at=expires_at,
        )
    except Exception:  # noqa: BLE001 - nothing about the message or the password is logged
        logger.warning("owner.provision email_failed job_id=%s request_id=%s", run.job_id, get_request_id())
        return EmailDeliveryResult(status="FAILED")


# ----- failure: record it, then compensate -----


async def _record_failure(
    *, db, users, jobs, idempotency, provider, run: JobRun, failure: Failure, clock
) -> AppError:
    """Record the failure on the job and return the error to raise.

    A temporary failure leaves FAILED_RETRYABLE (until attempt_count reaches the maximum, which makes it
    final). A final failure first COMMITS FAILED + needs_cleanup + firebase_user_created, and only then
    tries to delete Firebase user own-<job_id>; the flags come down once the delete is confirmed.
    A final failure that must not compensate (UID_MISMATCH) is FAILED with needs_cleanup false and no
    Firebase call at all."""
    final = (not failure.retryable) or state.exhausted(run.attempt, settings.PROVISIONING_MAX_ATTEMPTS)
    exhausted = final and failure.retryable
    compensate = final and failure.compensate
    try:
        now = clock()
        async with rollback_on_error(db):
            await idempotency.set_lock_timeout(LOCK_TIMEOUT_SECONDS)
            key_row = await _lock_key(idempotency, run.job_id)
            job = await jobs.lock(run.job_id)
            if not state.holds_attempt(job, run.attempt):
                await rollback_quietly(db)  # change nothing, let go of the locks
                return _lost_lease_error()  # someone else owns the job now
            if compensate:
                await jobs.finish_failed_needing_cleanup(job, error_code=failure.code, now=now)
            elif final:
                await jobs.finish_failed(job, error_code=failure.code, now=now)  # left untouched at Firebase
            else:
                await jobs.finish_retryable(job, error_code=failure.code, now=now)
            if key_row is not None and key_row.status == "IN_PROGRESS" and key_row.resource_id == run.job_id:
                await idempotency.delete(key_row)  # a failure is not stored: the key is free again
            await _audit(
                users, event="failed" if final else "failed_retryable", from_status=state.RUNNING,
                to_status=state.FAILED if final else state.FAILED_RETRYABLE, attempt=run.attempt, at=now,
                ip_address=run.ip_address, actor_id=run.actor_id, job_id=run.job_id, clan_id=run.clan_id,
                error_code=failure.code, needs_cleanup=compensate,
            )
            await db.commit()
    except Exception:  # noqa: BLE001 - the job stays RUNNING until its lease runs out; a retry resolves it
        logger.error("owner.provision failure_not_recorded job_id=%s code=%s request_id=%s",
                     run.job_id, failure.code, get_request_id())
        return _error(failure, run.job_id)
    if compensate:
        await _cleanup(db=db, users=users, jobs=jobs, idempotency=idempotency, provider=provider, run=run, clock=clock)
    return _error(failure, run.job_id, exhausted=exhausted, attempts=run.attempt)


async def _cleanup(*, db, users, jobs, idempotency, provider, run: JobRun, clock) -> None:
    """Delete Firebase user own-<job_id> (only that uid), then lower the flags once it is confirmed.
    The caller that needs the outcome re-reads the job."""
    confirmed = False
    try:
        await provider.delete_user(run.uid)  # True (deleted) or False (there was none): both are confirmed
        confirmed = True
    except (ProviderUnavailable, ProviderInvalidUser, UnsafeUid):
        confirmed = False
    try:
        now = clock()
        async with rollback_on_error(db):
            await idempotency.set_lock_timeout(LOCK_TIMEOUT_SECONDS)
            job = await jobs.lock(run.job_id)
            if job is None or job.status != state.FAILED or not job.needs_cleanup or job.attempt_count != run.attempt:
                return
            if confirmed:
                await jobs.finish_cleanup(job, now=now)
            await _audit(
                users, event="cleanup_done" if confirmed else "cleanup_failed", from_status=state.FAILED,
                to_status=state.FAILED, attempt=run.attempt, at=now, ip_address=run.ip_address,
                actor_id=run.actor_id, job_id=run.job_id, clan_id=run.clan_id,
                error_code=job.error_code, needs_cleanup=not confirmed,
            )
            await db.commit()
    except Exception:  # noqa: BLE001 - the flags stay up: a clean-up retry deletes again (not found is fine)
        logger.error("owner.provision cleanup_not_recorded job_id=%s request_id=%s", run.job_id, get_request_id())


# ----- GET /admin/provisioning-jobs/{job_id} and the list -----


def _job_response(job) -> ProvisioningJobResponse:
    """The job as the SA sees it: never the e-mail, the phone, the Firebase uid or a password."""
    return ProvisioningJobResponse(
        job_id=job.job_id,
        job_type=job.job_type,
        clan_id=job.clan_id,
        status=job.status,
        user_id=job.user_id,
        email_delivery_status=None,
        attempt_count=job.attempt_count,
        needs_cleanup=job.needs_cleanup,
        error_code=job.error_code,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


async def get_job(*, jobs: ProvisioningRepository, job_id: uuid.UUID) -> ProvisioningJobResponse:
    job = await jobs.get(job_id)
    if job is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return _job_response(job)


async def list_jobs(*, jobs: ProvisioningRepository, query: ProvisioningJobListQuery) -> Page[ProvisioningJobResponse]:
    rows = await jobs.list_page(
        clan_id=query.clan_id, status=query.status, limit=query.page_size, offset=query.offset
    )
    total = await jobs.count(clan_id=query.clan_id, status=query.status)
    return Page[ProvisioningJobResponse](
        items=[_job_response(row) for row in rows], total=total, page=query.page, page_size=query.page_size
    )


# ----- why a job cannot be retried or abandoned now -----

_DENIED_BECAUSE = {
    "ALREADY_SUCCEEDED": "it already succeeded",
    "FAILED_FINAL": "it failed for good and nothing is owed to the identity provider",
    "CLEANUP_PENDING": "it still owes a clean-up at the identity provider: retry it to finish the clean-up",
    "PENDING_NOT_STUCK": "it was created moments ago and its request may still be starting it",
    "LEASE_HELD": "a run is working on it and its lease has not run out",
    "ATTEMPTS_EXHAUSTED": "it used all its attempts: abandon it",
    "UNKNOWN_STATUS": "its status is not known",
}


def _denied_error(job_id: uuid.UUID, status: str, denied: state.ClaimDenied, what: str) -> AppError:
    """409 that names the CURRENT status (and Retry-After when waiting helps)."""
    because = _DENIED_BECAUSE.get(denied.reason, denied.reason)
    headers = {"Retry-After": str(denied.retry_after)} if denied.retry_after else None
    return AppError(
        ErrorCode.STATE_CONFLICT, f"Job {job_id} is {status} and cannot be {what} now: {because}.", headers=headers
    )


# ----- POST /admin/provisioning-jobs/{job_id}/retry -----


@dataclass(frozen=True)
class _Claimed:
    run: JobRun
    cleanup_only: bool


async def retry_job(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    family: FamilyRepository,
    jobs: ProvisioningRepository,
    idempotency: IdempotencyStore,
    provider: IdentityProvider,
    sender: EmailSender,
    principal: Principal,
    job_id: uuid.UUID,
    client: ClientInfo,
    clock: Callable[[], datetime] | None = None,
    password_factory: Callable[[], str] | None = None,
) -> ProvisionResult:
    """Run the job again. 200 with a NEW temporary password (shown once) when it succeeds; when the job
    only owes a Firebase clean-up, the clean-up is done and no password is made. Every other state is 409."""
    if not provider.admin_api_enabled:
        raise AppError(ErrorCode.PROVIDER_UNAVAILABLE)  # nothing written
    clock = clock or (lambda: utcnow())
    claimed = await _claim_retry(
        db=db, users=users, family=family, jobs=jobs, idempotency=idempotency, principal=principal,
        job_id=job_id, client=client, clock=clock,
    )
    run = claimed.run
    if claimed.cleanup_only:
        await _cleanup(db=db, users=users, jobs=jobs, idempotency=idempotency, provider=provider, run=run, clock=clock)
        job = await jobs.get(job_id)  # re-read: another request may have finished the clean-up
        if job is None or job.needs_cleanup:
            raise AppError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                f"The clean-up of job {job_id} could not be confirmed at the identity provider; try again.",
            )
        return ProvisionResult(
            status=200,
            replayed=False,
            response=OwnerProvisionResponse(job_id=job_id, status=job.status, clan_id=job.clan_id),
        )
    return await _execute(
        db=db, users=users, family=family, jobs=jobs, idempotency=idempotency, provider=provider,
        sender=sender, run=run, clock=clock, password_factory=password_factory, status=200,
    )


async def _claim_retry(*, db, users, family, jobs, idempotency, principal, job_id, client, clock) -> _Claimed:
    """One short transaction: lock the clan, then the job; decide; and (unless it is only a clean-up) make
    the job RUNNING with a new attempt and a new lease. Same fencing as a first run."""
    now = clock()
    async with rollback_on_error(db):
        await idempotency.set_lock_timeout(LOCK_TIMEOUT_SECONDS)
        known = await jobs.get(job_id)
        if known is None:
            raise AppError(ErrorCode.NOT_FOUND)
        clan = await family.lock_clan(known.clan_id)  # lock order: clan, job
        job = await jobs.lock(job_id)
        if job is None:
            raise AppError(ErrorCode.NOT_FOUND)
        try:
            action = state.decide_claim(
                job, now, lease_seconds=settings.PROVISIONING_LEASE_SECONDS,
                max_attempts=settings.PROVISIONING_MAX_ATTEMPTS,
            )
        except state.ClaimDenied as denied:
            raise _denied_error(job_id, job.status, denied, "retried") from None
        run = JobRun(
            job_id=job_id, clan_id=job.clan_id, attempt=job.attempt_count, email=job.email,
            display_name=job.display_name, uid=job.firebase_uid, actor_id=principal.user_id,
            ip_address=client.ip_address,
        )
        if action == state.CLEANUP_ONLY:
            await db.commit()  # nothing changed: let go of the locks
            return _Claimed(run, cleanup_only=True)
        # a run is about to begin: the clan and the e-mail must still allow an Owner
        if clan is None or clan.status != "PENDING":
            raise AppError(
                ErrorCode.STATE_CONFLICT,
                f"The clan is {clan.status if clan else 'gone'}; job {job_id} cannot create an Owner now: abandon it.",
            )
        if await family.get_active_owner(job.clan_id) is not None:
            raise AppError(ErrorCode.STATE_CONFLICT, "This clan already has an Owner: abandon the job.")
        if await users.get_user_by_email_ci(job.email) is not None:
            raise AppError(
                ErrorCode.DUPLICATE_RESOURCE, "An account with this e-mail address already exists: abandon the job."
            )
        from_status = job.status
        await jobs.mark_running(
            job, now=now, lease_expires_at=now + timedelta(seconds=settings.PROVISIONING_LEASE_SECONDS)
        )
        attempt = job.attempt_count
        await _audit(
            users, event="retried", from_status=from_status, to_status=state.RUNNING, attempt=attempt,
            at=now, ip_address=client.ip_address, actor_id=principal.user_id, job_id=job_id, clan_id=run.clan_id,
        )
        await db.commit()
    return _Claimed(JobRun(**{**run.__dict__, "attempt": attempt}), cleanup_only=False)


# ----- POST /admin/provisioning-jobs/{job_id}/abandon -----

ABANDONED = "ABANDONED"


async def abandon_job(
    *,
    db: UnitOfWork,
    users: UserAccessRepository,
    jobs: ProvisioningRepository,
    idempotency: IdempotencyStore,
    provider: IdentityProvider,
    principal: Principal,
    job_id: uuid.UUID,
    client: ClientInfo,
    clock: Callable[[], datetime] | None = None,
) -> ProvisioningJobResponse:
    """Give the job up. It becomes FAILED (error_code ABANDONED). When a run ever started (attempt_count > 0)
    the same compensation as a final failure follows: FAILED + needs_cleanup are COMMITTED first, then
    delete_user(own-<job_id>) is tried, then the flags come down. A failed delete leaves them up (the clan and
    the e-mail stay blocked; a retry finishes the clean-up). Not allowed while a run holds a live lease."""
    clock = clock or (lambda: utcnow())
    now = clock()
    async with rollback_on_error(db):
        await idempotency.set_lock_timeout(LOCK_TIMEOUT_SECONDS)
        key_row = await _lock_key(idempotency, job_id)  # lock order: key, job (the clan is not needed)
        job = await jobs.lock(job_id)
        if job is None:
            raise AppError(ErrorCode.NOT_FOUND)
        try:
            state.decide_abandon(job, now, lease_seconds=settings.PROVISIONING_LEASE_SECONDS)
        except state.ClaimDenied as denied:
            raise _denied_error(job_id, job.status, denied, "abandoned") from None
        run = JobRun(
            job_id=job_id, clan_id=job.clan_id, attempt=job.attempt_count, email=job.email,
            display_name=job.display_name, uid=job.firebase_uid, actor_id=principal.user_id,
            ip_address=client.ip_address,
        )
        from_status = job.status
        owes_cleanup = job.attempt_count > 0  # a run ever began: a Firebase user may exist
        if owes_cleanup:
            await jobs.finish_failed_needing_cleanup(job, error_code=ABANDONED, now=now)
        else:
            await jobs.finish_failed(job, error_code=ABANDONED, now=now)
        if key_row is not None and key_row.status == "IN_PROGRESS":
            await idempotency.delete(key_row)  # nothing will ever complete it
        await _audit(
            users, event="abandoned", from_status=from_status, to_status=state.FAILED, attempt=run.attempt,
            at=now, ip_address=client.ip_address, actor_id=principal.user_id, job_id=job_id,
            clan_id=run.clan_id, error_code=ABANDONED, needs_cleanup=owes_cleanup,
        )
        await db.commit()
    if owes_cleanup:
        await _cleanup(db=db, users=users, jobs=jobs, idempotency=idempotency, provider=provider, run=run, clock=clock)
    job = await jobs.get(job_id)
    if job is None:  # pragma: no cover - rows are never deleted
        raise AppError(ErrorCode.NOT_FOUND)
    return _job_response(job)
