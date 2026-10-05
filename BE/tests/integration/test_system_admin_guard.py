"""Last-System-Admin guard on the real DB (single transaction, rolled back).

The race itself is tested in test_last_sa_concurrency.py.
"""

from __future__ import annotations

import pytest

from app.core.errors import AppError
from app.dependencies.permissions import ensure_not_last_system_admin
from app.models.user_access.repository import UserAccessRepository
from app.schemas.errors import ErrorCode


async def _guard(session, user, *, removes=True):
    await ensure_not_last_system_admin(
        UserAccessRepository(session), user.user_id, removes_admin_access=removes
    )


async def _conflict(session, user) -> bool:
    try:
        await _guard(session, user)
        return False
    except AppError as exc:
        assert exc.code is ErrorCode.STATE_CONFLICT
        return True


async def _only_sa(world) -> object:
    await world.isolate_system_admins()
    sa = await world.user()
    await world.grant(sa, "SYSTEM_ADMIN")
    return sa


async def test_cannot_lock_last_active_sa_including_self(session, world):
    sa = await _only_sa(world)
    assert await _conflict(session, sa)


async def test_can_lock_sa_when_another_active_sa_remains(session, world):
    sa = await _only_sa(world)
    other = await world.user()
    await world.grant(other, "SYSTEM_ADMIN")
    assert not await _conflict(session, sa)


async def test_other_sa_must_be_active_to_count(session, world):
    sa = await _only_sa(world)
    locked = await world.user("LOCKED")
    await world.grant(locked, "SYSTEM_ADMIN")
    assert await _conflict(session, sa)


async def test_revoked_or_clan_scoped_sa_grants_do_not_count(session, world):
    sa = await _only_sa(world)
    revoked, scoped = await world.user(), await world.user()
    await world.grant(revoked, "SYSTEM_ADMIN", revoked=True)
    await world.grant(scoped, "SYSTEM_ADMIN", await world.clan())
    assert await _conflict(session, sa)


async def test_guard_passes_for_non_sa_target_and_for_non_removing_change(session, world):
    sa = await _only_sa(world)
    plain = await world.user()
    assert not await _conflict(session, plain)
    await _guard(session, sa, removes=False)  # e.g. reactivation: no check


async def test_guard_passes_when_target_is_already_not_active(session, world):
    await world.isolate_system_admins()
    locked = await world.user("LOCKED")
    await world.grant(locked, "SYSTEM_ADMIN")
    assert not await _conflict(session, locked)


async def test_duplicate_sa_grants_of_one_user_do_not_inflate_the_count(session, world):
    """Two active grants for the same user (the DB allows it, see KI-03) are still one SA."""
    sa = await _only_sa(world)
    await world.grant(sa, "SYSTEM_ADMIN")  # duplicate active grant
    repo = UserAccessRepository(session)
    assert await repo.count_active_system_admins() == 1
    assert await _conflict(session, sa)


async def test_lock_statement_is_valid_on_postgres(session, world):
    sa = await _only_sa(world)
    await UserAccessRepository(session).lock_active_system_admin_roles()
    assert await UserAccessRepository(session).has_active_role(sa.user_id, "SYSTEM_ADMIN", clan_id=None)
