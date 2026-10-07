"""PATCH /admin/users/{id}/status under real concurrency (Mốc F). COMMITS real rows.

Same rules as test_last_sa_concurrency.py: itest-conc-* users only, cleaned in finally,
skipped when the database has other ACTIVE System Admins. These go through the real use
case, so they cover the whole lock order, not only the guard:

    1. every active SA grant, ORDER BY user_id        (lock_active_system_admin_roles)
    2. the target user row, FOR NO KEY UPDATE         (get_user_for_update)

Why the order matters, and why NO KEY UPDATE: two SAs lock each other. With the target
row taken first and FOR UPDATE, request 1 holds user B and then inserts an audit row
whose actor FK needs FOR KEY SHARE on user A, which request 2 holds FOR UPDATE (and
vice versa): a deadlock. test_control_* reproduces exactly that to prove this file
detects it.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select, update

from app.controllers.auth_access.use_cases import ClientInfo
from app.controllers.auth_access.user_admin_use_cases import update_user_status
from app.core.errors import AppError
from app.dependencies.auth import Principal
from app.models.user_access.entities import AuditLog, User
from app.models.user_access.repository import UserAccessRepository
from app.schemas.errors import ErrorCode
from app.schemas.users import UserStatusUpdateRequest
from tests.integration.diagnostics import describe_error, is_error
from tests.integration.test_last_sa_concurrency import (  # noqa: F401  (fixture)
    two_committed_sas,
)

pytestmark = pytest.mark.concurrency

HOLD_SECONDS = 0.5  # keep the winner's transaction open so the loser must wait


class SlowCommit:
    """Unit of work that holds the transaction open just before COMMIT."""

    def __init__(self, session) -> None:
        self._s = session

    async def commit(self) -> None:
        await asyncio.sleep(HOLD_SECONDS)
        await self._s.commit()

    async def rollback(self) -> None:
        await self._s.rollback()


async def _attempt(maker, barrier, actor_id, target_id, status: str = "LOCKED"):
    """One real request. Returns 'ok', the AppError code, or describe_error(): 'ERROR:<type>:<sqlstate>:<message>'."""
    async with maker() as s:
        try:
            await barrier.wait()
            await update_user_status(
                db=SlowCommit(s),
                users=UserAccessRepository(s),
                principal=Principal(actor_id, uuid.uuid4(), "ACTIVE", False),
                user_id=target_id,
                body=UserStatusUpdateRequest(status=status, reason="itest-concurrency"),
                client=ClientInfo(None, None),
            )
            return "ok"
        except AppError as exc:
            return str(exc.code)
        except Exception as exc:  # noqa: BLE001 - a deadlock must be reported by name
            return describe_error(exc)


async def _race(maker, *requests):
    barrier = asyncio.Barrier(len(requests))
    return await asyncio.wait_for(
        asyncio.gather(*(_attempt(maker, barrier, *r) for r in requests)), timeout=90
    )


async def _active_among(maker, ids) -> int:
    async with maker() as s:
        return int(
            (
                await s.execute(
                    select(func.count()).select_from(User).where(
                        User.user_id.in_(ids), User.status == "ACTIVE"
                    )
                )
            ).scalar_one()
        )


async def _audit_count(maker, ids) -> int:
    async with maker() as s:
        return int(
            (
                await s.execute(
                    select(func.count()).select_from(AuditLog).where(AuditLog.entity_id.in_(ids))
                )
            ).scalar_one()
        )


@pytest.mark.parametrize("status", ["LOCKED", "SUSPENDED", "DISABLED"])
async def test_two_sas_locking_each_other_one_wins_one_conflicts_no_deadlock(two_committed_sas, status):
    maker, a_id, b_id = two_committed_sas
    results = await _race(maker, (a_id, b_id, status), (b_id, a_id, status))

    assert sorted(results) == sorted(["ok", str(ErrorCode.STATE_CONFLICT)]), results
    assert not any(is_error(r) for r in results)  # no deadlock, no 500
    assert await _active_among(maker, [a_id, b_id]) == 1
    assert await _audit_count(maker, [a_id, b_id]) == 1  # only the winner is audited


async def test_two_requests_locking_the_same_last_sa_are_both_refused(two_committed_sas):
    maker, a_id, b_id = two_committed_sas
    async with maker() as s, s.begin():  # B is already out: A is the last active SA
        await s.execute(update(User).where(User.user_id == b_id).values(status="LOCKED"))

    results = await _race(maker, (a_id, a_id, "LOCKED"), (a_id, a_id, "SUSPENDED"))

    assert results == [str(ErrorCode.STATE_CONFLICT)] * 2, results
    assert await _active_among(maker, [a_id]) == 1
    assert await _audit_count(maker, [a_id, b_id]) == 0


async def test_unlocking_one_sa_while_the_other_locks_it_is_serialized(two_committed_sas):
    """A non-blocking change (no SA lock) racing a blocking one must not deadlock either."""
    maker, a_id, b_id = two_committed_sas
    async with maker() as s, s.begin():
        await s.execute(update(User).where(User.user_id == b_id).values(status="SUSPENDED"))

    # Request 1 (actor A) re-activates B; request 2 (actor A) tries to lock A, the only
    # other SA. Whatever the order, the end state keeps at least one ACTIVE SA.
    results = await _race(maker, (a_id, b_id, "ACTIVE"), (a_id, a_id, "LOCKED"))

    assert not any(is_error(r) for r in results), results
    assert await _active_among(maker, [a_id, b_id]) >= 1


async def test_control_user_row_first_with_for_update_deadlocks(two_committed_sas, monkeypatch):
    """Control: the OLD plan (target row first, FOR UPDATE, no SA lock first) deadlocks.

    If this test ever stops seeing a deadlock, the concurrency tests above no longer prove
    anything about lock ordering and must be re-examined.
    """

    async def no_sa_lock(self) -> None:
        return None

    async def user_row_for_update(self, user_id):
        stmt = (
            select(User)
            .where(User.user_id == user_id)
            .with_for_update()  # FOR UPDATE: conflicts with the FK KEY SHARE of audit inserts
            .execution_options(populate_existing=True)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    monkeypatch.setattr(UserAccessRepository, "lock_active_system_admin_roles", no_sa_lock)
    monkeypatch.setattr(UserAccessRepository, "get_user_for_update", user_row_for_update)
    maker, a_id, b_id = two_committed_sas
    results = await _race(maker, (a_id, b_id, "LOCKED"), (b_id, a_id, "LOCKED"))

    assert any(r.startswith("ERROR:DeadlockDetected:40P01:") for r in results), results  # sqlstate 40P01
