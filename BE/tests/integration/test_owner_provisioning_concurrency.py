"""Create the Owner under real concurrency (Mốc E6a), with a FAKE Firebase. COMMITS real rows.

Data uses the itest-conc-op- prefix (users itest-conc-op-*, Owner e-mails itest-conc-op-owner-*, clan
codes ITESTOP-*) and is deleted in finally, with the audit rows, clans (their jobs, memberships, roles and
ownership cascade) and users (their idempotency rows and credentials cascade). The DEV-* plans seeded on
the dev branch are never read, changed or deleted: a last check proves their count did not move.

What is protected, and by what:
  * the same Idempotency-Key at the same instant: the first T1 commits the key as IN_PROGRESS with the job;
    the other waits on the unique index only for that short transaction, then sees IN_PROGRESS and answers
    409 with the job id. ONE job, ONE Firebase user, ONE Owner;
  * two keys for one clan, two clans for one e-mail: the clan row lock, the live-job indexes and the e-mail
    index give exactly one job; the other request is a 409;
  * NO lock is held while the identity provider is called: from inside the call, another session can take
    the clan, job and key rows with FOR UPDATE NOWAIT;
  * a run that was replaced (its attempt_count moved on) writes and deletes nothing;
  * a run that dies leaves the job RUNNING and the key IN_PROGRESS, and nothing blocks forever.

A non-application error is reported by describe_error() with its SQLSTATE; there is no retry anywhere."""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.controllers.auth_access.use_cases import ClientInfo
from app.controllers.family_management import owner_provisioning_use_cases as use_cases
from app.core.email_sender import NoopEmailSender
from app.core.errors import AppError
from app.db.postgres import make_engine
from app.dependencies.auth import Principal
from app.models.family.entities import Clan, IdempotencyKey, ProvisioningJob, SubscriptionPlan
from app.models.family.idempotency_repository import IdempotencyRepository
from app.models.family.provisioning_repository import ProvisioningRepository
from app.models.family.repository import FamilyRepository
from app.models.user_access.entities import AuditLog, User
from app.models.user_access.repository import UserAccessRepository
from app.schemas.business import OwnerProvisionRequest
from tests.fakes import FakeIdentityProvider
from tests.integration.diagnostics import describe_error, is_error

pytestmark = pytest.mark.concurrency

USER_PREFIX = "itest-conc-op-"
OWNER_PREFIX = "itest-conc-op-owner-"
CODE_PREFIX = "ITESTOP-"
KNOWN = "Kq7Wm2Xp9Tr4Vz8N"
CLIENT = ClientInfo(ip_address=None, user_agent=None)


class Crash(BaseException):
    """A process that dies."""


async def purge(s) -> None:
    # (the e-mail comparison ignores the letter case: some tests give the same Owner e-mail in upper case)
    user_ids = list((await s.execute(select(User.user_id).where(
        User.firebase_uid.startswith(USER_PREFIX) | func.lower(User.email).startswith(OWNER_PREFIX)
        | func.lower(User.email).startswith(USER_PREFIX)))).scalars())
    clan_ids = list((await s.execute(select(Clan.clan_id).where(Clan.clan_code.startswith(CODE_PREFIX)))).scalars())
    job_ids = list((await s.execute(select(ProvisioningJob.job_id).where(ProvisioningJob.clan_id.in_(clan_ids)))).scalars()) if clan_ids else []
    if clan_ids:
        await s.execute(delete(AuditLog).where(AuditLog.clan_id.in_(clan_ids)))
        if job_ids:
            await s.execute(delete(AuditLog).where(AuditLog.entity_id.in_(job_ids)))
        await s.execute(delete(Clan).where(Clan.clan_id.in_(clan_ids)))  # jobs, memberships, roles, ownership cascade
    if user_ids:
        await s.execute(delete(AuditLog).where(AuditLog.actor_id.in_(user_ids)))
        await s.execute(delete(User).where(User.user_id.in_(user_ids)))  # credentials, idempotency rows cascade


async def dev_plan_count(maker) -> int:
    async with maker() as s:
        return (await s.execute(select(func.count()).select_from(SubscriptionPlan).where(SubscriptionPlan.code.startswith("DEV-")))).scalar_one()


@pytest_asyncio.fixture(loop_scope="session")
async def arena(monkeypatch):
    from app.core.config import settings

    engine = make_engine(settings.DATABASE_URL, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(use_cases, "_default_password", lambda: KNOWN)
    try:
        async with maker() as s, s.begin():
            await purge(s)  # leftovers of a crashed run (our prefixes only)
        dev_before = await dev_plan_count(maker)
        yield maker
        assert await dev_plan_count(maker) == dev_before  # the seeded DEV-* plans were never touched
    finally:
        async with maker() as s, s.begin():
            await purge(s)
        async with maker() as s:  # nothing of ours may be left behind, in ANY letter case
            left = (await s.execute(select(func.count()).select_from(User).where(
                func.lower(User.email).startswith(USER_PREFIX) | User.firebase_uid.startswith(USER_PREFIX)))).scalar_one()
            owners = (await s.execute(text("SELECT count(*) FROM users WHERE firebase_uid LIKE 'own-%' AND lower(email) LIKE :p"),
                                      {"p": USER_PREFIX + "%"})).scalar_one()
        await engine.dispose()
        assert left == 0 and owners == 0, "the concurrency tests left users behind"


async def make_sas(maker, count: int) -> list[Principal]:
    out = []
    async with maker() as s, s.begin():
        for _ in range(count):
            t = uuid.uuid4().hex[:12]
            user = User(user_id=uuid.uuid4(), firebase_uid=f"{USER_PREFIX}{t}", email=f"{USER_PREFIX}{t}@example.test",
                        display_name="Concurrency SA", status="ACTIVE", first_login_required=False)
            s.add(user)
            out.append(Principal(user_id=user.user_id, session_id=uuid.uuid4(), status="ACTIVE", requires_password_change=False))
    return out


async def make_clans(maker, count: int = 1) -> list[uuid.UUID]:
    out = []
    async with maker() as s, s.begin():
        for _ in range(count):
            clan = Clan(clan_id=uuid.uuid4(), clan_code=f"{CODE_PREFIX}{uuid.uuid4().hex[:8].upper()}", name="Itest Conc Owner Clan", status="PENDING")
            s.add(clan)
            out.append(clan.clan_id)
    return out


def email() -> str:
    return f"{OWNER_PREFIX}{uuid.uuid4().hex[:10]}@Example.TEST"


class ReplacedBeforeTheRows(FamilyRepository):
    """On the SECOND lock of the clan (the one at the start of T4, before the job row is locked), another run
    claims the job in its own committed transaction: the run in T4 has just been replaced."""

    def __init__(self, session, maker, clan_id) -> None:
        super().__init__(session)
        self._maker, self._clan_id, self._locks = maker, clan_id, 0

    async def lock_clan(self, clan_id):
        clan = await super().lock_clan(clan_id)
        self._locks += 1
        if self._locks == 2:
            async with self._maker() as other, other.begin():
                await other.execute(text("UPDATE provisioning_jobs SET attempt_count = attempt_count + 1 WHERE clan_id = :c"),
                                    {"c": self._clan_id})
        return clan


async def run_owner(maker, provider, principal, clan_id, key, *, address, start=None, marks=None, results=None, family_factory=None):
    """One request: its own session, its connection opened first, the use case as the router calls it."""
    async with maker() as s:
        await s.connection()
        if start is not None:
            await start.wait()
        try:
            result = await use_cases.provision_owner(
                db=s, users=UserAccessRepository(s), family=family_factory(s) if family_factory else FamilyRepository(s), jobs=ProvisioningRepository(s),
                idempotency=IdempotencyRepository(s), provider=provider, sender=NoopEmailSender(), principal=principal,
                clan_id=clan_id, body=OwnerProvisionRequest(email=address, display_name="Concurrency Owner"), key=key, client=CLIENT)
            if results is not None:
                results.append(result)
            return f"{result.status}{'R' if result.replayed else ''}"
        except AppError as exc:
            return str(exc.code)
        except Crash:
            return "CRASH"
        except Exception as exc:  # noqa: BLE001 - a driver error here is exactly what must not happen
            return describe_error(exc)


async def within(*coroutines, seconds: float = 240.0) -> list:
    return await asyncio.wait_for(asyncio.gather(*coroutines), timeout=seconds)


def no_errors(results) -> None:
    errors = [r for r in results if is_error(r)]
    assert not errors, f"driver errors (deadlock, 500, or a dropped connection: see the sqlstate): {errors}"


async def state(maker, clan_id) -> dict:
    async with maker() as s:
        jobs = list((await s.execute(select(ProvisioningJob).where(ProvisioningJob.clan_id == clan_id))).scalars())
        owners = (await s.execute(text("SELECT count(*) FROM clan_ownership_history WHERE clan_id = :c AND ended_at IS NULL"), {"c": clan_id})).scalar_one()
        memberships = (await s.execute(text("SELECT count(*) FROM clan_memberships WHERE clan_id = :c"), {"c": clan_id})).scalar_one()
        return {"jobs": jobs, "owners": owners, "memberships": memberships}


async def keys_of(maker, actor_id) -> list[IdempotencyKey]:
    async with maker() as s:
        return list((await s.execute(select(IdempotencyKey).where(IdempotencyKey.actor_id == actor_id))).scalars())


# ------------------------------------------------------------------ the same key


async def test_the_same_key_at_the_same_instant_one_job_and_one_owner_the_other_is_409_with_the_job_id(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    [sa] = await make_sas(maker, 1)
    provider = FakeIdentityProvider()
    address = email()
    start, results = asyncio.Barrier(2), []
    outcomes = await within(*[run_owner(maker, provider, sa, clan_id, "key-op-same-instant-1", address=address, start=start, results=results) for _ in range(2)])
    no_errors(outcomes)
    assert sorted(outcomes) == sorted(["201", "STATE_CONFLICT"]), outcomes  # the loser sees the key IN_PROGRESS
    st = await state(maker, clan_id)
    assert len(st["jobs"]) == 1 and st["owners"] == 1 and st["memberships"] == 1
    assert st["jobs"][0].status == "SUCCEEDED" and len(provider.provider_users) == 1
    assert [op for op, _ in provider.provider_calls].count("create_user") == 1
    assert len(results) == 1 and results[0].response.temporary_password == KNOWN  # exactly one request ever saw the password
    again = await run_owner(maker, provider, sa, clan_id, "key-op-same-instant-1", address=address)
    assert again == "201R"  # now it is a replay of the finished request


async def test_two_keys_for_one_clan_one_job_and_the_other_is_409(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    start = asyncio.Barrier(2)
    outcomes = await within(run_owner(maker, provider, a, clan_id, "key-op-two-keys-aaaaa", address=email(), start=start),
                            run_owner(maker, provider, b, clan_id, "key-op-two-keys-bbbbb", address=email(), start=start))
    no_errors(outcomes)
    assert sorted(outcomes) == sorted(["201", "STATE_CONFLICT"]), outcomes
    st = await state(maker, clan_id)
    assert len(st["jobs"]) == 1 and st["owners"] == 1 and len(provider.provider_users) == 1
    loser = b if outcomes[0] == "201" else a
    assert await keys_of(maker, loser.user_id) == []  # the loser's key was rolled back


async def test_two_clans_for_one_email_one_owner_and_the_other_is_409_duplicate(arena):
    maker = arena
    first, second = await make_clans(maker, 2)
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    address = email()
    start = asyncio.Barrier(2)
    outcomes = await within(run_owner(maker, provider, a, first, "key-op-same-email-aaaa", address=address, start=start),
                            run_owner(maker, provider, b, second, "key-op-same-email-bbbb", address=address.upper(), start=start))
    no_errors(outcomes)
    assert sorted(outcomes) == sorted(["201", "DUPLICATE_RESOURCE"]), outcomes
    states = [await state(maker, first), await state(maker, second)]
    assert sorted(st["owners"] for st in states) == [0, 1] and len(provider.provider_users) == 1


async def test_clans_with_different_emails_are_provisioned_in_parallel_without_blocking_or_deadlock(arena):
    maker = arena
    clans = await make_clans(maker, 4)
    sas = await make_sas(maker, 4)
    provider = FakeIdentityProvider()
    start = asyncio.Barrier(4)
    outcomes = await within(*[run_owner(maker, provider, sa, clan, f"key-op-parallel-{i}-abcdef", address=email(), start=start)
                              for i, (sa, clan) in enumerate(zip(sas, clans))])
    no_errors(outcomes)
    assert outcomes == ["201"] * 4
    for clan in clans:
        st = await state(maker, clan)
        assert len(st["jobs"]) == 1 and st["jobs"][0].status == "SUCCEEDED" and st["owners"] == 1
    assert len(provider.provider_users) == 4


# ------------------------------------------------------------------ no lock while the provider is called


async def test_no_row_is_locked_while_the_identity_provider_is_being_called(arena):
    """From inside the Firebase call another session takes the clan, the job and the key rows FOR UPDATE NOWAIT:
    it would fail at once if the request still held any lock (or any transaction)."""
    maker = arena
    [clan_id] = await make_clans(maker)
    [sa] = await make_sas(maker, 1)
    provider = FakeIdentityProvider()
    probed = {}

    async def probe(uid):
        async with maker() as other, other.begin():
            for name, sql in (
                ("clan", "SELECT 1 FROM clans WHERE clan_id = :c FOR UPDATE NOWAIT"),
                ("job", "SELECT 1 FROM provisioning_jobs WHERE clan_id = :c FOR UPDATE NOWAIT"),
                ("key", "SELECT 1 FROM idempotency_keys WHERE actor_id = :a FOR UPDATE NOWAIT"),
            ):
                rows = (await other.execute(text(sql), {"c": clan_id, "a": sa.user_id})).all()
                probed.setdefault(name, []).append(len(rows))

    provider.hooks["get_user"] = probe
    provider.hooks["create_user"] = probe
    outcome = await run_owner(maker, provider, sa, clan_id, "key-op-no-lock-held-1", address=email())
    assert outcome == "201"
    assert probed == {"clan": [1, 1], "job": [1, 1], "key": [1, 1]}  # every probe got every lock at once


# ------------------------------------------------------------------ fencing and death


async def test_a_run_that_was_replaced_writes_and_deletes_nothing(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    [sa] = await make_sas(maker, 1)
    provider = FakeIdentityProvider()

    async def taken_over(uid):
        async with maker() as other, other.begin():
            await other.execute(text("UPDATE provisioning_jobs SET attempt_count = attempt_count + 1 WHERE clan_id = :c"), {"c": clan_id})

    provider.hooks["create_user"] = taken_over
    outcome = await run_owner(maker, provider, sa, clan_id, "key-op-replaced-run-1", address=email())
    assert outcome == "STATE_CONFLICT"
    st = await state(maker, clan_id)
    assert st["jobs"][0].status == "RUNNING" and st["jobs"][0].attempt_count == 2 and st["owners"] == 0
    assert "delete_user" not in [op for op, _ in provider.provider_calls]


async def test_a_run_replaced_just_before_the_rows_are_written_writes_no_owner(arena):
    """The fence of the LAST transaction (T4) on the real database: the job moved on after T3 committed."""
    maker = arena
    [clan_id] = await make_clans(maker)
    [sa] = await make_sas(maker, 1)
    provider = FakeIdentityProvider()
    address = email()
    outcome = await run_owner(maker, provider, sa, clan_id, "key-op-replaced-late-01", address=address,
                              family_factory=lambda s: ReplacedBeforeTheRows(s, maker, clan_id))
    assert outcome == "STATE_CONFLICT"
    st = await state(maker, clan_id)
    assert (st["jobs"][0].status, st["jobs"][0].attempt_count) == ("RUNNING", 2)  # the newer attempt's, untouched by T4
    assert st["owners"] == 0 and st["memberships"] == 0
    async with maker() as s:
        assert (await s.execute(select(func.count()).select_from(User).where(func.lower(User.email) == address.lower()))).scalar_one() == 0
    assert "delete_user" not in [op for op, _ in provider.provider_calls]


async def test_a_run_that_dies_leaves_the_job_running_and_the_key_in_progress_and_nothing_blocks(arena):
    maker = arena
    [clan_id] = await make_clans(maker)
    [sa] = await make_sas(maker, 1)
    provider = FakeIdentityProvider()
    address = email()

    async def die(uid):
        raise Crash()

    provider.hooks["get_user"] = die
    assert await run_owner(maker, provider, sa, clan_id, "key-op-process-died-1", address=address) == "CRASH"
    provider.hooks.clear()
    st = await state(maker, clan_id)
    job = st["jobs"][0]
    assert (job.status, job.attempt_count) == ("RUNNING", 1) and job.lease_expires_at is not None
    [key] = await keys_of(maker, sa.user_id)
    assert (key.status, key.resource_id) == ("IN_PROGRESS", job.job_id)
    waiter = await within(run_owner(maker, provider, sa, clan_id, "key-op-process-died-1", address=address),
                          run_owner(maker, provider, sa, clan_id, "key-op-process-died-2", address=address))
    assert waiter == ["STATE_CONFLICT", "STATE_CONFLICT"]  # both are told about the job; neither hangs
    assert len((await state(maker, clan_id))["jobs"]) == 1


async def test_a_final_failure_is_compensated_under_real_concurrency_and_frees_the_clan_and_the_email(arena):
    from app.core.firebase import ProviderInvalidUser

    maker = arena
    [clan_id] = await make_clans(maker)
    [sa] = await make_sas(maker, 1)
    provider = FakeIdentityProvider()
    provider.faults["create_user"] = [ProviderInvalidUser()]
    address = email()
    assert await run_owner(maker, provider, sa, clan_id, "key-op-final-failure-1", address=address) == "STATE_CONFLICT"
    job = (await state(maker, clan_id))["jobs"][0]
    assert (job.status, job.needs_cleanup, job.firebase_user_created, job.error_code) == ("FAILED", False, False, "PROVIDER_REJECTED_USER")
    assert provider.provider_users == {} and await keys_of(maker, sa.user_id) == []
    assert await run_owner(maker, provider, sa, clan_id, "key-op-final-failure-2", address=address) == "201"  # a FAILED job blocks nothing
    st = await state(maker, clan_id)
    assert len(st["jobs"]) == 2 and st["owners"] == 1
