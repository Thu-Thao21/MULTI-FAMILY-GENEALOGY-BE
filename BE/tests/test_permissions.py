from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.dialects import postgresql

from app.core.errors import AppError
from app.dependencies.auth import Principal
from app.dependencies.permissions import (
    ACTION_RULES,
    Action,
    ResourceScope,
    authorize,
    ensure_not_last_system_admin,
)
from app.models.user_access.repository import active_system_admin_roles_for_update_stmt
from app.schemas.errors import ErrorCode
from tests.fakes import NOW, FakeFamilyRepo, FakeUserAccessRepo, make_user


def principal(user) -> Principal:
    return Principal(user_id=user.user_id, session_id=uuid.uuid4(), status=user.status,
                     requires_password_change=False)


@pytest.fixture
def world():
    roles, family = FakeUserAccessRepo(), FakeFamilyRepo()
    return roles, family


async def check(world, user, action, scope) -> ErrorCode | None:
    roles, family = world
    try:
        await authorize(principal(user), action, scope, roles=roles, family=family)
        return None
    except AppError as exc:
        return exc.code


def owner_setup(world, clan_status="ACTIVE"):
    roles, family = world
    clan = family.add_clan(clan_status)
    bo = roles.add_user(make_user())
    roles.grant(bo, "BUSINESS_OWNER", clan.clan_id)
    family.add_owner(clan, bo)
    family.add_member(clan, bo)
    return clan, bo


# ----- System Admin -----


async def test_every_action_has_a_rule():
    assert set(ACTION_RULES) == set(Action)


async def test_sa_allowed_on_system_action(world):
    roles, _ = world
    sa = roles.add_user(make_user())
    roles.grant(sa, "SYSTEM_ADMIN")
    assert await check(world, sa, Action.REGISTRATION_REVIEW, ResourceScope.system()) is None


async def test_non_sa_forbidden_on_system_action(world):
    roles, _ = world
    user = roles.add_user(make_user())
    roles.grant(user, "BUSINESS_OWNER", uuid.uuid4())
    assert await check(world, user, Action.USER_LIST, ResourceScope.system()) is ErrorCode.FORBIDDEN


async def test_clan_scoped_or_revoked_sa_grant_does_not_count(world):
    roles, _ = world
    a = roles.add_user(make_user())
    roles.grant(a, "SYSTEM_ADMIN", uuid.uuid4())
    b = roles.add_user(make_user())
    roles.grant(b, "SYSTEM_ADMIN", revoked=True)
    for u in (a, b):
        assert await check(world, u, Action.CLAN_ACTIVATE, ResourceScope.system()) is ErrorCode.FORBIDDEN


async def test_unknown_action_is_denied(world):
    roles, _ = world
    sa = roles.add_user(make_user())
    roles.grant(sa, "SYSTEM_ADMIN")
    assert await check(world, sa, "person.private.read", ResourceScope.system()) is ErrorCode.FORBIDDEN


async def test_sa_gets_no_implicit_clan_access(world):
    roles, family = world
    clan = family.add_clan()
    sa = roles.add_user(make_user())
    roles.grant(sa, "SYSTEM_ADMIN")
    assert await check(world, sa, Action.CLAN_USERS_LIST, ResourceScope.clan(clan.clan_id)) is ErrorCode.NOT_FOUND


# ----- Business Owner -----


async def test_bo_allowed_in_own_clan(world):
    clan, bo = owner_setup(world)
    for action in (Action.CLAN_USERS_LIST, Action.CLAN_FA_PERMISSIONS_UPDATE):
        assert await check(world, bo, action, ResourceScope.clan(clan.clan_id)) is None


async def test_bo_of_clan_a_cannot_see_clan_b(world):
    _, family = world
    _clan_a, bo = owner_setup(world)
    clan_b = family.add_clan()
    assert await check(world, bo, Action.CLAN_USERS_LIST, ResourceScope.clan(clan_b.clan_id)) is ErrorCode.NOT_FOUND


async def test_nonexistent_clan_is_not_found(world):
    _, bo = owner_setup(world)
    assert await check(world, bo, Action.CLAN_USERS_LIST, ResourceScope.clan(uuid.uuid4())) is ErrorCode.NOT_FOUND


async def test_bo_role_without_active_ownership_is_forbidden(world):
    roles, family = world
    clan = family.add_clan()
    bo = roles.add_user(make_user())
    roles.grant(bo, "BUSINESS_OWNER", clan.clan_id)
    family.add_member(clan, bo)
    family.add_owner(clan, bo, ended_at=NOW - timedelta(days=1))
    assert await check(world, bo, Action.CLAN_USERS_LIST, ResourceScope.clan(clan.clan_id)) is ErrorCode.FORBIDDEN


async def test_ownership_without_bo_role_in_that_clan_is_forbidden(world):
    roles, family = world
    clan = family.add_clan()
    bo = roles.add_user(make_user())
    roles.grant(bo, "BUSINESS_OWNER", uuid.uuid4())  # role for another clan
    family.add_member(clan, bo)
    family.add_owner(clan, bo)
    assert await check(world, bo, Action.CLAN_USERS_LIST, ResourceScope.clan(clan.clan_id)) is ErrorCode.FORBIDDEN


async def test_bo_with_inactive_membership_is_not_found(world):
    roles, family = world
    clan = family.add_clan()
    bo = roles.add_user(make_user())
    roles.grant(bo, "BUSINESS_OWNER", clan.clan_id)
    family.add_owner(clan, bo)
    family.add_member(clan, bo, status="SUSPENDED")
    assert await check(world, bo, Action.CLAN_USERS_LIST, ResourceScope.clan(clan.clan_id)) is ErrorCode.NOT_FOUND


@pytest.mark.parametrize("status", ["PENDING", "SUSPENDED", "LOCKED", "EXPIRED", "INACTIVE"])
async def test_clan_must_be_active(world, status):
    clan, bo = owner_setup(world, clan_status=status)
    assert await check(world, bo, Action.CLAN_USERS_LIST, ResourceScope.clan(clan.clan_id)) is ErrorCode.FORBIDDEN


async def test_clan_rule_without_clan_scope_is_denied(world):
    _, bo = owner_setup(world)
    assert await check(world, bo, Action.CLAN_USERS_LIST, ResourceScope.system()) is ErrorCode.FORBIDDEN


# ----- Family Admin -----


def fa_setup(world, *, code="MEMBER_ACCOUNT_MANAGE", branch_id=None, revoked=False, member_status="ACTIVE"):
    roles, family = world
    clan = family.add_clan()
    fa = roles.add_user(make_user())
    family.add_member(clan, fa, status=member_status)
    family.add_fa(clan, fa, code, branch_id=branch_id, revoked=revoked)
    return clan, fa


async def test_fa_with_permission_clan_wide(world):
    clan, fa = fa_setup(world)
    assert await check(world, fa, Action.CLAN_USERS_LIST, ResourceScope.clan(clan.clan_id)) is None


async def test_fa_without_needed_permission_is_forbidden(world):
    clan, fa = fa_setup(world, code="TREE_VIEW")
    assert await check(world, fa, Action.CLAN_USERS_LIST, ResourceScope.clan(clan.clan_id)) is ErrorCode.FORBIDDEN


async def test_fa_revoked_assignment_is_forbidden(world):
    clan, fa = fa_setup(world, revoked=True)
    assert await check(world, fa, Action.CLAN_USERS_LIST, ResourceScope.clan(clan.clan_id)) is ErrorCode.FORBIDDEN


async def test_fa_without_active_membership_is_not_found(world):
    clan, fa = fa_setup(world, member_status="REVOKED")
    assert await check(world, fa, Action.CLAN_USERS_LIST, ResourceScope.clan(clan.clan_id)) is ErrorCode.NOT_FOUND


async def test_fa_branch_coverage(world):
    branch, other = uuid.uuid4(), uuid.uuid4()
    clan, fa = fa_setup(world, branch_id=branch)
    cid = clan.clan_id
    assert await check(world, fa, Action.CLAN_USERS_LIST, ResourceScope.clan(cid, branch)) is None
    assert await check(world, fa, Action.CLAN_USERS_LIST, ResourceScope.clan(cid, other)) is ErrorCode.FORBIDDEN
    assert await check(world, fa, Action.CLAN_USERS_LIST, ResourceScope.clan(cid)) is ErrorCode.FORBIDDEN


async def test_fa_cannot_update_fa_permissions(world):
    clan, fa = fa_setup(world, code="ADMIN_MANAGE")
    assert await check(world, fa, Action.CLAN_FA_PERMISSIONS_UPDATE, ResourceScope.clan(clan.clan_id)) is ErrorCode.FORBIDDEN


async def test_plain_member_is_forbidden(world):
    roles, family = world
    clan = family.add_clan()
    me = roles.add_user(make_user())
    roles.grant(me, "FAMILY_MEMBER", clan.clan_id)
    family.add_member(clan, me)
    assert await check(world, me, Action.CLAN_USERS_LIST, ResourceScope.clan(clan.clan_id)) is ErrorCode.FORBIDDEN


# ----- Last System Admin guard -----


def sa_world(n_active: int, extra_locked: int = 0):
    repo = FakeUserAccessRepo()
    sas = []
    for _ in range(n_active):
        u = repo.add_user(make_user())
        repo.grant(u, "SYSTEM_ADMIN")
        sas.append(u)
    for _ in range(extra_locked):
        u = repo.add_user(make_user("LOCKED"))
        repo.grant(u, "SYSTEM_ADMIN")
    return repo, sas


async def test_cannot_lock_last_active_sa_including_self():
    repo, (sa,) = sa_world(1, extra_locked=1)
    with pytest.raises(AppError) as exc:
        await ensure_not_last_system_admin(repo, sa.user_id, removes_admin_access=True)
    assert exc.value.code is ErrorCode.STATE_CONFLICT and exc.value.status_code == 409
    assert repo.calls[0] == "lock" and "count" in repo.calls  # lock happens before the count


async def test_can_lock_sa_when_another_active_sa_remains():
    repo, (a, _b) = sa_world(2)
    await ensure_not_last_system_admin(repo, a.user_id, removes_admin_access=True)


async def test_guard_ignores_non_sa_target_and_reactivation():
    repo, _ = sa_world(1)
    other = repo.add_user(make_user())
    await ensure_not_last_system_admin(repo, other.user_id, removes_admin_access=True)
    repo.calls.clear()
    await ensure_not_last_system_admin(repo, other.user_id, removes_admin_access=False)
    assert repo.calls == []  # no lock taken when nothing is removed


async def test_guard_allows_change_on_already_locked_sa():
    repo, _ = sa_world(0, extra_locked=1)
    locked = next(iter(repo.users.values()))
    await ensure_not_last_system_admin(repo, locked.user_id, removes_admin_access=True)


def test_sa_lock_statement_uses_for_update_on_user_roles():
    sql = str(active_system_admin_roles_for_update_stmt().compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE OF user_roles" in sql
    assert "user_roles.revoked_at IS NULL" in sql and "user_roles.clan_id IS NULL" in sql
