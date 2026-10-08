"""Clan activation under real concurrency (Mốc E7), with a FAKE Firebase where an Owner is provisioned.
COMMITS real rows.

Data uses the same itest-conc-op- prefix as the E6 concurrency files (users itest-conc-op-*, Owner e-mails
itest-conc-op-owner-*, clan codes ITESTOP-*), cleaned by their fixture, plus plans coded ITESTOP-PLAN-* that
this file creates and deletes itself (a plan has no cascade from a clan). The DEV-* plans seeded on the dev
branch are never read, changed or deleted.

What is protected, and by what:
  * two activations at the same instant: the clan row lock leaves exactly one winner, one audit row, one
    ACTIVE subscription; the other is a 409 that says ACTIVE;
  * an activation never waits for a job that is inside Firebase (the job holds no lock): it answers 409
    "no Owner" at once, and works after the job finished;
  * an activation against a lock someone else holds does not hang: after the lock timeout it is a 409 with
    Retry-After, and it works once the lock is let go;
  * an activation racing the locking of the Owner account, and one racing the provisioning of the Owner:
    one consistent end, never a deadlock or a driver error;
  * several clans activate in parallel."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.controllers.family_management import clan_admin_use_cases
from app.core.dates import add_months
from app.core.errors import AppError
from app.models.family.entities import Clan, ClanSubscription, SubscriptionPlan
from app.models.family.idempotency_repository import IdempotencyRepository
from app.models.family.repository import FamilyRepository
from app.models.user_access.entities import AuditLog
from app.models.user_access.repository import UserAccessRepository
from tests.fakes import FakeIdentityProvider
from tests.integration.diagnostics import describe_error
from tests.integration.test_owner_provisioning_concurrency import (
    CLIENT,
    Crash,
    email,
    make_clans,
    make_sas,
    no_errors,
    run_owner,
    state,
    within,
)
from tests.integration.test_owner_recovery_concurrency import arena as base_arena
from tests.integration.test_owner_recovery_concurrency import make_owner

pytestmark = pytest.mark.concurrency

PLAN_PREFIX = "ITESTOP-PLAN-"


async def purge_plans(maker) -> None:
    async with maker() as s, s.begin():
        await s.execute(text("DELETE FROM clan_subscriptions WHERE plan_id IN (SELECT plan_id FROM subscription_plans WHERE code LIKE :p)"), {"p": PLAN_PREFIX + "%"})
        await s.execute(text("DELETE FROM subscription_plans WHERE code LIKE :p"), {"p": PLAN_PREFIX + "%"})


@pytest_asyncio.fixture(loop_scope="session")
async def arena(base_arena):
    maker = base_arena
    await purge_plans(maker)
    try:
        yield maker
    finally:
        await purge_plans(maker)
        async with maker() as s:
            left = (await s.execute(text("SELECT count(*) FROM subscription_plans WHERE code LIKE :p"), {"p": PLAN_PREFIX + "%"})).scalar_one()
        assert left == 0, "the activation tests left plans behind"


async def add_subscription(maker, clan_id, *, months=12, plan_status="ACTIVE", status="PENDING") -> uuid.UUID:
    async with maker() as s, s.begin():
        plan = SubscriptionPlan(plan_id=uuid.uuid4(), code=f"{PLAN_PREFIX}{uuid.uuid4().hex[:10].upper()}", name="Itest activation plan",
                                price=0, billing_period_months=months, status=plan_status)
        s.add(plan)
        await s.flush()
        start = datetime.now(timezone.utc) - timedelta(days=3)
        sub = ClanSubscription(subscription_id=uuid.uuid4(), clan_id=clan_id, plan_id=plan.plan_id, starts_at=start,
                               ends_at=add_months(start, months), status=status, auto_renew=False)
        s.add(sub)
        return sub.subscription_id


async def run_activate(maker, principal, clan_id, *, start=None) -> str:
    async with maker() as s:
        await s.connection()
        try:
            if start is not None:
                await start.wait()
            await clan_admin_use_cases.activate_clan(
                db=s, users=UserAccessRepository(s), family=FamilyRepository(s), idempotency=IdempotencyRepository(s),
                principal=principal, clan_id=clan_id, client=CLIENT)
            return "200"
        except AppError as exc:
            return str(exc.code) if exc.code else "ERR"
        except Crash:
            return "CRASH"
        except Exception as exc:  # noqa: BLE001 - a driver error here is exactly what must not happen
            return describe_error(exc)


async def clan_state(maker, clan_id) -> dict:
    async with maker() as s:
        clan = (await s.execute(select(Clan).where(Clan.clan_id == clan_id))).scalar_one()
        subs = list((await s.execute(select(ClanSubscription).where(ClanSubscription.clan_id == clan_id))).scalars())
        audits = (await s.execute(select(AuditLog.log_id).where(AuditLog.action == "clan.activate", AuditLog.clan_id == clan_id))).all()
        return {"clan": clan, "subs": subs, "audits": len(audits)}


async def ready_clan(maker, provider, sa, *, months=12):
    """A clan with a finished Owner (through the API use case, fake Firebase) and a PENDING subscription."""
    [clan_id] = await make_clans(maker)
    user_id, _job = await make_owner(maker, provider, sa, clan_id, email(), f"key-act-{uuid.uuid4().hex[:12]}", sessions=0)
    sub_id = await add_subscription(maker, clan_id, months=months)
    return clan_id, user_id, sub_id


async def test_two_activations_at_the_same_instant_one_wins_one_audit_row_one_active_subscription(arena):
    maker = arena
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    clan_id, _user, sub_id = await ready_clan(maker, provider, a, months=6)
    start = asyncio.Barrier(2)
    outcomes = await within(run_activate(maker, a, clan_id, start=start), run_activate(maker, b, clan_id, start=start))
    no_errors(outcomes)
    assert sorted(outcomes) == sorted(["200", "STATE_CONFLICT"]), outcomes
    st = await clan_state(maker, clan_id)
    [sub] = st["subs"]
    assert (st["clan"].status, sub.status, st["audits"]) == ("ACTIVE", "ACTIVE", 1)
    assert sub.starts_at == st["clan"].activated_at and sub.ends_at == add_months(sub.starts_at, 6)


async def test_an_activation_does_not_wait_for_a_job_inside_firebase_and_works_after_it(arena):
    maker = arena
    a, b = await make_sas(maker, 2)
    provider = FakeIdentityProvider()
    [clan_id] = await make_clans(maker)
    await add_subscription(maker, clan_id)
    entered, release = asyncio.Event(), asyncio.Event()

    async def stall(uid):
        entered.set()
        await release.wait()

    provider.hooks["create_user"] = stall
    creating = asyncio.create_task(run_owner(maker, provider, a, clan_id, "key-act-vs-job-1", address=email()))
    await asyncio.wait_for(entered.wait(), timeout=120)
    assert await within(run_activate(maker, b, clan_id), seconds=60) == ["STATE_CONFLICT"]  # no Owner yet, and it did not wait
    release.set()
    assert await asyncio.wait_for(creating, timeout=240) == "201"
    assert await run_activate(maker, b, clan_id) == "200"
    st = await state(maker, clan_id)
    assert (st["owners"], st["memberships"], len(st["jobs"])) == (1, 1, 1)
    assert (await clan_state(maker, clan_id))["clan"].status == "ACTIVE"


async def test_an_activation_against_a_lock_someone_holds_is_a_409_after_the_timeout_not_a_hang_and_works_after(arena):
    maker = arena
    [sa] = await make_sas(maker, 1)
    provider = FakeIdentityProvider()
    clan_id, _user, _sub = await ready_clan(maker, provider, sa)
    holder = maker()
    await holder.__aenter__()
    try:
        await holder.execute(text("SELECT 1 FROM clans WHERE clan_id = :c FOR NO KEY UPDATE"), {"c": clan_id})  # held, uncommitted
        busy = await within(run_activate(maker, sa, clan_id), seconds=120)
        assert busy == ["STATE_CONFLICT"], busy  # busy_error after the lock timeout (409 + Retry-After), no driver error
        assert (await clan_state(maker, clan_id))["clan"].status == "PENDING"
    finally:
        await holder.rollback()
        await holder.__aexit__(None, None, None)
    assert await run_activate(maker, sa, clan_id) == "200"


async def test_an_activation_racing_the_locking_of_the_owner_account_ends_in_one_consistent_state(arena):
    maker = arena
    [sa] = await make_sas(maker, 1)
    provider = FakeIdentityProvider()
    for round_ in range(3):
        clan_id, user_id, _sub = await ready_clan(maker, provider, sa)
        start = asyncio.Barrier(2)

        async def lock_owner():
            async with maker() as s, s.begin():
                await start.wait()
                await s.execute(text("UPDATE users SET status = 'LOCKED' WHERE user_id = :u"), {"u": user_id})
            return "locked"

        activation, locked = await within(run_activate(maker, sa, clan_id, start=start), lock_owner())
        no_errors([activation])
        assert locked == "locked" and activation in ("200", "STATE_CONFLICT"), (round_, activation)
        status = (await clan_state(maker, clan_id))["clan"].status
        assert status == ("ACTIVE" if activation == "200" else "PENDING")  # the answer and the row agree


async def test_an_activation_racing_the_provisioning_of_the_owner_never_deadlocks(arena):
    maker = arena
    a, b = await make_sas(maker, 2)
    for round_ in range(3):
        provider = FakeIdentityProvider()
        [clan_id] = await make_clans(maker)
        await add_subscription(maker, clan_id)
        start = asyncio.Barrier(2)
        provisioning, activation = await within(
            run_owner(maker, provider, a, clan_id, f"key-act-race-{round_}-{uuid.uuid4().hex[:6]}", address=email(), start=start),
            run_activate(maker, b, clan_id, start=start))
        no_errors([provisioning, activation])
        assert provisioning == "201" and activation in ("200", "STATE_CONFLICT"), (round_, provisioning, activation)
        st = await clan_state(maker, clan_id)
        assert st["clan"].status == ("ACTIVE" if activation == "200" else "PENDING")
        if activation == "STATE_CONFLICT":  # the Owner did not exist yet when it asked: asking again works
            assert await run_activate(maker, b, clan_id) == "200"


async def test_clans_activate_in_parallel_without_blocking_or_deadlock(arena):
    maker = arena
    sas = await make_sas(maker, 4)
    provider = FakeIdentityProvider()
    clans = [(await ready_clan(maker, provider, sa))[0] for sa in sas]
    start = asyncio.Barrier(4)
    outcomes = await within(*[run_activate(maker, sa, clan, start=start) for sa, clan in zip(sas, clans)])
    no_errors(outcomes)
    assert outcomes == ["200"] * 4
    for clan in clans:
        st = await clan_state(maker, clan)
        assert (st["clan"].status, st["subs"][0].status, st["audits"]) == ("ACTIVE", "ACTIVE", 1)
