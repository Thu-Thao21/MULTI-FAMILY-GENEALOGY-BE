"""Guest registration under real concurrency (Mốc E, E3). COMMITS real rows.

Data uses the itest-conc- prefix (a plan ITEST-CONC-*, applicant e-mails itest-conc-reg-*) and
is deleted in finally, with the audit rows that name it. The DEV-* plans seeded on the dev
branch are never read, changed or deleted here: every test registers against its OWN plan.

What is protected, and by what:
  * N identical registrations at the same instant: the pre-check says "no" to all of them (the
    test FORCES that with a barrier right after the check), so only the unique index
    uq_registration_pending_same_applicant stands between the requests and N pending rows.
    Exactly one wins; the others get 409 DUPLICATE_RESOURCE (an IntegrityError mapped by the
    use case), never a 500, and leave no history and no audit row;
  * different applicants at the same instant do not block one another and do not deadlock.

Timing: a NEW session needs ~4 s to open its Neon connection. Every request therefore opens
its connection BEFORE it waits (`await s.connection()`), and the winner holds its transaction
for HOLD_SECONDS before COMMIT so the others really are inside the race (the lesson of the
Family Admin concurrency tests).
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.controllers.auth_access.use_cases import ClientInfo
from app.controllers.family_management.public_use_cases import create_registration
from app.core.errors import AppError
from app.core.tokens import hash_tracking_code
from app.models.family.entities import BusinessRegistration, RegistrationStatusHistory, SubscriptionPlan
from app.models.family.repository import FamilyRepository
from app.models.user_access.entities import AuditLog
from app.models.user_access.repository import UserAccessRepository
from app.schemas.business import BusinessRegistrationCreateRequest
from app.schemas.errors import ErrorCode

pytestmark = pytest.mark.concurrency

PLAN_PREFIX = "ITEST-CONC-"
EMAIL_PREFIX = "itest-conc-reg-"
HOLD_SECONDS = 1.5
DUPLICATE = str(ErrorCode.DUPLICATE_RESOURCE)
CLIENT = ClientInfo(ip_address=None, user_agent=None)


class SlowCommit:
    """Unit of work that holds the transaction open just before COMMIT."""

    def __init__(self, session, hold: float = HOLD_SECONDS) -> None:
        self._s = session
        self._hold = hold

    async def commit(self) -> None:
        await asyncio.sleep(self._hold)
        await self._s.commit()

    async def rollback(self) -> None:
        await self._s.rollback()


class BarrierAfterCheck(FamilyRepository):
    """After the duplicate check has ANSWERED, wait until every racer has its answer.

    All of them then hold "no pending registration" and all try to INSERT: without this the
    pre-check would serialize the race away and the index would never be tested.
    """

    def __init__(self, session, barrier: asyncio.Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    async def exists_pending_registration(self, *, email, clan_name):
        answer = await super().exists_pending_registration(email=email, clan_name=clan_name)
        await self._barrier.wait()
        return answer


async def purge(s) -> None:
    plan_ids = select(SubscriptionPlan.plan_id).where(SubscriptionPlan.code.startswith(PLAN_PREFIX))
    reg_ids = list((await s.execute(
        select(BusinessRegistration.registration_id).where(
            (BusinessRegistration.requested_plan_id.in_(plan_ids))
            | BusinessRegistration.representative_email.startswith(EMAIL_PREFIX)
        )
    )).scalars())
    if reg_ids:
        await s.execute(delete(AuditLog).where(AuditLog.entity_id.in_(reg_ids)))
        await s.execute(delete(BusinessRegistration).where(BusinessRegistration.registration_id.in_(reg_ids)))
    await s.execute(delete(SubscriptionPlan).where(SubscriptionPlan.code.startswith(PLAN_PREFIX)))


@pytest_asyncio.fixture(loop_scope="session")
async def committed_plan():
    """(session maker, plan_id): a committed ACTIVE plan of our own."""
    from app.core.config import settings

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as s, s.begin():
            await purge(s)  # leftovers of a crashed run (our prefix only)
            plan = SubscriptionPlan(
                plan_id=uuid.uuid4(), code=f"{PLAN_PREFIX}{uuid.uuid4().hex[:10].upper()}",
                name="Concurrency plan", price=Decimal("0.00"), billing_period_months=12, status="ACTIVE",
            )
            s.add(plan)
        yield maker, plan.plan_id
    finally:
        async with maker() as s, s.begin():
            await purge(s)
        await engine.dispose()


def body_of(plan_id, email: str, clan_name: str) -> BusinessRegistrationCreateRequest:
    return BusinessRegistrationCreateRequest(
        representative_name="Concurrency Applicant", representative_email=email,
        clan_name=clan_name, requested_plan_id=plan_id,
    )


def applicant() -> tuple[str, str]:
    t = uuid.uuid4().hex[:10]
    return f"{EMAIL_PREFIX}{t}@example.test", f"Itest Conc Clan {t}"


async def run_registration(maker, plan_id, email, clan_name, *, check_barrier=None, start_barrier=None, hold=HOLD_SECONDS):
    """One request: its own session, its connection opened first, the use case as the router calls it."""
    async with maker() as s:
        await s.connection()  # open the connection BEFORE waiting (see the module docstring)
        if start_barrier is not None:
            await start_barrier.wait()
        family = BarrierAfterCheck(s, check_barrier) if check_barrier is not None else FamilyRepository(s)
        try:
            await create_registration(
                db=SlowCommit(s, hold), users=UserAccessRepository(s), family=family,
                body=body_of(plan_id, email, clan_name), client=CLIENT,
            )
            return "ok"
        except AppError as exc:
            return str(exc.code)
        except Exception as exc:  # noqa: BLE001 - a driver error here is exactly what must not happen
            return f"ERROR:{type(exc).__name__}"


async def within(*coroutines, seconds: float = 180.0) -> list:
    return await asyncio.wait_for(asyncio.gather(*coroutines), timeout=seconds)


async def state(maker, plan_id, email: str) -> dict:
    async with maker() as s:
        rows = list((await s.execute(
            select(BusinessRegistration).where(BusinessRegistration.representative_email == email))).scalars())
        ids = [r.registration_id for r in rows]
        history = (await s.execute(select(func.count()).select_from(RegistrationStatusHistory).where(
            RegistrationStatusHistory.registration_id.in_(ids)))).scalar_one() if ids else 0
        audit = (await s.execute(select(func.count()).select_from(AuditLog).where(
            AuditLog.entity_id.in_(ids)))).scalar_one() if ids else 0
        return {"registrations": rows, "history": history, "audit": audit}


def no_errors(results) -> None:
    errors = [r for r in results if str(r).startswith("ERROR")]
    assert not errors, f"driver errors (deadlock, 500): {errors}"


# ------------------------------------------------------------------ identical applicants


async def test_identical_registrations_at_the_same_instant_exactly_one_wins_and_the_rest_get_409(committed_plan):
    """The pre-check answers "no" to every racer (forced by the barrier): only the index decides."""
    maker, plan_id = committed_plan
    email, clan = applicant()
    racers = 6
    barrier = asyncio.Barrier(racers)
    results = await within(*[
        run_registration(maker, plan_id, email, clan, check_barrier=barrier) for _ in range(racers)
    ])
    no_errors(results)
    assert sorted(results) == sorted(["ok"] + [DUPLICATE] * (racers - 1)), results
    st = await state(maker, plan_id, email)
    assert len(st["registrations"]) == 1  # exactly one pending row
    assert st["history"] == 1 and st["audit"] == 1  # the losers wrote nothing
    assert st["registrations"][0].status == "PENDING"


async def test_identical_registrations_without_any_help_never_create_two_or_fail_with_a_driver_error(committed_plan):
    """The natural race (no barrier): the check or the index stops the others, in either order."""
    maker, plan_id = committed_plan
    email, clan = applicant()
    results = await within(*[run_registration(maker, plan_id, email, clan) for _ in range(4)])
    no_errors(results)
    assert sorted(results) == sorted(["ok"] + [DUPLICATE] * 3), results
    st = await state(maker, plan_id, email)
    assert len(st["registrations"]) == 1 and st["history"] == 1 and st["audit"] == 1


async def test_the_same_applicant_in_another_case_races_to_the_same_single_winner(committed_plan):
    maker, plan_id = committed_plan
    email, clan = applicant()
    barrier = asyncio.Barrier(3)
    variants = [(email, clan), (email.upper(), clan.upper()), (email.title(), clan.lower())]
    results = await within(*[
        run_registration(maker, plan_id, e, c, check_barrier=barrier) for e, c in variants
    ])
    no_errors(results)
    assert sorted(results) == sorted(["ok", DUPLICATE, DUPLICATE]), results
    pending = []
    for e, _c in variants:
        pending += (await state(maker, plan_id, e))["registrations"]
    assert len(pending) == 1 and pending[0].status == "PENDING"


async def test_after_the_race_a_later_attempt_is_stopped_by_the_check_and_nothing_changes(committed_plan):
    maker, plan_id = committed_plan
    email, clan = applicant()
    barrier = asyncio.Barrier(3)
    first = await within(*[run_registration(maker, plan_id, email, clan, check_barrier=barrier) for _ in range(3)])
    no_errors(first)
    again = await run_registration(maker, plan_id, email, clan, hold=0.0)
    assert again == DUPLICATE
    st = await state(maker, plan_id, email)
    assert len(st["registrations"]) == 1 and st["history"] == 1 and st["audit"] == 1


async def test_the_winners_tracking_code_finds_exactly_its_own_row(committed_plan):
    """Only the hash of the winner's code is stored: a loser's code never reaches the table."""
    maker, plan_id = committed_plan
    email, clan = applicant()
    codes = []

    async def racer(barrier):
        async with maker() as s:
            await s.connection()
            try:
                response = await create_registration(
                    db=SlowCommit(s), users=UserAccessRepository(s),
                    family=BarrierAfterCheck(s, barrier), body=body_of(plan_id, email, clan), client=CLIENT)
                codes.append(response.tracking_code)
                return "ok"
            except AppError as exc:
                return str(exc.code)

    barrier = asyncio.Barrier(4)
    results = await within(*[racer(barrier) for _ in range(4)])
    assert sorted(results) == sorted(["ok"] + [DUPLICATE] * 3)
    [winner_code] = codes  # a loser raised before it could return a code
    [row] = (await state(maker, plan_id, email))["registrations"]
    assert row.tracking_code_hash == hash_tracking_code(winner_code)


# ------------------------------------------------------------------ different applicants


async def test_different_applicants_at_the_same_instant_all_succeed_without_blocking_or_deadlock(committed_plan):
    maker, plan_id = committed_plan
    applicants = [applicant() for _ in range(6)]
    start = asyncio.Barrier(len(applicants))
    results = await within(*[
        run_registration(maker, plan_id, email, clan, start_barrier=start) for email, clan in applicants
    ])
    no_errors(results)
    assert results == ["ok"] * 6
    for email, _clan in applicants:
        st = await state(maker, plan_id, email)
        assert len(st["registrations"]) == 1 and st["history"] == 1 and st["audit"] == 1


async def test_a_mixed_race_has_one_winner_per_applicant_and_no_deadlock(committed_plan):
    """Three identical + three distinct applicants all at once."""
    maker, plan_id = committed_plan
    same_email, same_clan = applicant()
    distinct = [applicant() for _ in range(3)]
    check = asyncio.Barrier(6)
    jobs = [run_registration(maker, plan_id, same_email, same_clan, check_barrier=check) for _ in range(3)]
    jobs += [run_registration(maker, plan_id, e, c, check_barrier=check) for e, c in distinct]
    results = await within(*jobs)
    no_errors(results)
    assert results[3:] == ["ok"] * 3  # the distinct applicants all won
    assert sorted(results[:3]) == sorted(["ok", DUPLICATE, DUPLICATE])
    assert len((await state(maker, plan_id, same_email))["registrations"]) == 1
    for e, _c in distinct:
        assert len((await state(maker, plan_id, e))["registrations"]) == 1
