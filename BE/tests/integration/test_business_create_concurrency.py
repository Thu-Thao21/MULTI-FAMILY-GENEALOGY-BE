"""Create the Business under real concurrency (Mốc E, E5). COMMITS real rows.

Data uses the itest-conc-bc- prefix (a plan ITEST-CONC-BC-*, users itest-conc-bc-*, applicant
e-mails itest-conc-bc-reg-*, clan codes ITESTBC-*) and is deleted in finally, with the audit rows,
clans, profiles, subscriptions and idempotency rows that name it. The DEV-* plans seeded on the dev
branch are never read as an expectation, changed or deleted: a last check proves their count did not
move.

What is protected, and by what:
  * the same key at the same instant: the INSERT ... ON CONFLICT DO NOTHING of the key WAITS on the
    unique index until the first request commits (then it replays) or rolls back (then it runs as a
    fresh request). One Business, never two, and the same body for both;
  * the same key with a different request: exactly one wins, the other is 409 IDEMPOTENCY_KEY_CONFLICT;
  * two keys for one registration, or two registrations with one clan code: the registration row
    lock and the unique indexes give exactly one Business and a 409 DUPLICATE_RESOURCE for the other;
  * a Business racing a review of the registration: the create waits for the registration lock and
    sees what the review committed, and never blocks the review;
  * a request that dies half-way rolls everything back, key included, and a waiter with the same key
    then creates the Business;
  * a generated code that collides under a real race is drawn again;
  * the users row of the SA is never locked.

Timing: a NEW session needs ~4 s to open its Neon connection, so every request opens its connection
BEFORE it waits, and the winner holds its transaction for HOLD_SECONDS before COMMIT so the others
really are queued behind the lock. A non-application error is reported by describe_error() with its
SQLSTATE; there is no retry anywhere.
"""

from __future__ import annotations

import asyncio
import itertools
import time
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

import app.controllers.family_management.business_admin_use_cases as use_cases
from app.controllers.auth_access.use_cases import ClientInfo
from app.core.errors import AppError
from app.db.postgres import make_engine
from app.dependencies.auth import Principal
from app.models.family.entities import (
    BusinessRegistration,
    Clan,
    ClanProfile,
    ClanSubscription,
    IdempotencyKey,
    SubscriptionPlan,
)
from app.models.family.idempotency_repository import IdempotencyRepository
from app.models.family.repository import FamilyRepository
from app.models.user_access.entities import AuditLog, User
from app.models.user_access.repository import UserAccessRepository
from app.schemas.business import BusinessCreateRequest, RegistrationReviewRequest
from app.controllers.family_management.registration_admin_use_cases import review_registration
from tests.integration.diagnostics import describe_error, is_error

pytestmark = pytest.mark.concurrency

PLAN_PREFIX = "ITEST-CONC-BC-"
USER_PREFIX = "itest-conc-bc-"
EMAIL_PREFIX = "itest-conc-bc-reg-"
CODE_PREFIX = "ITESTBC-"
HOLD_SECONDS = 1.5
LONG_HOLD = 6.0
CLIENT = ClientInfo(ip_address=None, user_agent=None)


class SlowCommit:
    """Unit of work that holds the transaction open just before COMMIT (and says so)."""

    def __init__(self, session, hold: float = HOLD_SECONDS, holding: asyncio.Event | None = None) -> None:
        self._s, self._hold, self._holding = session, hold, holding

    async def commit(self) -> None:
        if self._holding is not None:
            self._holding.set()
        await asyncio.sleep(self._hold)
        await self._s.commit()

    async def rollback(self) -> None:
        await self._s.rollback()


async def purge(s) -> None:
    plan_ids = select(SubscriptionPlan.plan_id).where(SubscriptionPlan.code.startswith(PLAN_PREFIX))
    reg_ids = list((await s.execute(select(BusinessRegistration.registration_id).where(
        BusinessRegistration.requested_plan_id.in_(plan_ids) | BusinessRegistration.representative_email.startswith(EMAIL_PREFIX)))).scalars())
    user_ids = list((await s.execute(select(User.user_id).where(User.firebase_uid.startswith(USER_PREFIX)))).scalars())
    clan_ids = list((await s.execute(select(Clan.clan_id).where(
        Clan.registration_id.in_(reg_ids) | Clan.created_by.in_(user_ids) | Clan.clan_code.startswith(CODE_PREFIX)))).scalars()) if (reg_ids or user_ids) else []
    if clan_ids:
        await s.execute(delete(AuditLog).where(AuditLog.clan_id.in_(clan_ids)))
        await s.execute(delete(Clan).where(Clan.clan_id.in_(clan_ids)))  # profile and subscription cascade
    if reg_ids:
        await s.execute(delete(AuditLog).where(AuditLog.entity_id.in_(reg_ids)))
        await s.execute(delete(BusinessRegistration).where(BusinessRegistration.registration_id.in_(reg_ids)))
    if user_ids:
        await s.execute(delete(AuditLog).where(AuditLog.actor_id.in_(user_ids)))
        await s.execute(delete(User).where(User.user_id.in_(user_ids)))  # idempotency rows cascade
    await s.execute(delete(SubscriptionPlan).where(SubscriptionPlan.code.startswith(PLAN_PREFIX)))


async def dev_plan_count(maker) -> int:
    async with maker() as s:
        return (await s.execute(select(func.count()).select_from(SubscriptionPlan).where(SubscriptionPlan.code.startswith("DEV-")))).scalar_one()


@pytest_asyncio.fixture(loop_scope="session")
async def arena():
    """(session maker, plan_id): a committed ACTIVE plan of our own; DEV-* plans counted, never touched."""
    from app.core.config import settings

    engine = make_engine(settings.DATABASE_URL, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as s, s.begin():
            await purge(s)  # leftovers of a crashed run (our prefixes only)
        dev_before = await dev_plan_count(maker)
        async with maker() as s, s.begin():
            plan = SubscriptionPlan(plan_id=uuid.uuid4(), code=f"{PLAN_PREFIX}{uuid.uuid4().hex[:10].upper()}", name="Business concurrency plan",
                                    price=Decimal("0.00"), billing_period_months=12, status="ACTIVE")
            s.add(plan)
        yield maker, plan.plan_id
        assert await dev_plan_count(maker) == dev_before  # the seeded DEV-* plans were never touched
    finally:
        async with maker() as s, s.begin():
            await purge(s)
        await engine.dispose()


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


async def make_registrations(maker, plan_id, count: int = 1, status: str = "APPROVED") -> list[uuid.UUID]:
    out = []
    async with maker() as s, s.begin():
        for _ in range(count):
            t = uuid.uuid4().hex[:12]
            row = BusinessRegistration(registration_id=uuid.uuid4(), requested_plan_id=plan_id, representative_name="Concurrency Applicant",
                                       representative_email=f"{EMAIL_PREFIX}{t}@example.test", clan_name=f"Itest Conc Business {t}",
                                       origin_place="Itest Village", status=status, tracking_code_hash=uuid.uuid4().hex + uuid.uuid4().hex)
            s.add(row)
            out.append(row.registration_id)
    return out


def code(prefix: str = CODE_PREFIX) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8].upper()}"


class LockedThenWait(FamilyRepository):
    """After the registration row is locked (and its state read), hold the lock for a while."""

    def __init__(self, session, holding: asyncio.Event, hold: float) -> None:
        super().__init__(session)
        self._holding, self._hold = holding, hold

    async def lock_registration(self, registration_id):
        row = await super().lock_registration(registration_id)
        self._holding.set()
        await asyncio.sleep(self._hold)
        return row


class DiesHalfWay(FamilyRepository):
    """Fails after the clan and its profile were written, while the key row is still uncommitted."""

    def __init__(self, session, holding: asyncio.Event, hold: float) -> None:
        super().__init__(session)
        self._holding, self._hold = holding, hold

    async def create_subscription(self, **kw):
        self._holding.set()
        await asyncio.sleep(self._hold)
        raise RuntimeError("INJECTED: the process died half-way")


async def run_create(maker, principal, registration_id, key, *, body=None, start=None, hold=HOLD_SECONDS, holding=None,
                     family_factory=None, marks=None, bodies=None):
    """One request: its own session, its connection opened first, the use case as the router calls it.

    Returns '201', '201R' (a replay), an application error code, 'INJECTED' for the failure this test
    caused on purpose, or describe_error() for anything else.
    """
    async with maker() as s:
        await s.connection()  # open the connection BEFORE waiting
        if start is not None:
            await start.wait()
        began = time.monotonic()
        family = family_factory(s) if family_factory is not None else FamilyRepository(s)
        try:
            result = await use_cases.create_business(
                db=SlowCommit(s, hold, holding), users=UserAccessRepository(s), family=family, idempotency=IdempotencyRepository(s),
                principal=principal, registration_id=registration_id, body=body or BusinessCreateRequest(), key=key, client=CLIENT)
            if marks is not None:
                marks.append((began, time.monotonic()))
            if bodies is not None:
                bodies.append(result.body)
            return f"{result.status}{'R' if result.replayed else ''}"
        except AppError as exc:
            return str(exc.code)
        except RuntimeError as exc:
            return "INJECTED" if str(exc).startswith("INJECTED") else describe_error(exc)
        except Exception as exc:  # noqa: BLE001 - a driver error here is exactly what must not happen
            return describe_error(exc)


async def within(*coroutines, seconds: float = 240.0) -> list:
    return await asyncio.wait_for(asyncio.gather(*coroutines), timeout=seconds)


def no_errors(results) -> None:
    errors = [r for r in results if is_error(r)]
    assert not errors, f"driver errors (deadlock, 500, or a dropped connection: see the sqlstate): {errors}"


async def state(maker, registration_id) -> dict:
    async with maker() as s:
        clans = list((await s.execute(select(Clan).where(Clan.registration_id == registration_id))).scalars())
        ids = [c.clan_id for c in clans]
        profiles = (await s.execute(select(func.count()).select_from(ClanProfile).where(ClanProfile.clan_id.in_(ids)))).scalar_one() if ids else 0
        subs = (await s.execute(select(func.count()).select_from(ClanSubscription).where(ClanSubscription.clan_id.in_(ids)))).scalar_one() if ids else 0
        audit = (await s.execute(select(func.count()).select_from(AuditLog).where(AuditLog.clan_id.in_(ids)))).scalar_one() if ids else 0
        reg = (await s.execute(select(BusinessRegistration).where(BusinessRegistration.registration_id == registration_id))).scalar_one()
        return {"clans": clans, "profiles": profiles, "subscriptions": subs, "audit": audit, "status": reg.status}


async def keys_of(maker, actor_id) -> list[IdempotencyKey]:
    async with maker() as s:
        return list((await s.execute(select(IdempotencyKey).where(IdempotencyKey.actor_id == actor_id))).scalars())


def one_business(st) -> None:
    assert len(st["clans"]) == 1 and (st["profiles"], st["subscriptions"], st["audit"]) == (1, 1, 1), st


# ------------------------------------------------------------------ the same key


async def test_the_same_key_at_the_same_instant_creates_one_business_and_both_get_the_same_answer(arena):
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id)
    [sa] = await make_sas(maker, 1)
    start, bodies = asyncio.Barrier(2), []
    results = await within(*[run_create(maker, sa, registration_id, "key-same-instant-1", start=start, bodies=bodies) for _ in range(2)])
    no_errors(results)
    assert sorted(results) == ["201", "201R"], results  # the second WAITED on the unique index, then replayed
    assert len(bodies) == 2 and bodies[0] == bodies[1]
    st = await state(maker, registration_id)
    one_business(st)
    assert str(st["clans"][0].clan_id) == bodies[0]["clan_id"]
    [row] = await keys_of(maker, sa.user_id)
    assert (row.status, row.response_status, row.response_body) == ("COMPLETED", 201, bodies[0])


async def test_six_requests_with_the_same_key_one_creation_and_five_replays(arena):
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id)
    [sa] = await make_sas(maker, 1)
    start, bodies = asyncio.Barrier(6), []
    results = await within(*[run_create(maker, sa, registration_id, "key-six-at-once-1", start=start, bodies=bodies) for _ in range(6)])
    no_errors(results)
    assert sorted(results) == sorted(["201"] + ["201R"] * 5), results
    assert all(b == bodies[0] for b in bodies)
    one_business(await state(maker, registration_id))
    assert len(await keys_of(maker, sa.user_id)) == 1


async def test_the_same_key_with_a_different_request_one_wins_and_the_other_is_a_key_conflict(arena):
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id)
    [sa] = await make_sas(maker, 1)
    start = asyncio.Barrier(2)
    a, b = code(), code()
    results = await within(
        run_create(maker, sa, registration_id, "key-different-req-1", body=BusinessCreateRequest(clan_code=a), start=start),
        run_create(maker, sa, registration_id, "key-different-req-1", body=BusinessCreateRequest(clan_code=b), start=start))
    no_errors(results)
    assert sorted(results) == sorted(["201", "IDEMPOTENCY_KEY_CONFLICT"]), results
    st = await state(maker, registration_id)
    one_business(st)
    assert st["clans"][0].clan_code == (a, b)[results.index("201")]


async def test_a_request_that_dies_half_way_leaves_nothing_and_a_waiter_with_the_same_key_creates_it(arena):
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id)
    [sa] = await make_sas(maker, 1)
    holding = asyncio.Event()
    first = asyncio.create_task(run_create(
        maker, sa, registration_id, "key-dies-and-waiter-1", holding=holding, hold=HOLD_SECONDS,
        family_factory=lambda s: DiesHalfWay(s, holding, 2.0)))
    go = asyncio.Event()
    waiter = asyncio.create_task(run_create(maker, sa, registration_id, "key-dies-and-waiter-1", start=go))
    await asyncio.wait_for(holding.wait(), timeout=180)  # the first request holds the key row and the clan, uncommitted
    go.set()
    results = await within(first, waiter)
    no_errors([r for r in results if r != "INJECTED"])
    assert results == ["INJECTED", "201"], results  # the waiter ran as a fresh request, not as a replay of a failure
    one_business(await state(maker, registration_id))
    [row] = await keys_of(maker, sa.user_id)
    assert row.status == "COMPLETED"


async def test_an_expired_key_replaced_by_two_requests_at_once_gives_one_creation_and_one_replay(arena):
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id)
    [sa] = await make_sas(maker, 1)
    from datetime import datetime, timedelta, timezone

    async with maker() as s, s.begin():
        s.add(IdempotencyKey(idempotency_id=uuid.uuid4(), actor_id=sa.user_id, endpoint=use_cases.ENDPOINT, idempotency_key="key-expired-race-1",
                             request_hash="f" * 64, status="COMPLETED", response_status=201, response_body={"stale": True},
                             created_at=datetime.now(timezone.utc) - timedelta(days=9), expires_at=datetime.now(timezone.utc) - timedelta(days=2)))
    start, bodies = asyncio.Barrier(2), []
    results = await within(*[run_create(maker, sa, registration_id, "key-expired-race-1", start=start, bodies=bodies) for _ in range(2)])
    no_errors(results)
    assert sorted(results) == ["201", "201R"], results
    assert all("stale" not in b for b in bodies) and bodies[0] == bodies[1]
    one_business(await state(maker, registration_id))
    assert len(await keys_of(maker, sa.user_id)) == 1


# ------------------------------------------------------------------ different keys, one resource


async def test_two_keys_for_one_registration_one_business_and_the_loser_key_is_not_kept(arena):
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id)
    a, b = await make_sas(maker, 2)
    start = asyncio.Barrier(2)
    results = await within(run_create(maker, a, registration_id, "key-first-of-two-001", start=start),
                           run_create(maker, b, registration_id, "key-second-of-two-01", start=start))
    no_errors(results)
    assert sorted(results) == sorted(["201", "DUPLICATE_RESOURCE"]), results
    one_business(await state(maker, registration_id))
    winner, loser = (a, b) if results[0] == "201" else (b, a)
    assert len(await keys_of(maker, winner.user_id)) == 1 and await keys_of(maker, loser.user_id) == []  # the loser's key rolled back


async def test_two_registrations_with_the_same_clan_code_exactly_one_wins(arena):
    """Both pass the pre-check (neither is committed): the unique index of clan_code decides."""
    maker, plan_id = arena
    first, second = await make_registrations(maker, plan_id, 2)
    a, b = await make_sas(maker, 2)
    shared = code()
    start = asyncio.Barrier(2)
    results = await within(
        run_create(maker, a, first, "key-code-race-aaaa-1", body=BusinessCreateRequest(clan_code=shared), start=start),
        run_create(maker, b, second, "key-code-race-bbbb-1", body=BusinessCreateRequest(clan_code=shared), start=start))
    no_errors(results)
    assert sorted(results) == sorted(["201", "DUPLICATE_RESOURCE"]), results
    states = [await state(maker, first), await state(maker, second)]
    assert sorted(len(st["clans"]) for st in states) == [0, 1]
    async with maker() as s:
        assert (await s.execute(select(func.count()).select_from(Clan).where(Clan.clan_code == shared))).scalar_one() == 1


async def test_two_generated_codes_that_collide_under_a_real_race_are_drawn_again(arena, monkeypatch):
    maker, plan_id = arena
    first, second = await make_registrations(maker, plan_id, 2)
    a, b = await make_sas(maker, 2)
    collide = code("CLAN-")  # not under our purge prefix: the clans carry created_by of our users, which purge uses
    fresh = (code("CLAN-") for _ in itertools.count())
    draws = itertools.chain([collide, collide], fresh)
    monkeypatch.setattr(use_cases, "generate_clan_code", lambda: next(draws))
    start = asyncio.Barrier(2)
    results = await within(run_create(maker, a, first, "key-gen-collide-aaa-1", start=start),
                           run_create(maker, b, second, "key-gen-collide-bbb-1", start=start))
    no_errors(results)
    assert results == ["201", "201"], results  # the one that lost the index drew a new code inside its transaction
    codes = [(await state(maker, r))["clans"][0].clan_code for r in (first, second)]
    assert len(set(codes)) == 2 and collide in codes


# ------------------------------------------------------------------ a Business racing a review


async def test_the_business_waits_for_a_review_that_approves_and_then_succeeds(arena):
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id, status="PENDING")
    sa, reviewer = await make_sas(maker, 2)
    holding = asyncio.Event()

    async def review(decision, reason=None):
        async with maker() as s:
            await s.connection()
            await review_registration(db=SlowCommit(s, 3.0, holding), users=UserAccessRepository(s), family=FamilyRepository(s),
                                      principal=reviewer, registration_id=registration_id,
                                      body=RegistrationReviewRequest(decision=decision, reason=reason), client=CLIENT)
            return "ok"

    go = asyncio.Event()
    create = asyncio.create_task(run_create(maker, sa, registration_id, "key-after-approve-01", start=go))
    approving = asyncio.create_task(review("APPROVED"))
    await asyncio.wait_for(holding.wait(), timeout=180)  # the review holds the registration row, approved but uncommitted
    go.set()
    results = await within(approving, create)
    assert results == ["ok", "201"], results  # the create saw APPROVED once the review committed
    st = await state(maker, registration_id)
    one_business(st)
    assert st["status"] == "APPROVED"


async def test_the_business_waits_for_a_review_that_rejects_and_is_refused(arena):
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id, status="PENDING")
    sa, reviewer = await make_sas(maker, 2)
    holding = asyncio.Event()

    async def review():
        async with maker() as s:
            await s.connection()
            await review_registration(db=SlowCommit(s, 3.0, holding), users=UserAccessRepository(s), family=FamilyRepository(s),
                                      principal=reviewer, registration_id=registration_id,
                                      body=RegistrationReviewRequest(decision="REJECTED", reason="Missing documents"), client=CLIENT)
            return "ok"

    go = asyncio.Event()
    create = asyncio.create_task(run_create(maker, sa, registration_id, "key-after-reject-01", start=go))
    rejecting = asyncio.create_task(review())
    await asyncio.wait_for(holding.wait(), timeout=180)
    go.set()
    results = await within(rejecting, create)
    assert results == ["ok", "STATE_CONFLICT"], results
    st = await state(maker, registration_id)
    assert st["clans"] == [] and st["status"] == "REJECTED"
    assert await keys_of(maker, sa.user_id) == []  # the refused request left no key


async def test_a_business_that_saw_pending_is_refused_and_does_not_harm_the_review_that_waited_for_it(arena):
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id, status="PENDING")
    sa, reviewer = await make_sas(maker, 2)
    holding = asyncio.Event()
    create = asyncio.create_task(run_create(maker, sa, registration_id, "key-saw-pending-001", hold=0.0,
                                            family_factory=lambda s: LockedThenWait(s, holding, 3.0)))

    async def review():
        async with maker() as s:
            await s.connection()
            await asyncio.wait_for(holding.wait(), timeout=180)  # the create holds the registration lock and saw PENDING
            await review_registration(db=SlowCommit(s, 0.0), users=UserAccessRepository(s), family=FamilyRepository(s),
                                      principal=reviewer, registration_id=registration_id,
                                      body=RegistrationReviewRequest(decision="APPROVED"), client=CLIENT)
            return "ok"

    results = await within(create, asyncio.create_task(review()))
    assert results == ["STATE_CONFLICT", "ok"], results  # the create answered 409 and released the lock; the review went on
    st = await state(maker, registration_id)
    assert st["clans"] == [] and st["status"] == "APPROVED"
    assert await keys_of(maker, sa.user_id) == []


# ------------------------------------------------------------------ locks that must not be taken, and parallelism


async def test_the_users_row_of_the_sa_is_never_locked_while_a_business_is_being_created(arena):
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id)
    [sa] = await make_sas(maker, 1)
    holding = asyncio.Event()
    create = asyncio.create_task(run_create(maker, sa, registration_id, "key-users-not-locked-1", holding=holding, hold=LONG_HOLD))
    async with maker() as other:
        await other.connection()
        await asyncio.wait_for(holding.wait(), timeout=180)
        started = time.monotonic()
        await other.execute(update(User).where(User.user_id == sa.user_id).values(display_name="renamed during create"))
        await other.commit()
        waited = time.monotonic() - started
    assert waited < LONG_HOLD * 0.6, f"the user update waited {waited:.2f}s: the users row must not be locked"
    assert await asyncio.wait_for(create, timeout=60) == "201"
    one_business(await state(maker, registration_id))


async def test_different_registrations_are_created_in_parallel_without_blocking_one_another(arena):
    maker, plan_id = arena
    registrations = await make_registrations(maker, plan_id, 6)
    [sa] = await make_sas(maker, 1)
    marks: list = []
    assert await run_create(maker, sa, registrations[0], "key-parallel-single-1", hold=1.0, marks=marks) == "201"
    single = marks[0][1] - marks[0][0]  # one request alone, timed from the moment its connection is open
    start, marks = asyncio.Barrier(5), []
    results = await within(*[run_create(maker, sa, r, f"key-parallel-{i:04d}-abc", hold=1.0, start=start, marks=marks)
                             for i, r in enumerate(registrations[1:])])
    elapsed = max(end for _b, end in marks) - min(began for began, _e in marks)
    no_errors(results)
    assert results == ["201"] * 5
    assert elapsed < single * 2.5, f"five creations took {elapsed:.1f}s against {single:.1f}s for one: they were serialized"
    for r in registrations:
        one_business(await state(maker, r))
    assert len(await keys_of(maker, sa.user_id)) == 6
