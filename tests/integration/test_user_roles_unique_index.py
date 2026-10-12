"""uq_active_user_role_scope on the real DB (after migration 0002_integrity_constraints).

DB definition:  UNIQUE NULLS NOT DISTINCT (user_id, role_id, clan_id) WHERE revoked_at IS NULL
NULLS NOT DISTINCT makes a NULL clan_id (system scope, i.e. every SYSTEM_ADMIN grant) count as
one value, so a duplicate active SA grant is rejected like a duplicate clan grant (KI-03).
These tests need the migration applied to the database they run against.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.user_access.repository import UserAccessRepository


async def test_duplicate_active_grant_in_a_clan_is_rejected(session, world):
    clan, user = await world.clan(), await world.user()
    await world.grant(user, "FAMILY_MEMBER", clan)
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await world.grant(user, "FAMILY_MEMBER", clan)


async def test_regrant_after_revoke_is_allowed(session, world):
    clan, user = await world.clan(), await world.user()
    await world.grant(user, "FAMILY_MEMBER", clan, revoked=True)
    await world.grant(user, "FAMILY_MEMBER", clan)


async def test_same_role_in_two_clans_is_allowed(session, world):
    a, b, user = await world.clan(), await world.clan(), await world.user()
    await world.grant(user, "FAMILY_MEMBER", a)
    await world.grant(user, "FAMILY_MEMBER", b)


async def test_db_rejects_duplicate_system_admin_grant(session, world):
    """KI-03 closed: a second active SYSTEM_ADMIN grant (clan_id NULL) is rejected."""
    sa = await world.user()
    await world.grant(sa, "SYSTEM_ADMIN")
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await world.grant(sa, "SYSTEM_ADMIN")
    repo = UserAccessRepository(session)
    grants = [g for g in await repo.list_active_role_grants(sa.user_id) if g[0] == "SYSTEM_ADMIN"]
    assert len(grants) == 1


async def test_system_admin_regrant_after_revoke_is_allowed(session, world):
    sa = await world.user()
    await world.grant(sa, "SYSTEM_ADMIN", revoked=True)
    await world.grant(sa, "SYSTEM_ADMIN")
    await world.grant(sa, "SYSTEM_ADMIN", revoked=True)  # revoked history may repeat


async def test_two_users_may_each_hold_system_admin(session, world):
    a, b = await world.user(), await world.user()
    await world.grant(a, "SYSTEM_ADMIN")
    await world.grant(b, "SYSTEM_ADMIN")


async def test_system_scope_and_clan_scope_of_the_same_role_do_not_collide(session, world):
    """clan_id NULL and a real clan_id are different values, even for the same user and role."""
    clan, user = await world.clan(), await world.user()
    await world.grant(user, "SYSTEM_ADMIN")
    await world.grant(user, "SYSTEM_ADMIN", clan)
