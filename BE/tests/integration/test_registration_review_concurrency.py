"""SA review of a registration under real concurrency (Mốc E, E4). COMMITS real rows.

Data uses the itest-conc-rv- prefix (a plan ITEST-CONC-RV-*, users itest-conc-rv-*, applicant
e-mails itest-conc-rv-reg-*) and is deleted in finally, with the audit rows that name it. The
DEV-* plans seeded on the dev branch are never read as an expectation, changed or deleted:
every test works on its OWN plan, and a last test proves the DEV-* count did not move.

What is protected, and by what:
  * two reviewers at the same time: the registration row is locked FOR NO KEY UPDATE first; the
    second reviewer waits, re-reads the committed status and gets 409. Exactly one history row
    and one audit row, whatever the mix of decisions. No driver error, no deadlock;
  * a reader (the detail) is never blocked by a review in progress and sees the committed state;
  * the users row of the reviewer is never locked: another session can change that user while
    the review is mid-transaction (FOR UPDATE here would deadlock; Mốc F lesson).

Timing: a NEW session needs ~4 s to open its Neon connection, so every request opens its
connection BEFORE it waits, and the winner holds its transaction for HOLD_SECONDS before COMMIT
so the others really are queued behind the lock.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.db.postgres import make_engine
from tests.integration.diagnostics import describe_error, is_error

from app.controllers.auth_access.use_cases import ClientInfo
from app.controllers.family_management.registration_admin_use_cases import (
    get_registration_detail,
    review_registration,
)
from app.core.errors import AppError
from app.dependencies.auth import Principal
from app.models.family.entities import (
    BusinessRegistration,
    RegistrationStatusHistory,
    SubscriptionPlan,
)
from app.models.family.repository import FamilyRepository
from app.models.user_access.entities import AuditLog, User
from app.models.user_access.repository import UserAccessRepository
from app.schemas.business import RegistrationReviewRequest
from app.schemas.errors import ErrorCode

pytestmark = pytest.mark.concurrency

PLAN_PREFIX = "ITEST-CONC-RV-"
USER_PREFIX = "itest-conc-rv-"
EMAIL_PREFIX = "itest-conc-rv-reg-"
HOLD_SECONDS = 1.5
LONG_HOLD = 6.0  # the "is it blocked?" tests: a few Neon round trips must be far shorter than the hold
CONFLICT = str(ErrorCode.STATE_CONFLICT)
CLIENT = ClientInfo(ip_address=None, user_agent=None)


class SlowCommit:
    """Unit of work that holds the transaction open just before COMMIT (and says so)."""

    def __init__(self, session, hold: float = HOLD_SECONDS, holding: asyncio.Event | None = None) -> None:
        self._s, self._hold, self._holding = session, hold, holding

    async def commit(self) -> None:
        if self._holding is not None:
            self._holding.set()  # the lock is held and the rows are written, not yet committed
        await asyncio.sleep(self._hold)
        await self._s.commit()

    async def rollback(self) -> None:
        await self._s.rollback()


async def purge(s) -> None:
    plan_ids = select(SubscriptionPlan.plan_id).where(SubscriptionPlan.code.startswith(PLAN_PREFIX))
    reg_ids = list((await s.execute(
        select(BusinessRegistration.registration_id).where(
            BusinessRegistration.requested_plan_id.in_(plan_ids)
            | BusinessRegistration.representative_email.startswith(EMAIL_PREFIX)))).scalars())
    user_ids = list((await s.execute(select(User.user_id).where(User.firebase_uid.startswith(USER_PREFIX)))).scalars())
    if reg_ids:
        await s.execute(delete(AuditLog).where(AuditLog.entity_id.in_(reg_ids)))
        await s.execute(delete(BusinessRegistration).where(BusinessRegistration.registration_id.in_(reg_ids)))
    if user_ids:
        await s.execute(delete(AuditLog).where(AuditLog.actor_id.in_(user_ids)))
        await s.execute(delete(User).where(User.user_id.in_(user_ids)))
    await s.execute(delete(SubscriptionPlan).where(SubscriptionPlan.code.startswith(PLAN_PREFIX)))


async def dev_plan_count(maker) -> int:
    async with maker() as s:
        return (await s.execute(select(func.count()).select_from(SubscriptionPlan)
                                .where(SubscriptionPlan.code.startswith("DEV-")))).scalar_one()


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
            plan = SubscriptionPlan(
                plan_id=uuid.uuid4(), code=f"{PLAN_PREFIX}{uuid.uuid4().hex[:10].upper()}",
                name="Review concurrency plan", price=Decimal("0.00"), billing_period_months=12, status="ACTIVE")
            s.add(plan)
        yield maker, plan.plan_id
        assert await dev_plan_count(maker) == dev_before  # the seeded DEV-* plans were never touched
    finally:
        async with maker() as s, s.begin():
            await purge(s)
        await engine.dispose()


async def make_reviewers(maker, count: int) -> list[Principal]:
    out = []
    async with maker() as s, s.begin():
        for _ in range(count):
            tag = uuid.uuid4().hex[:12]
            user = User(user_id=uuid.uuid4(), firebase_uid=f"{USER_PREFIX}{tag}", email=f"{USER_PREFIX}{tag}@example.test",
                        display_name="Concurrency SA", status="ACTIVE", first_login_required=False)
            s.add(user)
            out.append(Principal(user_id=user.user_id, session_id=uuid.uuid4(), status="ACTIVE", requires_password_change=False))
    return out


async def make_registrations(maker, plan_id, count: int = 1) -> list[uuid.UUID]:
    out = []
    async with maker() as s, s.begin():
        for _ in range(count):
            tag = uuid.uuid4().hex[:12]
            row = BusinessRegistration(
                registration_id=uuid.uuid4(), requested_plan_id=plan_id, representative_name="Concurrency Applicant",
                representative_email=f"{EMAIL_PREFIX}{tag}@example.test", clan_name=f"Itest Conc Review {tag}",
                status="PENDING", tracking_code_hash=uuid.uuid4().hex + uuid.uuid4().hex)
            s.add(row)
            out.append(row.registration_id)
    return out


async def run_review(maker, principal, registration_id, decision, *, start=None, hold=HOLD_SECONDS, holding=None, marks=None):
    """One request: its own session, its connection opened first, the use case as the router calls it."""
    async with maker() as s:
        await s.connection()  # open the connection BEFORE waiting
        if start is not None:
            await start.wait()
        began = time.monotonic()  # after the connection is open and the barrier released
        reason = "Missing documents" if decision == "REJECTED" else None
        try:
            await review_registration(
                db=SlowCommit(s, hold, holding), users=UserAccessRepository(s), family=FamilyRepository(s),
                principal=principal, registration_id=registration_id,
                body=RegistrationReviewRequest(decision=decision, reason=reason), client=CLIENT)
            if marks is not None:
                marks.append((began, time.monotonic()))
            return "ok"
        except AppError as exc:
            return str(exc.code)
        except Exception as exc:  # noqa: BLE001 - a driver error here is exactly what must not happen
            return describe_error(exc)


async def within(*coroutines, seconds: float = 180.0) -> list:
    return await asyncio.wait_for(asyncio.gather(*coroutines), timeout=seconds)


def no_errors(results) -> None:
    errors = [r for r in results if is_error(r)]
    assert not errors, f"driver errors (deadlock, 500, or a dropped connection: see the sqlstate): {errors}"


async def state(maker, registration_id) -> dict:
    async with maker() as s:
        row = (await s.execute(select(BusinessRegistration).where(BusinessRegistration.registration_id == registration_id))).scalar_one()
        history = list((await s.execute(select(RegistrationStatusHistory).where(
            RegistrationStatusHistory.registration_id == registration_id))).scalars())
        audit = list((await s.execute(select(AuditLog).where(AuditLog.entity_id == registration_id))).scalars())
        return {"row": row, "history": history, "audit": audit}


def assert_one_consistent_decision(st, winner: Principal, decision: str) -> None:
    row = st["row"]
    assert row.status == decision and row.reviewed_by == winner.user_id and row.reviewed_at is not None
    assert (row.rejection_reason is not None) == (decision == "REJECTED")  # only a rejection reason is public
    [history], [audit] = st["history"], st["audit"]
    assert (history.from_status, history.to_status, history.changed_by) == ("PENDING", decision, winner.user_id)
    assert (audit.actor_id, audit.new_data["status"], audit.reason) == (winner.user_id, decision, None)


# ------------------------------------------------------------------ the same registration


async def test_two_reviewers_approve_at_the_same_instant_exactly_one_wins(arena):
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id)
    a, b = await make_reviewers(maker, 2)
    start = asyncio.Barrier(2)
    results = await within(run_review(maker, a, registration_id, "APPROVED", start=start),
                           run_review(maker, b, registration_id, "APPROVED", start=start))
    no_errors(results)
    assert sorted(results) == sorted(["ok", CONFLICT]), results
    winner = (a, b)[results.index("ok")]
    assert_one_consistent_decision(await state(maker, registration_id), winner, "APPROVED")


async def test_approve_against_reject_one_decision_wins_and_the_loser_changes_nothing(arena):
    maker, plan_id = arena
    for _round in range(2):
        [registration_id] = await make_registrations(maker, plan_id)
        a, b = await make_reviewers(maker, 2)
        start = asyncio.Barrier(2)
        results = await within(run_review(maker, a, registration_id, "APPROVED", start=start),
                               run_review(maker, b, registration_id, "REJECTED", start=start))
        no_errors(results)
        assert sorted(results) == sorted(["ok", CONFLICT]), results
        winner, decision = ((a, "APPROVED"), (b, "REJECTED"))[results.index("ok")]  # results follow the call order
        assert_one_consistent_decision(await state(maker, registration_id), winner, decision)


async def test_six_mixed_reviewers_exactly_one_succeeds_and_nobody_deadlocks(arena):
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id)
    reviewers = await make_reviewers(maker, 6)
    decisions = ["APPROVED", "REJECTED"] * 3
    start = asyncio.Barrier(6)
    results = await within(*[run_review(maker, p, registration_id, d, start=start) for p, d in zip(reviewers, decisions)])
    no_errors(results)
    assert sorted(results) == sorted(["ok"] + [CONFLICT] * 5), results
    index = results.index("ok")
    assert_one_consistent_decision(await state(maker, registration_id), reviewers[index], decisions[index])


async def test_a_review_that_arrives_after_the_winner_committed_is_409_and_writes_nothing(arena):
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id)
    a, b = await make_reviewers(maker, 2)
    assert await run_review(maker, a, registration_id, "REJECTED", hold=0.0) == "ok"
    assert await run_review(maker, b, registration_id, "APPROVED", hold=0.0) == CONFLICT
    assert_one_consistent_decision(await state(maker, registration_id), a, "REJECTED")


# ------------------------------------------------------------------ readers and other rows are not blocked


async def test_a_detail_read_during_a_review_is_not_blocked_and_sees_the_committed_state(arena):
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id)
    [a] = await make_reviewers(maker, 1)
    holding = asyncio.Event()
    review = asyncio.create_task(run_review(maker, a, registration_id, "APPROVED", holding=holding, hold=LONG_HOLD))
    async with maker() as reader:
        await reader.connection()
        await asyncio.wait_for(holding.wait(), timeout=120)  # the row is locked and written, not committed
        started = time.monotonic()
        during = await get_registration_detail(family=FamilyRepository(reader), registration_id=registration_id)
        waited = time.monotonic() - started
    assert waited < LONG_HOLD * 0.6, f"the reader waited {waited:.2f}s: a read must not queue behind the lock"
    assert during.status == "PENDING" and during.status_history == []  # the committed state, not the open transaction
    assert await asyncio.wait_for(review, timeout=60) == "ok"
    async with maker() as reader:
        after = await get_registration_detail(family=FamilyRepository(reader), registration_id=registration_id)
    assert after.status == "APPROVED" and [h.to_status for h in after.status_history] == ["APPROVED"]


async def test_the_reviewers_user_row_is_never_locked_during_a_review(arena):
    """FOR UPDATE on users would make this UPDATE wait for the review to finish (and deadlock with
    the foreign keys of audit_logs and reviewed_by, which need KEY SHARE: Mốc F lesson)."""
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id)
    [a] = await make_reviewers(maker, 1)
    holding = asyncio.Event()
    review = asyncio.create_task(run_review(maker, a, registration_id, "REJECTED", holding=holding, hold=LONG_HOLD))
    async with maker() as other:
        await other.connection()
        await asyncio.wait_for(holding.wait(), timeout=120)
        started = time.monotonic()
        await other.execute(update(User).where(User.user_id == a.user_id).values(display_name="renamed during review"))
        await other.commit()
        waited = time.monotonic() - started
    assert waited < LONG_HOLD * 0.6, f"the user update waited {waited:.2f}s: the users row must not be locked"
    assert await asyncio.wait_for(review, timeout=60) == "ok"
    assert_one_consistent_decision(await state(maker, registration_id), a, "REJECTED")


async def test_different_registrations_are_reviewed_in_parallel_without_blocking_one_another(arena):
    maker, plan_id = arena
    registrations = await make_registrations(maker, plan_id, 6)
    reviewers = await make_reviewers(maker, 6)
    # One review alone sets the yardstick (its own round trips plus the 1.0s hold), timed from the
    # moment its connection is open: the ~4s Neon connection set-up is not what is being measured.
    marks: list = []
    assert await run_review(maker, reviewers[0], registrations[0], "APPROVED", hold=1.0, marks=marks) == "ok"
    single = marks[0][1] - marks[0][0]
    # Five at once on five different rows must take about as long as one, not five times as long.
    start = asyncio.Barrier(5)
    marks = []
    results = await within(*[run_review(maker, p, r, "APPROVED", start=start, hold=1.0, marks=marks)
                             for p, r in zip(reviewers[1:], registrations[1:])])
    elapsed = max(end for _b, end in marks) - min(began for began, _e in marks)
    no_errors(results)
    assert results == ["ok"] * 5
    assert elapsed < single * 2.5, f"five reviews took {elapsed:.1f}s against {single:.1f}s for one: they were serialized"
    for registration_id, principal in zip(registrations, reviewers):
        assert_one_consistent_decision(await state(maker, registration_id), principal, "APPROVED")


async def test_a_loser_leaves_the_registration_unlocked_for_the_next_request(arena):
    """After the race, a plain query on the row is immediate: the 409 releases its lock."""
    maker, plan_id = arena
    [registration_id] = await make_registrations(maker, plan_id)
    a, b = await make_reviewers(maker, 2)
    start = asyncio.Barrier(2)
    await within(run_review(maker, a, registration_id, "APPROVED", start=start, hold=0.5),
                 run_review(maker, b, registration_id, "REJECTED", start=start, hold=0.5))
    async with maker() as s:
        started = time.monotonic()
        await s.execute(text("SELECT 1 FROM business_registrations WHERE registration_id = :i FOR NO KEY UPDATE NOWAIT"),
                        {"i": registration_id})  # NOWAIT: it would raise if a lock were left behind
        assert time.monotonic() - started < 5.0
        await s.rollback()
