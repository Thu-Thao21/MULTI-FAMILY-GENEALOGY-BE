"""Auth + authorization wiring over HTTP (real dependencies, real DB, rolled back)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.dependencies.auth import Principal
from app.dependencies.permissions import Action, ResourceScope, authorize
from app.core.errors import AppError
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from app.schemas.errors import ErrorCode
from tests.integration.factory import bearer, now

FA_CODE = "MEMBER_ACCOUNT_MANAGE"
NON_ACTIVE_CLAN_STATUSES = ["PENDING", "SUSPENDED", "EXPIRED", "LOCKED", "INACTIVE"]


def code_of(response) -> str:
    return response.json()["error"]["code"]


async def get(client, path, token=None):
    return await client.get(path, headers=bearer(token) if token else {})


# ----- session / account state over HTTP -----


async def test_missing_bearer_is_unauthenticated(client):
    r = await get(client, "/api/v1/auth/me")
    assert (r.status_code, code_of(r)) == (401, "UNAUTHENTICATED")


async def test_revoked_and_expired_tokens_are_401(client, world):
    user = await world.user()
    revoked = await world.session_for(user, revoked=True)
    expired = await world.session_for(user, created_ago=timedelta(hours=9), expires_in=timedelta(hours=-1))
    for token in (revoked, expired, "garbage"):
        r = await get(client, "/api/v1/auth/me", token)
        assert (r.status_code, code_of(r)) == (401, "SESSION_INVALID")


async def test_locked_user_is_403_even_on_auth_me(client, world):
    token = await world.session_for(await world.user("LOCKED"))
    r = await get(client, "/api/v1/auth/me", token)
    assert (r.status_code, code_of(r)) == (403, "ACCOUNT_BLOCKED")


async def test_expired_temporary_password_is_403(client, world):
    user = await world.user(
        "PENDING",
        cred=dict(
            must_change_password=True,
            failed_login_count=0,
            temporary_password_expires_at=now() - timedelta(minutes=1),
        ),
    )
    r = await get(client, "/api/v1/auth/me", await world.session_for(user))
    assert (r.status_code, code_of(r)) == (403, "TEMPORARY_PASSWORD_EXPIRED")


# ----- restricted session -----


async def _restricted_token(world, kind: str, *, system_admin: bool = False) -> str:
    if kind == "pending_temp_password":
        user = await world.user(
            "PENDING",
            cred=dict(
                must_change_password=True,
                failed_login_count=0,
                temporary_password_expires_at=now() + timedelta(days=1),
            ),
        )
    else:
        user = await world.user(first_login_required=True)
    if system_admin:
        await world.grant(user, "SYSTEM_ADMIN")
    return await world.session_for(user)


@pytest.mark.parametrize("kind", ["pending_temp_password", "first_login_required"])
async def test_restricted_session_reaches_only_the_three_auth_routes(client, world, kind):
    h = bearer(await _restricted_token(world, kind))
    me = await client.get("/api/v1/auth/me", headers=h)
    assert me.status_code == 200 and me.json()["restricted"] is True
    assert (await client.post("/api/v1/auth/change-password", headers=h)).status_code == 204
    assert (await client.post("/api/v1/auth/logout", headers=h)).status_code == 204

    other_clan = uuid.uuid4()
    for path in ("/api/v1/admin/users", f"/api/v1/clans/{other_clan}/users"):
        r = await client.get(path, headers=h)
        assert (r.status_code, code_of(r)) == (403, "PASSWORD_CHANGE_REQUIRED")


async def test_restricted_system_admin_is_still_blocked_on_business_routes(client, world):
    h = bearer(await _restricted_token(world, "first_login_required", system_admin=True))
    r = await client.get("/api/v1/admin/users", headers=h)
    assert (r.status_code, code_of(r)) == (403, "PASSWORD_CHANGE_REQUIRED")


# ----- System Admin -----


async def test_sa_can_use_system_route(client, world):
    sa = await world.user()
    await world.grant(sa, "SYSTEM_ADMIN")
    r = await get(client, "/api/v1/admin/users", await world.session_for(sa))
    assert r.status_code == 200


async def test_non_sa_is_forbidden_on_system_route(client, world):
    user = await world.user()
    r = await get(client, "/api/v1/admin/users", await world.session_for(user))
    assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")


async def test_clan_scoped_or_revoked_sa_grant_does_not_count(client, world):
    clan = await world.clan()
    scoped, revoked = await world.user(), await world.user()
    await world.grant(scoped, "SYSTEM_ADMIN", clan)
    await world.grant(revoked, "SYSTEM_ADMIN", revoked=True)
    for user in (scoped, revoked):
        r = await get(client, "/api/v1/admin/users", await world.session_for(user))
        assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")


async def test_sa_has_no_implicit_clan_access(client, world):
    clan, _bo = await world.business_owner()
    sa = await world.user()
    await world.grant(sa, "SYSTEM_ADMIN")
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(sa))
    assert (r.status_code, code_of(r)) == (404, "NOT_FOUND")


# ----- tenant isolation -----


async def test_bo_reads_own_clan(client, world):
    clan, bo = await world.business_owner()
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(bo))
    assert r.status_code == 200


async def test_bo_of_clan_a_cannot_see_clan_b(client, world):
    _clan_a, bo_a = await world.business_owner()
    clan_b, _bo_b = await world.business_owner()
    token = await world.session_for(bo_a)
    r = await get(client, f"/api/v1/clans/{clan_b.clan_id}/users", token)
    assert (r.status_code, code_of(r)) == (404, "NOT_FOUND")
    r = await client.put(
        f"/api/v1/clans/{clan_b.clan_id}/admins/{uuid.uuid4()}/permissions", headers=bearer(token)
    )
    assert (r.status_code, code_of(r)) == (404, "NOT_FOUND")


async def test_nonexistent_or_malformed_clan_is_404(client, world):
    _clan, bo = await world.business_owner()
    token = await world.session_for(bo)
    for clan_id in (uuid.uuid4(), "not-a-uuid"):
        r = await get(client, f"/api/v1/clans/{clan_id}/users", token)
        assert (r.status_code, code_of(r)) == (404, "NOT_FOUND")


async def test_plain_member_in_own_clan_is_403(client, world):
    clan, _bo = await world.business_owner()
    member = await world.user()
    await world.grant(member, "FAMILY_MEMBER", clan)
    await world.member(clan, member)
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(member))
    assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")


# ----- clan must be ACTIVE; /auth/* is not affected -----


@pytest.mark.parametrize("status", NON_ACTIVE_CLAN_STATUSES)
async def test_inactive_clan_blocks_bo_and_fa_but_not_auth_routes(client, world, status):
    clan, bo = await world.business_owner(status)
    fa = await world.user()
    await world.member(clan, fa)
    await world.fa(clan, fa, FA_CODE)
    for user in (bo, fa):
        token = await world.session_for(user)
        r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", token)
        assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")
        assert (await get(client, "/api/v1/auth/me", token)).status_code == 200
        assert (await client.post("/api/v1/auth/logout", headers=bearer(token))).status_code == 204


# ----- Business Owner needs role + ownership + membership -----


async def test_bo_without_role_is_forbidden(client, world):
    clan = await world.clan()
    user = await world.user()
    await world.owner(clan, user)
    await world.member(clan, user)
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(user))
    assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")


async def test_bo_with_revoked_role_is_forbidden(client, world):
    clan = await world.clan()
    user = await world.user()
    await world.grant(user, "BUSINESS_OWNER", clan, revoked=True)
    await world.owner(clan, user)
    await world.member(clan, user)
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(user))
    assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")


async def test_bo_role_for_another_clan_does_not_count(client, world):
    clan, other = await world.clan(), await world.clan()
    user = await world.user()
    await world.grant(user, "BUSINESS_OWNER", other)
    await world.owner(clan, user)
    await world.member(clan, user)
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(user))
    assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")


async def test_bo_with_ended_ownership_is_forbidden(client, world):
    clan = await world.clan()
    user = await world.user()
    await world.grant(user, "BUSINESS_OWNER", clan)
    await world.owner(clan, user, ended=True)
    await world.member(clan, user)
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(user))
    assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")


async def test_bo_role_while_someone_else_owns_the_clan_is_forbidden(client, world):
    clan, _real_owner = await world.business_owner()
    impostor = await world.user()
    await world.grant(impostor, "BUSINESS_OWNER", clan)
    await world.member(clan, impostor)
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(impostor))
    assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")


@pytest.mark.parametrize("status", ["INVITED", "SUSPENDED", "REVOKED"])
async def test_bo_with_non_active_membership_is_not_found(client, world, status):
    clan = await world.clan()
    user = await world.user()
    await world.grant(user, "BUSINESS_OWNER", clan)
    await world.owner(clan, user)
    await world.member(clan, user, status)
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(user))
    assert (r.status_code, code_of(r)) == (404, "NOT_FOUND")


async def test_bo_with_revoked_at_set_on_active_membership_is_not_found(client, world):
    clan = await world.clan()
    user = await world.user()
    await world.grant(user, "BUSINESS_OWNER", clan)
    await world.owner(clan, user)
    await world.member(clan, user, "ACTIVE", revoked_at=now())
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(user))
    assert (r.status_code, code_of(r)) == (404, "NOT_FOUND")


async def test_revoking_bo_role_takes_effect_on_next_request(client, world):
    clan, bo = await world.business_owner()
    token = await world.session_for(bo)
    assert (await get(client, f"/api/v1/clans/{clan.clan_id}/users", token)).status_code == 200
    from sqlalchemy import update

    from app.models.user_access.entities import UserRole

    await world.s.execute(
        update(UserRole).where(UserRole.user_id == bo.user_id).values(revoked_at=now())
    )
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", token)
    assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")


# ----- Family Admin: membership + assignment + permission code (+ branch) -----


async def _fa_in(world, clan, *codes, **kwargs):
    fa = await world.user()
    await world.member(clan, fa)
    await world.fa(clan, fa, *codes, **kwargs)
    return fa


async def test_fa_with_permission_is_allowed(client, world):
    clan, _bo = await world.business_owner()
    fa = await _fa_in(world, clan, FA_CODE)
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(fa))
    assert r.status_code == 200


async def test_fa_without_the_needed_permission_is_forbidden(client, world):
    clan, _bo = await world.business_owner()
    fa = await _fa_in(world, clan, "PERSON_VIEW")
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(fa))
    assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")


async def test_fa_with_revoked_assignment_is_forbidden(client, world):
    clan, _bo = await world.business_owner()
    fa = await _fa_in(world, clan, FA_CODE, revoked=True)
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(fa))
    assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")


@pytest.mark.parametrize("status", ["INVITED", "SUSPENDED", "REVOKED"])
async def test_fa_with_non_active_membership_is_not_found(client, world, status):
    clan, _bo = await world.business_owner()
    fa = await world.user()
    await world.member(clan, fa, status)
    await world.fa(clan, fa, FA_CODE)
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(fa))
    assert (r.status_code, code_of(r)) == (404, "NOT_FOUND")


async def test_fa_assignment_without_membership_is_not_found(client, world):
    clan, _bo = await world.business_owner()
    fa = await world.user()
    await world.fa(clan, fa, FA_CODE)
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(fa))
    assert (r.status_code, code_of(r)) == (404, "NOT_FOUND")


async def test_fa_assignment_in_clan_a_gives_nothing_in_clan_b(client, world):
    clan_a, _ = await world.business_owner()
    clan_b, _ = await world.business_owner()
    fa = await _fa_in(world, clan_a, FA_CODE)
    r = await get(client, f"/api/v1/clans/{clan_b.clan_id}/users", await world.session_for(fa))
    assert (r.status_code, code_of(r)) == (404, "NOT_FOUND")


async def test_fa_cannot_update_fa_permissions(client, world):
    clan, _bo = await world.business_owner()
    fa = await _fa_in(world, clan, FA_CODE)
    r = await client.put(
        f"/api/v1/clans/{clan.clan_id}/admins/{fa.user_id}/permissions",
        headers=bearer(await world.session_for(fa)),
    )
    assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")


async def test_bo_can_update_fa_permissions(client, world):
    clan, bo = await world.business_owner()
    r = await client.put(
        f"/api/v1/clans/{clan.clan_id}/admins/{uuid.uuid4()}/permissions",
        headers=bearer(await world.session_for(bo)),
    )
    assert r.status_code == 200


async def test_branch_limited_assignment_does_not_cover_clan_wide_route(client, world):
    clan, _bo = await world.business_owner()
    branch = await world.branch(clan)
    fa = await _fa_in(world, clan, FA_CODE, branch_id=branch)
    r = await get(client, f"/api/v1/clans/{clan.clan_id}/users", await world.session_for(fa))
    assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")


async def test_branch_coverage_on_real_rows(session, world):
    clan, _bo = await world.business_owner()
    branch_1, branch_2 = await world.branch(clan), await world.branch(clan)
    limited = await _fa_in(world, clan, FA_CODE, branch_id=branch_1)
    clan_wide = await _fa_in(world, clan, FA_CODE)
    roles, family = UserAccessRepository(session), FamilyRepository(session)

    async def verdict(user, branch_id) -> ErrorCode | None:
        p = Principal(user.user_id, uuid.uuid4(), user.status, False)
        try:
            await authorize(
                p, Action.CLAN_USERS_LIST, ResourceScope.clan(clan.clan_id, branch_id),
                roles=roles, family=family,
            )
            return None
        except AppError as exc:
            return exc.code

    assert await verdict(limited, branch_1) is None
    assert await verdict(limited, branch_2) is ErrorCode.FORBIDDEN
    assert await verdict(limited, None) is ErrorCode.FORBIDDEN
    assert await verdict(clan_wide, branch_1) is None
    assert await verdict(clan_wide, branch_2) is None
