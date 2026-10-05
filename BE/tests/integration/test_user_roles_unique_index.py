"""uq_active_user_role_scope on the real DB.

DB definition:  UNIQUE (user_id, role_id, clan_id) WHERE revoked_at IS NULL
Because PostgreSQL treats NULLs as distinct, rows with clan_id IS NULL (system scope,
i.e. every SYSTEM_ADMIN grant) are never "equal", so the index does not stop a duplicate
active SA grant. See docs/known_issues.md KI-03.
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


async def test_db_accepts_duplicate_system_admin_grant_current_behaviour(session, world):
    """Pins today's behaviour (KI-03): no IntegrityError for a second active SA grant.

    If the lead adds the migration (NULLS NOT DISTINCT), this test will fail: delete it
    and drop the xfail marker on the test below.
    """
    sa = await world.user()
    await world.grant(sa, "SYSTEM_ADMIN")
    await world.grant(sa, "SYSTEM_ADMIN")  # accepted
    repo = UserAccessRepository(session)
    grants = [g for g in await repo.list_active_role_grants(sa.user_id) if g[0] == "SYSTEM_ADMIN"]
    assert len(grants) == 2


@pytest.mark.xfail(
    strict=True,
    reason="KI-03: uq_active_user_role_scope ignores clan_id IS NULL, so the DB allows a "
    "duplicate active SYSTEM_ADMIN grant. Needs a lead-approved migration "
    "(NULLS NOT DISTINCT or a partial unique index on (user_id, role_id) WHERE clan_id IS NULL).",
)
async def test_db_should_reject_duplicate_system_admin_grant(session, world):
    sa = await world.user()
    await world.grant(sa, "SYSTEM_ADMIN")
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await world.grant(sa, "SYSTEM_ADMIN")
