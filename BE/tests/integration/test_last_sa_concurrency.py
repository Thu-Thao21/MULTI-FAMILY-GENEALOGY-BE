"""Two real, concurrent transactions try to remove the last two System Admins.

These tests COMMIT. They use itest-conc-* users only and delete them in finally. They
need a database with no other ACTIVE System Admin (the guard counts all of them); if
there is one (for example the dev seed SA), the tests skip instead of guessing.

Marker: concurrency (also integration).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.errors import AppError
from app.dependencies.permissions import ensure_not_last_system_admin
from app.models.user_access.entities import AuditLog, Role, User, UserRole
from app.models.user_access.repository import UserAccessRepository
from app.schemas.errors import ErrorCode

pytestmark = pytest.mark.concurrency

PREFIX = "itest-conc-"
DOMAIN = "@example.test"
HOLD_SECONDS = 0.5  # keep the winner's transaction open so the loser must wait on the lock


def _is_ours(column):
    return column.startswith(PREFIX)


async def purge_prefixed_users(s) -> None:
    """Delete itest-conc-* users AND the audit rows that name them (audit FKs are
    ON DELETE SET NULL, so deleting only the users would leave orphan audit rows)."""
    ids = list((await s.execute(select(User.user_id).where(_is_ours(User.firebase_uid)))).scalars())
    if ids:
        await s.execute(delete(AuditLog).where(or_(AuditLog.entity_id.in_(ids), AuditLog.actor_id.in_(ids))))
    await s.execute(delete(User).where(_is_ours(User.firebase_uid)))


@pytest_asyncio.fixture(loop_scope="session")
async def two_committed_sas():
    from app.core.config import settings

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    ids: list[uuid.UUID] = []
    try:
        async with maker() as s, s.begin():
            # Leftovers from a crashed earlier run (our prefix only).
            await purge_prefixed_users(s)
            others = await UserAccessRepository(s).count_active_system_admins()
            if others:
                pytest.skip(
                    f"{others} other ACTIVE System Admin(s) exist in this database; the "
                    "'last SA' race cannot be set up without touching them."
                )
            role_id = (await s.execute(select(Role.role_id).where(Role.code == "SYSTEM_ADMIN"))).scalar_one()
            for label in ("a", "b"):
                uid = uuid.uuid4()
                ids.append(uid)
                s.add(
                    User(
                        user_id=uid,
                        firebase_uid=f"{PREFIX}{label}-{uid.hex[:8]}",
                        email=f"{PREFIX}{label}-{uid.hex[:8]}{DOMAIN}",
                        display_name="Concurrency SA",
                        status="ACTIVE",
                    )
                )
            await s.flush()
            for uid in ids:
                s.add(UserRole(user_id=uid, role_id=role_id, clan_id=None))
        yield maker, ids[0], ids[1]
    finally:
        async with maker() as s, s.begin():
            await purge_prefixed_users(s)
        await engine.dispose()


async def _attempt(maker, barrier, target_id: uuid.UUID, op: str):
    """One request: guard, write, hold, commit. Returns 'ok' or the AppError code."""
    async with maker() as s:
        try:
            async with s.begin():
                await barrier.wait()
                await ensure_not_last_system_admin(
                    UserAccessRepository(s), target_id, removes_admin_access=True
                )
                if op == "lock":
                    await s.execute(update(User).where(User.user_id == target_id).values(status="LOCKED"))
                else:  # revoke the SYSTEM_ADMIN role
                    sa_role = select(Role.role_id).where(Role.code == "SYSTEM_ADMIN").scalar_subquery()
                    await s.execute(
                        update(UserRole)
                        .where(
                            UserRole.user_id == target_id,
                            UserRole.role_id == sa_role,
                            UserRole.clan_id.is_(None),
                            UserRole.revoked_at.is_(None),
                        )
                        .values(revoked_at=datetime.now(timezone.utc))
                    )
                await asyncio.sleep(HOLD_SECONDS)
            return "ok"
        except AppError as exc:
            return exc.code


async def _race(maker, a_id, b_id, op):
    barrier = asyncio.Barrier(2)
    return await asyncio.wait_for(
        asyncio.gather(
            _attempt(maker, barrier, a_id, op),  # request 1 removes SA a
            _attempt(maker, barrier, b_id, op),  # request 2 removes SA b
        ),
        timeout=60,
    )


async def _remaining_active(maker, ids) -> int:
    async with maker() as s:
        sa_role = select(Role.role_id).where(Role.code == "SYSTEM_ADMIN").scalar_subquery()
        stmt = (
            select(func.count(func.distinct(UserRole.user_id)))
            .join(User, User.user_id == UserRole.user_id)
            .where(
                UserRole.user_id.in_(ids),
                UserRole.role_id == sa_role,
                UserRole.clan_id.is_(None),
                UserRole.revoked_at.is_(None),
                User.status == "ACTIVE",
            )
        )
        return int((await s.execute(stmt)).scalar_one())


@pytest.mark.parametrize("op", ["lock", "revoke_role"])
async def test_two_concurrent_requests_cannot_remove_the_last_two_sas(two_committed_sas, op):
    maker, a_id, b_id = two_committed_sas
    results = await _race(maker, a_id, b_id, op)

    assert sorted(map(str, results)) == sorted(["ok", str(ErrorCode.STATE_CONFLICT)]), results
    assert await _remaining_active(maker, [a_id, b_id]) == 1


async def test_control_without_the_row_lock_both_requests_succeed(two_committed_sas, monkeypatch):
    """Control: with the FOR UPDATE removed the same race leaves ZERO active SAs.

    Shows the test above really exercises the lock rather than passing by timing.
    """

    async def no_lock(self) -> None:
        return None

    monkeypatch.setattr(UserAccessRepository, "lock_active_system_admin_roles", no_lock)
    maker, a_id, b_id = two_committed_sas
    results = await _race(maker, a_id, b_id, "lock")

    assert results == ["ok", "ok"]
    assert await _remaining_active(maker, [a_id, b_id]) == 0
