"""Family Admin lifecycle under real concurrency (Mốc F2). COMMITS real rows.

Data uses the itest-conc- prefix (users, clan code ITEST-CONC-*) and is deleted in finally,
together with the audit rows that name it (audit FKs are ON DELETE SET NULL).

What is protected, and by what:
  * two simultaneous appointments of the SAME user: both queue on the clan_memberships row
    (FOR NO KEY UPDATE) and the second one sees the first one's committed assignment -> 409.
    Since migration 0002 (KI-08) the unique index uq_family_admin_active_assignment is the
    last line of defence: a request that gets past the lock still ends in IntegrityError ->
    409, never in two active assignments (see the control test below);
  * PUT permissions vs DELETE (and DELETE vs POST): all of them lock the user's assignment
    rows (FOR NO KEY UPDATE, ORDER BY assignment_id) before reading or writing.
No request locks the users row, so the audit FK to the actor cannot deadlock (Mốc F).

Timing: a NEW session needs ~4 s to open its Neon connection. Every request therefore
acquires its connection BEFORE it waits for a barrier or an event (`await s.connection()`),
otherwise the "second" request would only start after the first one had already committed
and the race would be a fiction (a mutation check proved exactly that).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.controllers.auth_access.use_cases import ClientInfo
from app.controllers.auth_access.user_admin_use_cases import (
    assign_family_admin,
    revoke_family_admin,
    update_fa_permissions,
)
from app.core.errors import AppError
from app.dependencies.auth import Principal
from app.models.family.entities import (
    Clan,
    ClanMembership,
    ClanOwnershipHistory,
    FamilyAdminAssignment,
    FamilyAdminPermission,
)
from app.models.family.repository import FamilyRepository
from app.models.user_access.entities import AuditLog, Role, User, UserRole
from app.models.user_access.repository import UserAccessRepository
from app.schemas.errors import ErrorCode
from app.schemas.users import FamilyAdminAssignRequest, FamilyAdminPermissionsUpdateRequest

pytestmark = pytest.mark.concurrency

PREFIX = "itest-conc-"
CLAN_PREFIX = "ITEST-CONC-"
HOLD_SECONDS = 1.5   # default time a request keeps its locks before COMMIT
LONG_HOLD_SECONDS = 3.5  # for tests where the second request needs several queries first
RESUME_TIMEOUT_SECONDS = 10.0  # PUT waits at most this long for the competing DELETE to finish
FA_CODE = "MEMBER_ACCOUNT_MANAGE"
CONFLICT = str(ErrorCode.STATE_CONFLICT)
NOT_FOUND = str(ErrorCode.NOT_FOUND)


class SlowCommit:
    """Unit of work that holds the transaction open just before COMMIT.

    `entered` is set as soon as commit() is called, so another request can be started at the
    moment this one holds its locks but has not committed yet.
    """

    def __init__(
        self, session, entered: asyncio.Event | None = None, hold: float = HOLD_SECONDS
    ) -> None:
        self._s = session
        self._entered = entered
        self._hold = hold

    async def commit(self) -> None:
        if self._entered is not None:
            self._entered.set()
        await asyncio.sleep(self._hold)
        await self._s.commit()

    async def rollback(self) -> None:
        await self._s.rollback()


async def purge(s) -> None:
    clan_ids = list((await s.execute(select(Clan.clan_id).where(Clan.clan_code.startswith(CLAN_PREFIX)))).scalars())
    user_ids = list((await s.execute(select(User.user_id).where(User.firebase_uid.startswith(PREFIX)))).scalars())
    assignment_ids = []
    if clan_ids:
        assignment_ids = list(
            (await s.execute(select(FamilyAdminAssignment.assignment_id).where(FamilyAdminAssignment.clan_id.in_(clan_ids)))).scalars()
        )
    conditions = []
    if clan_ids:
        conditions.append(AuditLog.clan_id.in_(clan_ids))
    if user_ids:
        conditions += [AuditLog.actor_id.in_(user_ids), AuditLog.entity_id.in_(user_ids)]
    if assignment_ids:
        conditions.append(AuditLog.entity_id.in_(assignment_ids))
    if conditions:
        await s.execute(delete(AuditLog).where(or_(*conditions)))
    # Clans first (ownership, memberships, assignments, permissions and clan roles cascade),
    # then users (clan_ownership_history.user_id has no ON DELETE action).
    await s.execute(delete(Clan).where(Clan.clan_code.startswith(CLAN_PREFIX)))
    await s.execute(delete(User).where(User.firebase_uid.startswith(PREFIX)))


@pytest_asyncio.fixture(loop_scope="session")
async def committed():
    """A committed ACTIVE clan with its Business Owner and one ACTIVE plain member."""
    from app.core.config import settings

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as s, s.begin():
            await purge(s)  # leftovers of a crashed run (our prefix only)
            role_ids = {
                code: (await s.execute(select(Role.role_id).where(Role.code == code))).scalar_one()
                for code in ("BUSINESS_OWNER", "FAMILY_ADMIN")
            }
            clan = Clan(clan_id=uuid.uuid4(), clan_code=f"{CLAN_PREFIX}{uuid.uuid4().hex[:10].upper()}",
                        name="Concurrency clan", status="ACTIVE")
            s.add(clan)
            users = {}
            for label in ("bo", "target"):
                uid = uuid.uuid4()
                users[label] = User(
                    user_id=uid, firebase_uid=f"{PREFIX}{label}-{uid.hex[:8]}",
                    email=f"{PREFIX}{label}-{uid.hex[:8]}@example.test",
                    display_name=f"Concurrency {label}", status="ACTIVE",
                )
                s.add(users[label])
            await s.flush()
            from datetime import datetime, timezone

            t = datetime.now(timezone.utc)
            s.add(ClanOwnershipHistory(ownership_id=uuid.uuid4(), clan_id=clan.clan_id,
                                       user_id=users["bo"].user_id, started_at=t))
            for label in ("bo", "target"):
                s.add(ClanMembership(membership_id=uuid.uuid4(), clan_id=clan.clan_id,
                                     user_id=users[label].user_id, status="ACTIVE", joined_at=t))
            s.add(UserRole(user_id=users["bo"].user_id, role_id=role_ids["BUSINESS_OWNER"],
                           clan_id=clan.clan_id))
        yield maker, clan.clan_id, users["bo"].user_id, users["target"].user_id, role_ids["FAMILY_ADMIN"]
    finally:
        async with maker() as s, s.begin():
            await purge(s)
        await engine.dispose()


# ----- helpers to set up and inspect committed state -----


async def make_fa(maker, clan_id, bo_id, target_id, role_id, codes, *, with_role=True):
    async with maker() as s, s.begin():
        assignment = FamilyAdminAssignment(assignment_id=uuid.uuid4(), user_id=target_id,
                                           clan_id=clan_id, assigned_by=bo_id)
        s.add(assignment)
        await s.flush()
        for code in codes:
            s.add(FamilyAdminPermission(assignment_id=assignment.assignment_id, permission_code=code))
        if with_role:
            s.add(UserRole(user_id=target_id, role_id=role_id, clan_id=clan_id))
    return assignment.assignment_id


async def state(maker, clan_id, target_id) -> dict:
    async with maker() as s:
        active = list((await s.execute(
            select(FamilyAdminAssignment).where(
                FamilyAdminAssignment.clan_id == clan_id, FamilyAdminAssignment.user_id == target_id,
                FamilyAdminAssignment.revoked_at.is_(None)))).scalars())
        everything = list((await s.execute(
            select(FamilyAdminAssignment).where(
                FamilyAdminAssignment.clan_id == clan_id, FamilyAdminAssignment.user_id == target_id))).scalars())
        # permission rows that belong to a REVOKED assignment must not exist
        orphans = int((await s.execute(
            select(func.count()).select_from(FamilyAdminPermission)
            .join(FamilyAdminAssignment, FamilyAdminAssignment.assignment_id == FamilyAdminPermission.assignment_id)
            .where(FamilyAdminAssignment.clan_id == clan_id, FamilyAdminAssignment.user_id == target_id,
                   FamilyAdminAssignment.revoked_at.is_not(None)))).scalar_one())
        roles = int((await s.execute(
            select(func.count()).select_from(UserRole).join(Role, Role.role_id == UserRole.role_id)
            .where(UserRole.user_id == target_id, UserRole.clan_id == clan_id,
                   Role.code == "FAMILY_ADMIN", UserRole.revoked_at.is_(None)))).scalar_one())
        audits = list((await s.execute(
            select(AuditLog.action).where(AuditLog.clan_id == clan_id))).scalars())
    return {"active": len(active), "all": len(everything), "revoked_with_permissions": orphans,
            "active_roles": roles, "audit": sorted(audits)}


def principal(bo_id) -> Principal:
    return Principal(bo_id, uuid.uuid4(), "ACTIVE", False)


CLIENT = ClientInfo(None, None)


async def _guarded(coro):
    """'ok' on success, the AppError code, or 'ERROR:<driver error name>' (e.g. a deadlock)."""
    try:
        await coro
        return "ok"
    except AppError as exc:
        return str(exc.code)
    except Exception as exc:  # noqa: BLE001 - a deadlock or a 500 must be reported by name
        return f"ERROR:{type(getattr(exc, 'orig', exc)).__name__}"


async def run_assign(
    maker, clan_id, bo_id, target_id, *, barrier=None, wait_for=None, entered=None, codes=(),
    hold=HOLD_SECONDS,
):
    async with maker() as s:
        await s.connection()  # open the connection BEFORE waiting (see module docstring)
        if barrier is not None:
            await barrier.wait()
        if wait_for is not None:
            await wait_for.wait()
        return await _guarded(assign_family_admin(
            db=SlowCommit(s, entered, hold), users=UserAccessRepository(s),
            family=FamilyRepository(s), principal=principal(bo_id), clan_id=clan_id,
            body=FamilyAdminAssignRequest(user_id=target_id, permission_codes=list(codes)),
            client=CLIENT))


async def run_revoke(
    maker, clan_id, bo_id, target_id, *, barrier=None, wait_for=None, entered=None,
    done=None, hold=HOLD_SECONDS,
):
    async with maker() as s:
        await s.connection()
        if barrier is not None:
            await barrier.wait()
        if wait_for is not None:
            await wait_for.wait()
        try:
            return await _guarded(revoke_family_admin(
                db=SlowCommit(s, entered, hold), users=UserAccessRepository(s),
                family=FamilyRepository(s), principal=principal(bo_id), clan_id=clan_id,
                user_id=target_id, client=CLIENT))
        finally:
            if done is not None:
                done.set()


class PausingFamily(FamilyRepository):
    """After the assignment rows are locked and read, announce it and pause (PUT only).

    The pause ends as soon as `resume` is set (the competing request finished) or after
    RESUME_TIMEOUT_SECONDS. With the lock in place the competitor is blocked by it, so the
    pause simply runs to the timeout; without the lock the competitor finishes first, which
    is precisely the interleaving that corrupts data.
    """

    def __init__(self, session, paused: asyncio.Event, resume: asyncio.Event) -> None:
        super().__init__(session)
        self._paused = paused
        self._resume = resume

    async def list_assignment_permission_codes(self, assignment_id):
        codes = await super().list_assignment_permission_codes(assignment_id)
        self._paused.set()
        try:
            await asyncio.wait_for(self._resume.wait(), timeout=RESUME_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            pass
        return codes


async def run_put(maker, clan_id, bo_id, target_id, codes, paused, resume, *, entered=None, wait_for=None):
    async with maker() as s:
        await s.connection()
        if wait_for is not None:
            await wait_for.wait()
        return await _guarded(update_fa_permissions(
            db=SlowCommit(s, entered), users=UserAccessRepository(s),
            family=PausingFamily(s, paused, resume), principal=principal(bo_id),
            clan_id=clan_id, user_id=target_id,
            body=FamilyAdminPermissionsUpdateRequest(permission_codes=codes), client=CLIENT))


async def within(*coros, timeout=120):
    return await asyncio.wait_for(asyncio.gather(*coros), timeout=timeout)


def no_errors(results) -> None:
    assert not any(str(r).startswith("ERROR:") for r in results), results  # no deadlock, no 500


# ----- POST vs POST -----


@pytest.mark.parametrize("role_row_exists", [False, True], ids=["fresh-user", "role-row-already-active"])
async def test_two_simultaneous_appointments_of_one_user_only_one_wins(committed, role_row_exists):
    maker, clan_id, bo_id, target_id, role_id = committed
    if role_row_exists:
        # With an active FAMILY_ADMIN row already there, the unique ROLE index cannot help:
        # the membership lock (and, on a migrated DB, the assignment index) is what decides.
        async with maker() as s, s.begin():
            s.add(UserRole(user_id=target_id, role_id=role_id, clan_id=clan_id))
    barrier = asyncio.Barrier(2)
    results = await within(
        run_assign(maker, clan_id, bo_id, target_id, barrier=barrier, codes=[FA_CODE]),
        run_assign(maker, clan_id, bo_id, target_id, barrier=barrier, codes=["PERSON_VIEW"]),
    )
    assert sorted(results) == sorted(["ok", CONFLICT]), results
    st = await state(maker, clan_id, target_id)
    assert st["active"] == 1 and st["active_roles"] == 1
    assert st["audit"] == ["family_admin.assign"]  # only the winner is audited


async def test_control_without_the_membership_lock_the_unique_index_still_lets_only_one_win(
    committed, monkeypatch
):
    """Control (KI-08 closed by migration 0002): drop the membership lock and run the same race.

    Before the migration this left TWO active assignments (the role index could not help
    because the role row already existed). Now the second INSERT waits for the first
    transaction and fails on uq_family_admin_active_assignment: IntegrityError, mapped to 409.
    The test proves the DB layer works on its own; it fails on a database without the index.
    """
    maker, clan_id, bo_id, target_id, role_id = committed
    async with maker() as s, s.begin():
        s.add(UserRole(user_id=target_id, role_id=role_id, clan_id=clan_id))

    async def membership_without_lock(self, clan_id, user_id):
        return await self.get_membership(clan_id, user_id)

    monkeypatch.setattr(FamilyRepository, "lock_membership", membership_without_lock)
    barrier = asyncio.Barrier(2)
    results = await within(
        run_assign(maker, clan_id, bo_id, target_id, barrier=barrier),
        run_assign(maker, clan_id, bo_id, target_id, barrier=barrier),
    )
    assert sorted(results) == sorted(["ok", CONFLICT]), results
    st = await state(maker, clan_id, target_id)
    assert st["active"] == 1 and st["all"] == 1
    assert st["audit"] == ["family_admin.assign"]  # only the winner is audited


# ----- PUT vs DELETE -----


async def test_put_then_delete_race_leaves_no_permissions_on_the_revoked_assignment(committed):
    """PUT locks the assignment and pauses mid-way; DELETE starts while it is paused. DELETE
    must wait for the lock, then revoke everything the PUT just wrote."""
    maker, clan_id, bo_id, target_id, role_id = committed
    await make_fa(maker, clan_id, bo_id, target_id, role_id, ["PERSON_VIEW"])
    paused, delete_done = asyncio.Event(), asyncio.Event()
    results = await within(
        run_put(maker, clan_id, bo_id, target_id, [FA_CODE, "TREE_VIEW"], paused, delete_done),
        run_revoke(maker, clan_id, bo_id, target_id, wait_for=paused, done=delete_done, hold=0.1),
    )
    assert results == ["ok", "ok"], results
    st = await state(maker, clan_id, target_id)
    assert st["active"] == 0 and st["active_roles"] == 0
    assert st["revoked_with_permissions"] == 0  # the invariant a missing lock would break
    assert st["audit"] == ["family_admin.permissions.update", "family_admin.revoke"]


async def test_delete_then_put_race_ends_in_404_not_in_permissions_on_a_revoked_row(committed):
    maker, clan_id, bo_id, target_id, role_id = committed
    await make_fa(maker, clan_id, bo_id, target_id, role_id, ["PERSON_VIEW"])
    entered, paused, delete_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    results = await within(
        run_revoke(maker, clan_id, bo_id, target_id, entered=entered, done=delete_done),
        run_put(maker, clan_id, bo_id, target_id, [FA_CODE], paused, delete_done, wait_for=entered),
    )
    assert results == ["ok", NOT_FOUND], results
    st = await state(maker, clan_id, target_id)
    assert st["active"] == 0 and st["revoked_with_permissions"] == 0 and st["active_roles"] == 0
    assert st["audit"] == ["family_admin.revoke"]


# ----- DELETE vs POST -----


async def test_delete_and_reappoint_race_ends_with_exactly_one_active_assignment_and_role(committed):
    """POST starts while DELETE holds its locks. POST must queue behind DELETE, see the
    revoked state and succeed with a NEW assignment (never a 409 on stale data)."""
    maker, clan_id, bo_id, target_id, role_id = committed
    old_id = await make_fa(maker, clan_id, bo_id, target_id, role_id, [FA_CODE])
    entered = asyncio.Event()
    results = await within(
        run_revoke(maker, clan_id, bo_id, target_id, entered=entered, hold=LONG_HOLD_SECONDS),
        run_assign(maker, clan_id, bo_id, target_id, wait_for=entered, codes=["PERSON_VIEW"]),
    )
    assert results == ["ok", "ok"], results
    st = await state(maker, clan_id, target_id)
    assert st["active"] == 1 and st["all"] == 2  # the old one stays as history
    assert st["active_roles"] == 1 and st["revoked_with_permissions"] == 0
    assert st["audit"] == ["family_admin.assign", "family_admin.revoke"]
    async with maker() as s:
        new = (await s.execute(select(FamilyAdminAssignment.assignment_id).where(
            FamilyAdminAssignment.clan_id == clan_id, FamilyAdminAssignment.user_id == target_id,
            FamilyAdminAssignment.revoked_at.is_(None)))).scalar_one()
    assert new != old_id


async def test_two_simultaneous_revokes_one_wins_the_other_is_404(committed):
    maker, clan_id, bo_id, target_id, role_id = committed
    await make_fa(maker, clan_id, bo_id, target_id, role_id, [FA_CODE])
    entered = asyncio.Event()
    results = await within(
        run_revoke(maker, clan_id, bo_id, target_id, entered=entered),
        run_revoke(maker, clan_id, bo_id, target_id, wait_for=entered, hold=0.1),
    )
    assert sorted(results) == sorted(["ok", NOT_FOUND]), results
    st = await state(maker, clan_id, target_id)
    assert st["active"] == 0 and st["revoked_with_permissions"] == 0
    assert st["audit"] == ["family_admin.revoke"]


async def test_delete_and_appoint_started_at_the_same_instant_never_deadlock(committed):
    """No staggering: both requests start together and take their locks at the same time.

    This is the test that sees two requests taking the same locks in opposite orders
    (membership first vs assignments first). POST sends no codes, so its first query is the
    membership lock, in step with DELETE's first query (the assignment lock). Either outcome is
    legal; the end state must be consistent and no request may fail with a driver error.
    """
    maker, clan_id, bo_id, target_id, role_id = committed
    await make_fa(maker, clan_id, bo_id, target_id, role_id, [FA_CODE])
    barrier = asyncio.Barrier(2)
    results = await within(
        run_revoke(maker, clan_id, bo_id, target_id, barrier=barrier),
        run_assign(maker, clan_id, bo_id, target_id, barrier=barrier),
    )
    no_errors(results)
    assert results[0] == "ok" and results[1] in ("ok", CONFLICT), results
    st = await state(maker, clan_id, target_id)
    assert st["active"] in (0, 1) and st["active"] == st["active_roles"], st
    assert st["revoked_with_permissions"] == 0
