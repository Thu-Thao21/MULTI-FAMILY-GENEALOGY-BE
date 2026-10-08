"""Retry, abandon and reset under real concurrency (Mốc E6b), with a FAKE Firebase. COMMITS real rows.

Data uses the itest-conc-op- prefix (users itest-conc-op-*, Owner e-mails itest-conc-op-owner-*, clan codes
ITESTOP-*) and is deleted in finally: the Owners' sessions first (no cascade), then the audit rows, the clans
(their jobs, memberships, roles and ownership cascade) and the users (credentials and idempotency rows
cascade). The matching of e-mails ignores the letter case and the last check of the session proves that no
user of ours was left behind. The DEV-* plans seeded on the dev branch are never read, changed or deleted.

What is protected, and by what:
  * the same Idempotency-Key at the same instant, and two keys for one clan (the E6a guarantees, with a retry
    and an abandon after them changing nothing);
  * two retries of one job: the clan and job row locks leave exactly one run;
  * a lease that ran out is taken over (attempt_count moves on) and the old run writes nothing, while the
    retry completes the ORIGINAL key through the job;
  * creating the Owner races a reset: a reset never waits for a job that is inside Firebase, and answers 409
    until the Owner exists; a second Owner request during a reset is a 409 that does not wait either;
  * two resets at the same instant, both already past Firebase: one wins, the other is a 409 that wrote nothing;
  * a retry that dies, a reset that dies: nothing blocks and a later call works;
  * NO lock is held while the identity provider is called: from inside the call, another session takes the
    clan, job, key, credential and user rows with FOR UPDATE NOWAIT;
  * the flags of an abandon are COMMITTED before the delete: from inside delete_user another session sees them.

A non-application error is reported by describe_error() with its SQLSTATE; there is no retry anywhere."""

from __future__ import annotations

import asyncio
import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.controllers.family_management import owner_password_reset_use_cases as reset_use_cases
from app.controllers.family_management import owner_provisioning_use_cases as use_cases
from app.core.email_sender import NoopEmailSender
from app.core.errors import AppError
from app.core.firebase import ProviderUnavailable
from app.db.postgres import make_engine
from app.models.family.idempotency_repository import IdempotencyRepository
from app.models.family.provisioning_repository import ProvisioningRepository
from app.models.family.repository import FamilyRepository
from app.models.user_access.entities import AuditLog, CredentialMetadata, User, UserSession
from app.models.user_access.repository import UserAccessRepository
from tests.fakes import FakeIdentityProvider
from tests.integration.diagnostics import describe_error
from tests.integration.test_owner_provisioning_concurrency import (
    CLIENT,
    Crash,
    dev_plan_count,
    email,
    keys_of,
    make_clans,
    make_sas,
    no_errors,
    purge as purge_users_and_clans,
    run_owner,
    state,
    within,
    USER_PREFIX,
)

pytestmark = pytest.mark.concurrency

PASSWORDS = [f"Kq7Wm2Xp9Tr4Vz8{c}" for c in "NPQRSTUVWXYZ"]


@pytest_asyncio.fixture(loop_scope="session")
async def arena(monkeypatch):
    from app.core.config import settings

    engine = make_engine(settings.DATABASE_URL, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    counter = itertools.count()
    monkeypatch.setattr(use_cases, "_default_password", lambda: PASSWORDS[next(counter) % len(PASSWORDS)])

    async def purge(s) -> None:
        ids = list((await s.execute(select(User.user_id).where(
            User.firebase_uid.startswith(USER_PREFIX) | func.lower(User.email).startswith(USER_PREFIX)))).scalars())
        if ids:
            await s.execute(delete(UserSession).where(UserSession.user_id.in_(ids)))  # no cascade on sessions
        await purge_users_and_clans(s)

    try:
        async with maker() as s, s.begin():
            await purge(s)
        dev_before = await dev_plan_count(maker)
        yield maker
        assert await dev_plan_count(maker) == dev_before
    finally:
        async with maker() as s, s.begin():
            await purge(s)
        async with maker() as s:
            left = (await s.execute(select(func.count()).select_from(User).where(
                func.lower(User.email).startswith(USER_PREFIX) | User.firebase_uid.startswith(USER_PREFIX)))).scalar_one()
            sessions = (await s.execute(text(
                "SELECT count(*) FROM user_sessions WHERE user_id NOT IN (SELECT user_id FROM users)"))).scalar_one()
        await engine.dispose()
        assert left == 0 and sessions == 0, "the concurrency tests left users or sessions behind"


# ------------------------------------------------------------------ one request each


async def _call(maker, work):
    async with maker() as s:
        await s.connection()
        try:
            return await work(s)
        except AppError as exc:
            return str(exc.code)
        except Crash:
            return "CRASH"
        except Exception as exc:  # noqa: BLE001 - a driver error here is exactly what must not happen
            return describe_error(exc)


async def run_retry(maker, provider, principal, job_id, *, start=None):
    async def work(s):
        if start is not None:
            await start.wait()
        result = await use_cases.retry_job(
            db=s, users=UserAccessRepository(s), family=FamilyRepository(s), jobs=ProvisioningRepository(s),
            idempotency=IdempotencyRepository(s), provider=provider, sender=NoopEmailSender(), principal=principal,
            job_id=job_id, client=CLIENT)
        return str(result.status)

    return await _call(maker, work)


async def run_abandon(maker, provider, principal, job_id, *, start=None):
    async def work(s):
        if start is not None:
            await start.wait()
        await use_cases.abandon_job(
            db=s, users=UserAccessRepository(s), jobs=ProvisioningRepository(s), idempotency=IdempotencyRepository(s),
            provider=provider, principal=principal, job_id=job_id, client=CLIENT)
        return "200"

    return await _call(maker, work)


async def run_reset(maker, provider, principal, clan_id, *, start=None):
    async def work(s):
        if start is not None:
            await start.wait()
        await reset_use_cases.reset_owner_password(
            db=s, users=UserAccessRepository(s), family=FamilyRepository(s), idempotency=IdempotencyRepository(s),
            provider=provider, sender=NoopEmailSender(), principal=principal, clan_id=clan_id, client=CLIENT)
        return "200"

    return await _call(maker, work)


async def failed_job(maker, provider, sa, clan_id, address, key, *, operation="get_user"):
    """The first run fails temporarily: FAILED_RETRYABLE, attempt 1, the key released."""
    provider.faults[operation] = [ProviderUnavailable("timeout")]
    assert await run_owner(maker, provider, sa, clan_id, key, address=address) == "PROVIDER_UNAVAILABLE"
    [job] = (await state(maker, clan_id))["jobs"]
    assert (job.status, job.attempt_count) == ("FAILED_RETRYABLE", 1)
    return job.job_id


async def make_owner(maker, provider, sa, clan_id, address, key, *, sessions=2):
    """A finished Owner (job SUCCEEDED) with `sessions` live sessions. Returns (user_id, job_id)."""
    assert await run_owner(maker, provider, sa, clan_id, key, address=address) == "201"
    [job] = (await state(maker, clan_id))["jobs"]
    async with maker() as s, s.begin():
        users = UserAccessRepository(s)
        for i in range(sessions):
            await users.add_session(
                user_id=job.user_id, token_jti_hash=uuid.uuid4().hex + uuid.uuid4().hex, created_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=8), ip_address=None, user_agent=None)
    return job.user_id, job.job_id


async def cred_and_sessions(maker, user_id):
    async with maker() as s:
        cred = (await s.execute(select(CredentialMetadata).where(CredentialMetadata.user_id == user_id))).scalar_one()
        revoked = [r.revoked_at is not None for r in (await s.execute(select(UserSession).where(UserSession.user_id == user_id))).scalars()]
        audits = (await s.execute(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "clan.owner.temp_password_reset", AuditLog.entity_id == user_id))).scalar_one()
        return cred, revoked, audits


async def set_lease(maker, clan_id, when_sql="now() - interval '1 second'"):
    async with maker() as s, s.begin():
        await s.execute(text(f"UPDATE provisioning_jobs SET lease_expires_at = {when_sql} WHERE clan_id = :c AND status = 'RUNNING'"),
                        {"c": clan_id})


# ------------------------------------------------------------------ the same key, two keys


async def test_the_same_key_at_the_same_instant_then_a_retry_and_an_abandon_of_the_finished_job_change_nothing(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    [sa] = await make_sas(maker, 1)
    provider = FakeIdentityProvider()
    address = email()
    start = asyncio.Barrier(2)
    outcomes = await within(*[run_owner(maker, provider, sa, clan_id, "key-op-e6b-same-key-1", address=address, start=start) for _ in range(2)])
    no_errors(outcomes)
    assert sorted(outcomes) == sorted(["201", "STATE_CONFLICT"]), outcomes
    st = await state(maker, clan_id)
    [job] = st["jobs"]
    assert (job.status, st["owners"], len(provider.provider_users)) == ("SUCCEEDED", 1, 1)
    calls = len(provider.provider_calls)
    assert await run_retry(maker, provider, sa, job.job_id) == "STATE_CONFLICT"
    assert await run_abandon(maker, provider, sa, job.job_id) == "STATE_CONFLICT"
    after = await state(maker, clan_id)
    assert (after["jobs"][0].status, after["jobs"][0].attempt_count, after["owners"]) == ("SUCCEEDED", 1, 1)
    assert len(provider.provider_calls) == calls  # neither touched Firebase


async def test_two_keys_for_one_clan_one_job_and_a_retry_of_it_is_refused(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    start = asyncio.Barrier(2)
    outcomes = await within(run_owner(maker, provider, a, clan_id, "key-op-e6b-two-keys-aaaa", address=email(), start=start),
                            run_owner(maker, provider, b, clan_id, "key-op-e6b-two-keys-bbbb", address=email(), start=start))
    no_errors(outcomes)
    assert sorted(outcomes) == sorted(["201", "STATE_CONFLICT"]), outcomes
    st = await state(maker, clan_id)
    assert len(st["jobs"]) == 1 and st["owners"] == 1
    assert await run_retry(maker, provider, a, st["jobs"][0].job_id) == "STATE_CONFLICT"


# ------------------------------------------------------------------ two retries of one job


async def test_two_retries_of_one_job_at_the_same_instant_exactly_one_runs(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    job_id = await failed_job(maker, provider, a, clan_id, email(), "key-op-e6b-retries-1")
    provider.provider_calls.clear()
    start = asyncio.Barrier(2)
    outcomes = await within(run_retry(maker, provider, a, job_id, start=start), run_retry(maker, provider, b, job_id, start=start))
    no_errors(outcomes)
    assert sorted(outcomes) == sorted(["200", "STATE_CONFLICT"]), outcomes
    st = await state(maker, clan_id)
    [job] = st["jobs"]
    assert (job.status, job.attempt_count, st["owners"], st["memberships"]) == ("SUCCEEDED", 2, 1, 1)
    assert [op for op, _ in provider.provider_calls].count("create_user") == 1 and len(provider.provider_users) == 1


async def test_a_retry_and_an_abandon_at_the_same_instant_leave_one_consistent_end(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    job_id = await failed_job(maker, provider, a, clan_id, email(), "key-op-e6b-race-ab-1")
    start = asyncio.Barrier(2)
    retry_outcome, abandon_outcome = await within(run_retry(maker, provider, a, job_id, start=start),
                                                  run_abandon(maker, provider, b, job_id, start=start))
    no_errors([retry_outcome, abandon_outcome])
    st = await state(maker, clan_id)
    [job] = st["jobs"]
    if job.status == "SUCCEEDED":  # the retry won: the abandon found a live lease or a finished job
        assert (retry_outcome, abandon_outcome, st["owners"]) == ("200", "STATE_CONFLICT", 1)
    else:  # the abandon won: no Owner, nothing left at Firebase, the clan free
        assert (job.status, job.error_code, job.needs_cleanup, st["owners"]) == ("FAILED", "ABANDONED", False, 0)
        # the retry either found a FAILED job with nothing owed (409) or arrived while the clean-up was still
        # owed and did ONLY that clean-up (200, no Owner, no password): both are right
        assert abandon_outcome == "200" and retry_outcome in ("STATE_CONFLICT", "200")
        assert provider.provider_users == {} and job.firebase_user_created is False


# ------------------------------------------------------------------ a lease that ran out


async def test_a_lease_that_ran_out_is_taken_over_the_old_run_writes_nothing_and_the_original_key_is_completed(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    address = email()
    entered, release, seen = asyncio.Event(), asyncio.Event(), {"n": 0}

    async def stall_the_first(uid):
        seen["n"] += 1
        if seen["n"] == 1:  # the first run is stuck inside Firebase
            entered.set()
            await release.wait()

    provider.hooks["get_user"] = stall_the_first
    old = asyncio.create_task(run_owner(maker, provider, a, clan_id, "key-op-e6b-takeover-1", address=address))
    await asyncio.wait_for(entered.wait(), timeout=120)
    [job] = (await state(maker, clan_id))["jobs"]
    assert (job.status, job.attempt_count) == ("RUNNING", 1)
    [key] = await keys_of(maker, a.user_id)
    assert (key.status, key.resource_id) == ("IN_PROGRESS", job.job_id)
    await set_lease(maker, clan_id)  # ... and its lease runs out
    assert await run_retry(maker, provider, b, job.job_id) == "200"
    release.set()
    assert await asyncio.wait_for(old, timeout=240) == "STATE_CONFLICT"  # replaced: it wrote nothing
    st = await state(maker, clan_id)
    [job] = st["jobs"]
    assert (job.status, job.attempt_count, st["owners"], st["memberships"]) == ("SUCCEEDED", 2, 1, 1)
    [key] = await keys_of(maker, a.user_id)  # completed by the RETRY, found through the job, not through the key text
    assert (key.status, key.response_status, key.resource_id) == ("COMPLETED", 201, job.job_id)
    assert set(key.response_body) == {"job_id", "status", "clan_id", "user_id"}
    assert await run_owner(maker, provider, a, clan_id, "key-op-e6b-takeover-1", address=address) == "201R"  # the replay


async def test_a_retry_that_dies_leaves_the_job_running_and_nothing_blocks_until_the_lease_runs_out_then_abandon_frees_the_clan(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    address = email()
    job_id = await failed_job(maker, provider, a, clan_id, address, "key-op-e6b-dies-1")

    async def die(uid):
        raise Crash()

    provider.hooks["create_user"] = die
    assert await run_retry(maker, provider, b, job_id) == "CRASH"
    provider.hooks.clear()
    [job] = (await state(maker, clan_id))["jobs"]
    assert (job.status, job.attempt_count) == ("RUNNING", 2) and job.lease_expires_at is not None
    results = await within(run_retry(maker, provider, a, job_id), run_abandon(maker, provider, a, job_id),
                           run_owner(maker, provider, a, clan_id, "key-op-e6b-dies-2", address=address))
    assert results == ["STATE_CONFLICT"] * 3  # a live lease: none waits, none hangs
    await set_lease(maker, clan_id)
    assert await run_abandon(maker, provider, b, job_id) == "200"
    [job] = (await state(maker, clan_id))["jobs"]
    assert (job.status, job.error_code, job.needs_cleanup) == ("FAILED", "ABANDONED", False)
    assert await run_owner(maker, provider, a, clan_id, "key-op-e6b-dies-3", address=address) == "201"


# ------------------------------------------------------------------ creating the Owner races a reset


async def test_a_reset_does_not_wait_for_a_job_inside_firebase_and_is_409_until_the_owner_exists(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    entered, release = asyncio.Event(), asyncio.Event()

    async def stall(uid):
        entered.set()
        await release.wait()

    provider.hooks["create_user"] = stall
    creating = asyncio.create_task(run_owner(maker, provider, a, clan_id, "key-op-e6b-vs-reset-1", address=email()))
    await asyncio.wait_for(entered.wait(), timeout=120)
    assert await within(run_reset(maker, provider, b, clan_id), seconds=60) == ["STATE_CONFLICT"]  # no Owner yet, and it did not wait
    release.set()
    assert await asyncio.wait_for(creating, timeout=240) == "201"
    assert await run_reset(maker, provider, b, clan_id) == "200"
    st = await state(maker, clan_id)
    assert (st["owners"], st["memberships"], len(st["jobs"])) == (1, 1, 1)


async def test_a_second_owner_request_during_a_reset_is_409_and_does_not_wait(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    address = email()
    user_id, job_id = await make_owner(maker, provider, a, clan_id, address, "key-op-e6b-during-reset-1")
    entered, release = asyncio.Event(), asyncio.Event()

    async def stall(uid):
        entered.set()
        await release.wait()

    provider.hooks["set_owner_password"] = stall
    resetting = asyncio.create_task(run_reset(maker, provider, b, clan_id))
    await asyncio.wait_for(entered.wait(), timeout=120)
    second = await within(run_owner(maker, provider, b, clan_id, "key-op-e6b-during-reset-2", address=address), seconds=60)
    assert second == ["STATE_CONFLICT"]  # the clan has its Owner; the reset holds no lock the request could wait for
    release.set()
    assert await asyncio.wait_for(resetting, timeout=240) == "200"
    cred, revoked, audits = await cred_and_sessions(maker, user_id)
    assert cred.must_change_password is True and revoked == [True, True] and audits == 1


# ------------------------------------------------------------------ two resets


async def test_two_resets_at_the_same_instant_both_past_firebase_one_wins_and_the_other_writes_nothing(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    user_id, _job = await make_owner(maker, provider, a, clan_id, email(), "key-op-e6b-two-resets-1")
    both_in_firebase = asyncio.Barrier(2)  # neither writes before both have called Firebase

    async def meet(uid):
        await both_in_firebase.wait()

    provider.hooks["set_owner_password"] = meet
    outcomes = await within(run_reset(maker, provider, a, clan_id), run_reset(maker, provider, b, clan_id))
    no_errors(outcomes)
    assert sorted(outcomes) == sorted(["200", "STATE_CONFLICT"]), outcomes
    cred, revoked, audits = await cred_and_sessions(maker, user_id)
    assert audits == 1 and revoked == [True, True]  # one write, one audit row, every session revoked
    assert cred.must_change_password is True and cred.temporary_password_expires_at - cred.temporary_password_issued_at == timedelta(hours=72)
    assert len(provider.owner_password_sets) == 2  # both reached Firebase (the loser's password was overwritten there: KI-25)


async def test_a_reset_that_dies_after_firebase_changes_nothing_and_the_next_reset_works(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    user_id, _job = await make_owner(maker, provider, a, clan_id, email(), "key-op-e6b-reset-dies-1")
    before, _revoked, _audits = await cred_and_sessions(maker, user_id)

    async def die(uid):
        raise Crash()

    provider.hooks["set_owner_password"] = die
    assert await run_reset(maker, provider, b, clan_id) == "CRASH"
    provider.hooks.clear()
    after, revoked, audits = await cred_and_sessions(maker, user_id)
    assert (after.temporary_password_issued_at, after.updated_at) == (before.temporary_password_issued_at, before.updated_at)
    assert revoked == [False, False] and audits == 0
    assert await run_reset(maker, provider, a, clan_id) == "200"  # nothing is left locked
    _cred, revoked, audits = await cred_and_sessions(maker, user_id)
    assert revoked == [True, True] and audits == 1


async def test_the_owner_changes_the_password_while_the_reset_is_in_firebase_and_the_database_keeps_the_owners_state(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    user_id, _job = await make_owner(maker, provider, a, clan_id, email(), "key-op-e6b-owner-changes-1")

    async def owner_changes_password(uid):  # the Owner's own change-password commits in its own session
        async with maker() as s, s.begin():
            await s.execute(text("UPDATE users SET status = 'ACTIVE', first_login_required = false WHERE user_id = :u"), {"u": user_id})
            await s.execute(text(
                "UPDATE credential_metadata SET must_change_password = false, temporary_password_issued_at = NULL, "
                "temporary_password_expires_at = NULL, password_changed_at = now(), updated_at = now() WHERE user_id = :u"), {"u": user_id})

    provider.hooks["set_owner_password"] = owner_changes_password
    assert await run_reset(maker, provider, b, clan_id) == "STATE_CONFLICT"
    cred, revoked, audits = await cred_and_sessions(maker, user_id)
    assert (cred.must_change_password, cred.temporary_password_issued_at, cred.temporary_password_expires_at) == (False, None, None)
    assert revoked == [False, False] and audits == 0


# ------------------------------------------------------------------ no lock across a Firebase call, flags committed first


async def test_no_row_is_locked_while_a_retry_and_a_reset_are_inside_firebase(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    job_id = await failed_job(maker, provider, a, clan_id, email(), "key-op-e6b-no-lock-1")
    probed = {}

    async def probe_retry(uid):
        async with maker() as other, other.begin():
            for name, sql in (
                ("clan", "SELECT 1 FROM clans WHERE clan_id = :c FOR UPDATE NOWAIT"),
                ("job", "SELECT 1 FROM provisioning_jobs WHERE clan_id = :c FOR UPDATE NOWAIT"),
                ("key", "SELECT 1 FROM idempotency_keys WHERE actor_id = :a FOR UPDATE NOWAIT"),
            ):
                probed.setdefault(name, []).append(len((await other.execute(text(sql), {"c": clan_id, "a": a.user_id})).all()))

    provider.hooks["get_user"] = probe_retry
    provider.hooks["create_user"] = probe_retry
    assert await run_retry(maker, provider, b, job_id) == "200"
    assert probed == {"clan": [1, 1], "job": [1, 1], "key": [0, 0]}  # every probe took every lock at once (a failed first run released its key)
    user_id = (await state(maker, clan_id))["jobs"][0].user_id
    probed.clear()

    async def probe_reset(uid):
        async with maker() as other, other.begin():
            for name, sql in (
                ("clan", "SELECT 1 FROM clans WHERE clan_id = :c FOR UPDATE NOWAIT"),
                ("credential", "SELECT 1 FROM credential_metadata WHERE user_id = :u FOR UPDATE NOWAIT"),
                ("user", "SELECT 1 FROM users WHERE user_id = :u FOR UPDATE NOWAIT"),
            ):
                probed.setdefault(name, []).append(len((await other.execute(text(sql), {"c": clan_id, "u": user_id})).all()))

    provider.hooks.clear()
    provider.hooks["set_owner_password"] = probe_reset
    assert await run_reset(maker, provider, b, clan_id) == "200"
    assert probed == {"clan": [1], "credential": [1], "user": [1]}


async def test_the_abandon_flags_are_committed_before_the_delete_and_a_failed_delete_leaves_them_for_a_retry(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    address = email()
    job_id = await failed_job(maker, provider, a, clan_id, address, "key-op-e6b-abandon-flags-1", operation="create_user")
    seen = {}

    async def other_session_looks(uid):
        async with maker() as other:  # a DIFFERENT connection: sees only what is committed
            row = (await other.execute(text("SELECT status, needs_cleanup, firebase_user_created, error_code FROM provisioning_jobs WHERE job_id = :j"),
                                       {"j": job_id})).one()
            seen["row"] = tuple(row)

    provider.hooks["delete_user"] = other_session_looks
    provider.faults["delete_user"] = [ProviderUnavailable("timeout")]
    assert await run_abandon(maker, provider, b, job_id) == "200"
    assert seen["row"] == ("FAILED", True, True, "ABANDONED")  # committed first
    [job] = (await state(maker, clan_id))["jobs"]
    assert (job.status, job.needs_cleanup) == ("FAILED", True)  # the delete failed: the flags stay up
    assert await run_owner(maker, provider, a, clan_id, "key-op-e6b-abandon-flags-2", address=address) == "STATE_CONFLICT"  # blocked
    assert await run_retry(maker, provider, a, job_id) == "200"  # the clean-up
    [job] = (await state(maker, clan_id))["jobs"]
    assert (job.status, job.needs_cleanup, job.firebase_user_created) == ("FAILED", False, False)
    assert await run_owner(maker, provider, a, clan_id, "key-op-e6b-abandon-flags-3", address=address) == "201"
