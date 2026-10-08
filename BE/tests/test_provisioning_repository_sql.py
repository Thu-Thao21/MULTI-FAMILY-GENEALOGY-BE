"""The real SQL and field writes of the E6a repository methods, compiled without a database: the job
repository, lock_clan, the membership and ownership writes, the user account writes and the idempotency
release. The same methods run on PostgreSQL in the integration tests."""

from __future__ import annotations

import inspect
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.family.entities import IdempotencyKey, ProvisioningJob
from app.models.family.idempotency_repository import IdempotencyRepository
from app.models.family.provisioning_repository import ProvisioningRepository
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from tests.test_public_repository_sql import RecordingSession, compiled

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(seconds=90)
CLAN, USER, SA = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


@pytest.fixture
def session() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def jobs(session) -> ProvisioningRepository:
    return ProvisioningRepository(session)


def a_job(**kw) -> ProvisioningJob:
    job_id = kw.pop("job_id", uuid.uuid4())
    values = dict(job_id=job_id, clan_id=CLAN, status="RUNNING", email="o@example.test", display_name="O",
                  firebase_uid=f"own-{job_id}", firebase_user_created=False, needs_cleanup=False, attempt_count=1,
                  lease_expires_at=LATER, error_code=None, created_at=NOW, updated_at=NOW)
    values.update(kw)
    return ProvisioningJob(**values)


# ------------------------------------------------------------------ job statements


async def test_a_new_job_is_pending_and_its_firebase_uid_is_own_plus_its_id(jobs, session):
    job_id = uuid.uuid4()
    job = await jobs.insert_pending(job_id=job_id, clan_id=CLAN, requested_by=SA, email="Owner@Example.TEST",
                                    display_name="Owner", phone=None, now=NOW)
    assert (job.status, job.firebase_uid, job.attempt_count, job.firebase_user_created, job.needs_cleanup) == (
        "PENDING", f"own-{job_id}", 0, False, False)
    assert (job.email, job.requested_by, job.job_type, job.lease_expires_at) == ("Owner@Example.TEST", SA, "OWNER_PROVISIONING", None)
    assert session.added == [job] and session.flushes == 1


async def test_the_job_lock_is_for_no_key_update_and_rereads_the_row(jobs, session):
    await jobs.lock(uuid.uuid4())
    sql, _ = compiled(session)
    assert sql.endswith("FOR NO KEY UPDATE") and "FOR UPDATE" not in sql.replace("FOR NO KEY UPDATE", "")
    assert session.statements[0].get_execution_options().get("populate_existing") is True
    assert "provisioning_jobs.job_id = " in sql.split("WHERE", 1)[1] and "JOIN" not in sql and not re.search(r"\busers\b", sql)


async def test_a_plain_read_takes_no_lock(jobs, session):
    await jobs.get(uuid.uuid4())
    sql, _ = compiled(session)
    assert "FOR " not in sql and "provisioning_jobs.job_id = " in sql


async def test_the_blocking_query_looks_at_the_clan_and_the_email_in_any_case(jobs, session):
    await jobs.list_blocking(clan_id=CLAN, email="Owner@Example.TEST")
    sql, params = compiled(session)
    where = sql.split("WHERE", 1)[1].split("ORDER BY", 1)[0]
    assert "provisioning_jobs.clan_id = " in where and "lower(provisioning_jobs.email) = " in where
    assert "provisioning_jobs.needs_cleanup IS true" in where.replace("= true", "IS true") or "needs_cleanup" in where
    assert "owner@example.test" in params.values() and "Owner@Example.TEST" not in params.values()  # lower-cased for the comparison
    assert "ORDER BY provisioning_jobs.created_at, provisioning_jobs.job_id" in sql
    assert "FOR " not in sql


async def test_the_blocking_statuses_are_the_live_ones_and_a_succeeded_job_of_the_clan(jobs, session):
    await jobs.list_blocking(clan_id=CLAN, email="o@example.test")
    _, params = compiled(session)
    flat = [p for v in params.values() for p in (v if isinstance(v, (list, tuple)) else [v])]
    for status in ("PENDING", "RUNNING", "FAILED_RETRYABLE", "SUCCEEDED"):
        assert status in flat, status
    assert "FAILED" not in flat  # a FAILED job without a pending clean-up blocks nothing


# ------------------------------------------------------------------ transitions


async def test_mark_running_counts_the_attempt_and_sets_the_lease(jobs, session):
    job = a_job(status="PENDING", attempt_count=0, lease_expires_at=None, error_code="OLD")
    await jobs.mark_running(job, now=NOW, lease_expires_at=LATER)
    assert (job.status, job.attempt_count, job.lease_expires_at, job.error_code, job.updated_at) == ("RUNNING", 1, LATER, None, NOW)
    await jobs.mark_running(job, now=NOW, lease_expires_at=LATER)
    assert job.attempt_count == 2


async def test_firebase_user_created_is_a_heartbeat_too(jobs):
    job = a_job()
    await jobs.mark_firebase_user_created(job, now=NOW, lease_expires_at=LATER + timedelta(seconds=5))
    assert (job.firebase_user_created, job.lease_expires_at, job.status) == (True, LATER + timedelta(seconds=5), "RUNNING")


async def test_success_closes_the_job_and_clears_the_lease_and_the_error(jobs):
    job = a_job(error_code="PROVIDER_UNAVAILABLE", firebase_user_created=True)
    await jobs.finish_succeeded(job, user_id=USER, now=NOW)
    assert (job.status, job.user_id, job.lease_expires_at, job.error_code, job.needs_cleanup, job.completed_at) == (
        "SUCCEEDED", USER, None, None, False, NOW)


async def test_a_temporary_failure_keeps_the_user_flag_and_drops_the_lease(jobs):
    job = a_job(firebase_user_created=True)
    await jobs.finish_retryable(job, error_code="DATABASE_UNAVAILABLE", now=NOW)
    assert (job.status, job.error_code, job.lease_expires_at, job.needs_cleanup, job.firebase_user_created) == (
        "FAILED_RETRYABLE", "DATABASE_UNAVAILABLE", None, False, True)


async def test_a_final_failure_raises_both_cleanup_flags_together_because_the_check_ties_them(jobs):
    job = a_job(firebase_user_created=False)  # we may not know whether the user exists
    await jobs.finish_failed_needing_cleanup(job, error_code="PROVIDER_EMAIL_TAKEN", now=NOW)
    assert (job.status, job.needs_cleanup, job.firebase_user_created, job.lease_expires_at, job.completed_at) == (
        "FAILED", True, True, None, NOW)
    # provisioning_jobs_needs_cleanup_check: needs_cleanup only when FAILED and firebase_user_created
    assert (not job.needs_cleanup) or (job.status == "FAILED" and job.firebase_user_created)


async def test_a_final_failure_without_cleanup_leaves_the_flags_down_and_the_user_flag_as_it_was(jobs):
    for created in (False, True):
        job = a_job(firebase_user_created=created)
        await jobs.finish_failed(job, error_code="UID_MISMATCH", now=NOW)
        assert (job.status, job.needs_cleanup, job.firebase_user_created, job.lease_expires_at, job.error_code, job.completed_at) == (
            "FAILED", False, created, None, "UID_MISMATCH", NOW)


async def test_a_confirmed_cleanup_lowers_both_flags_and_leaves_the_job_failed(jobs):
    job = a_job(status="FAILED", needs_cleanup=True, firebase_user_created=True, lease_expires_at=None)
    await jobs.finish_cleanup(job, now=NOW)
    assert (job.status, job.needs_cleanup, job.firebase_user_created) == ("FAILED", False, False)


def test_the_job_repository_never_commits_and_every_write_only_flushes():
    for name, member in inspect.getmembers(ProvisioningRepository, inspect.iscoroutinefunction):
        assert not re.search(r"\.(commit|rollback)\(", inspect.getsource(member)), name


JOB_SCOPE = {
    "insert_pending": "inserts a row; clan_id is the inserted value",
    "get": "WHERE job_id",
    "lock": "WHERE job_id, FOR NO KEY UPDATE",
    "list_blocking": "WHERE clan_id OR lower(email), only blocking rows",
    "mark_running": "writes the row it was given (locked by lock)",
    "mark_firebase_user_created": "writes the row it was given",
    "finish_succeeded": "writes the row it was given",
    "finish_retryable": "writes the row it was given",
    "finish_failed_needing_cleanup": "writes the row it was given",
    "finish_failed": "writes the row it was given",
    "finish_cleanup": "writes the row it was given",
}


def test_every_job_method_is_accounted_for():
    methods = {n for n, _ in inspect.getmembers(ProvisioningRepository, inspect.iscoroutinefunction) if not n.startswith("_")}
    assert methods == set(JOB_SCOPE)


# ------------------------------------------------------------------ the clan lock, membership, ownership


async def test_lock_clan_is_for_no_key_update_and_reads_one_table(session):
    await FamilyRepository(session).lock_clan(CLAN)
    sql, _ = compiled(session)
    assert sql.endswith("FOR NO KEY UPDATE") and "clans.clan_id = " in sql.split("WHERE", 1)[1] and "JOIN" not in sql
    assert session.statements[0].get_execution_options().get("populate_existing") is True


async def test_a_membership_and_an_ownership_are_written_open_and_only_flushed(session):
    family = FamilyRepository(session)
    membership = await family.create_membership(clan_id=CLAN, user_id=USER, status="ACTIVE", now=NOW)
    owner = await family.create_ownership(clan_id=CLAN, user_id=USER, now=NOW)
    assert (membership.clan_id, membership.user_id, membership.status, membership.joined_at, membership.revoked_at) == (CLAN, USER, "ACTIVE", NOW, None)
    assert (owner.clan_id, owner.user_id, owner.started_at, owner.ended_at, owner.transfer_id) == (CLAN, USER, NOW, None, None)
    assert session.flushes == 2 and session.statements == []


def test_the_new_family_methods_never_commit():
    for name in ("lock_clan", "create_membership", "create_ownership"):
        assert not re.search(r"\.(commit|rollback)\(", inspect.getsource(getattr(FamilyRepository, name))), name


# ------------------------------------------------------------------ the user account


async def test_the_account_is_stored_with_the_email_exactly_as_given(session):
    user = await UserAccessRepository(session).create_user_account(
        user_id=USER, firebase_uid="own-x", email="Owner.Mixed@Example.TEST", display_name="Owner", phone=None,
        status="PENDING", first_login_required=True, now=NOW)
    assert (user.email, user.status, user.first_login_required, user.email_verified, user.firebase_uid) == (
        "Owner.Mixed@Example.TEST", "PENDING", True, False, "own-x")
    assert session.added == [user] and session.flushes == 1


async def test_the_email_lookup_compares_lower_case_on_both_sides(session):
    await UserAccessRepository(session).get_user_by_email_ci("Owner.Mixed@Example.TEST")
    sql, params = compiled(session)
    assert "lower(users.email) = " in sql and "owner.mixed@example.test" in params.values()


# ------------------------------------------------------------------ releasing an idempotency key


async def test_releasing_a_key_deletes_that_row_and_naming_its_resource_only_writes_it(session):
    repo = IdempotencyRepository(session)
    row = IdempotencyKey(idempotency_id=uuid.uuid4(), actor_id=SA, endpoint="e", idempotency_key="k" * 8, request_hash="a" * 64,
                         status="IN_PROGRESS", created_at=NOW, expires_at=NOW)
    job = uuid.uuid4()
    await repo.set_resource(row, resource_type="provisioning_job", resource_id=job)
    assert (row.resource_type, row.resource_id) == ("provisioning_job", job)
    deleted = []

    async def fake_delete(obj):
        deleted.append(obj)

    session.delete = fake_delete
    await repo.delete(row)
    assert deleted == [row] and session.flushes == 2
