"""Appoint / edit / revoke a Family Admin on the real DB through the real routers (Mốc F2).

Rolled back per test. Also proves the dev seed still produces a consistent Family Admin
(assignment AND user_roles row) and that the existing PUT edits a seed-made assignment.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.dependencies.permissions import owner_actions
from app.models.family.entities import (
    ClanMembership,
    FamilyAdminAssignment,
    FamilyAdminPermission,
)
from app.models.user_access.entities import AuditLog, Role, User, UserRole
from tests.integration.factory import bearer, now

FA_CODE = "MEMBER_ACCOUNT_MANAGE"
BE_DIR = Path(__file__).resolve().parents[2]


def code(r) -> str:
    return r.json()["error"]["code"]


async def post_admin(client, token, clan_id, user_id, codes=None):
    body = {"user_id": str(user_id)}
    if codes is not None:
        body["permission_codes"] = codes
    return await client.post(f"/api/v1/clans/{clan_id}/admins", headers=bearer(token), json=body)


async def delete_admin(client, token, clan_id, user_id):
    return await client.delete(f"/api/v1/clans/{clan_id}/admins/{user_id}", headers=bearer(token))


async def put_perms(client, token, clan_id, user_id, codes):
    return await client.put(
        f"/api/v1/clans/{clan_id}/admins/{user_id}/permissions",
        headers=bearer(token),
        json={"permission_codes": codes},
    )


async def assignments(session, clan_id, user_id, *, active=True):
    stmt = select(FamilyAdminAssignment).where(
        FamilyAdminAssignment.clan_id == clan_id, FamilyAdminAssignment.user_id == user_id
    )
    if active:
        stmt = stmt.where(FamilyAdminAssignment.revoked_at.is_(None))
    return list((await session.execute(stmt)).scalars().all())


async def codes_of(session, assignment_id) -> set[str]:
    rows = await session.execute(
        select(FamilyAdminPermission.permission_code).where(
            FamilyAdminPermission.assignment_id == assignment_id
        )
    )
    return set(rows.scalars().all())


async def fa_role_rows(session, clan_id, user_id) -> list[UserRole]:
    rows = await session.execute(
        select(UserRole)
        .join(Role, Role.role_id == UserRole.role_id)
        .where(UserRole.clan_id == clan_id, UserRole.user_id == user_id, Role.code == "FAMILY_ADMIN")
    )
    return list(rows.scalars().all())


async def audit(session, action, clan_id):
    rows = await session.execute(
        select(AuditLog).where(AuditLog.action == action, AuditLog.clan_id == clan_id)
    )
    return list(rows.scalars().all())


async def member_in(world, clan, status="ACTIVE") -> User:
    user = await world.user()
    await world.member(clan, user, status)
    return user


# ----- appoint -----


async def test_appoint_creates_assignment_permissions_role_and_audit(real_client, session, world):
    clan, bo = await world.business_owner()
    bo_token = await world.session_for(bo)
    member = await member_in(world, clan)
    member_token = await world.session_for(member)
    clan_id, member_id, bo_id = clan.clan_id, member.user_id, bo.user_id
    url = f"/api/v1/clans/{clan_id}/users"
    assert code(await real_client.get(url, headers=bearer(member_token))) == "FORBIDDEN"

    r = await post_admin(real_client, bo_token, clan_id, member_id, [FA_CODE, "PERSON_VIEW"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["permission_codes"] == sorted([FA_CODE, "PERSON_VIEW"])

    [assignment] = await assignments(session, clan_id, member_id)
    assert str(assignment.assignment_id) == body["assignment_id"]
    assert assignment.branch_id is None and assignment.assigned_by == bo_id
    assert await codes_of(session, assignment.assignment_id) == {FA_CODE, "PERSON_VIEW"}
    [role_row] = await fa_role_rows(session, clan_id, member_id)
    assert role_row.revoked_at is None and role_row.granted_by == bo_id

    [log] = await audit(session, "family_admin.assign", clan_id)
    assert log.actor_id == bo_id and log.entity_id == assignment.assignment_id
    assert log.old_data is None and log.new_data["role_granted"] is True
    assert log.new_data["permission_codes"] == sorted([FA_CODE, "PERSON_VIEW"])
    assert log.new_data["request_id"]
    assert member.firebase_uid not in str(log.new_data) and member.email not in str(log.new_data)

    # Effective on the very next request, in /clans/{id}/users and in /auth/me.
    assert (await real_client.get(url, headers=bearer(member_token))).status_code == 200
    me = (await real_client.get("/api/v1/auth/me", headers=bearer(member_token))).json()
    [membership] = me["memberships"]
    assert "FAMILY_ADMIN" in membership["roles"] and FA_CODE in membership["permissions"]
    bo_me = (await real_client.get("/api/v1/auth/me", headers=bearer(bo_token))).json()
    assert {"clan.fa.assign", "clan.fa.revoke"} <= set(bo_me["memberships"][0]["permissions"])
    assert set(owner_actions()) == set(bo_me["memberships"][0]["permissions"])
    listed = {i["user_id"]: i for i in (await real_client.get(url, headers=bearer(bo_token))).json()["items"]}
    assert listed[str(member_id)]["is_family_admin"] is True


async def test_empty_permission_set_and_edit_with_the_existing_put(real_client, session, world):
    clan, bo = await world.business_owner()
    token = await world.session_for(bo)
    member = await member_in(world, clan)
    r = await post_admin(real_client, token, clan.clan_id, member.user_id)  # permission_codes omitted
    assert r.status_code == 201 and r.json()["permission_codes"] == []
    r = await put_perms(real_client, token, clan.clan_id, member.user_id, [FA_CODE])
    assert r.status_code == 200 and r.json()["assignment_id"] == (
        await assignments(session, clan.clan_id, member.user_id)
    )[0].assignment_id.__str__()
    assert r.json()["permission_codes"] == [FA_CODE]


async def test_non_delegable_code_is_403_on_post_and_put_and_unknown_is_422(real_client, session, world):
    clan, bo = await world.business_owner()
    token = await world.session_for(bo)
    member = await member_in(world, clan)
    for codes in (["ADMIN_MANAGE"], [FA_CODE, "ADMIN_MANAGE"]):
        r = await post_admin(real_client, token, clan.clan_id, member.user_id, codes)
        assert (r.status_code, code(r)) == (403, "FORBIDDEN") and "ADMIN_MANAGE" not in r.text
    r = await post_admin(real_client, token, clan.clan_id, member.user_id, ["NOT_A_REAL_CODE"])
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")
    assert await assignments(session, clan.clan_id, member.user_id) == []
    assert await audit(session, "family_admin.assign", clan.clan_id) == []

    fa = await member_in(world, clan)
    await world.grant(fa, "FAMILY_ADMIN", clan)
    legacy = await world.fa(clan, fa, FA_CODE, "ADMIN_MANAGE")  # a row that predates the ban
    assert code(await put_perms(real_client, token, clan.clan_id, fa.user_id, [FA_CODE, "ADMIN_MANAGE"])) == "FORBIDDEN"
    assert await codes_of(session, legacy.assignment_id) == {FA_CODE, "ADMIN_MANAGE"}
    assert (await put_perms(real_client, token, clan.clan_id, fa.user_id, [FA_CODE])).status_code == 200
    assert await codes_of(session, legacy.assignment_id) == {FA_CODE}


async def test_target_rules_on_db(real_client, session, world):
    clan, bo = await world.business_owner()
    token = await world.session_for(bo)
    clan_id = clan.clan_id
    assert code(await post_admin(real_client, token, clan_id, uuid.uuid4())) == "NOT_FOUND"
    assert code(await post_admin(real_client, token, clan_id, (await world.user()).user_id)) == "NOT_FOUND"
    for status in ("INVITED", "SUSPENDED", "REVOKED"):
        member = await member_in(world, clan, status)
        assert code(await post_admin(real_client, token, clan_id, member.user_id)) == "NOT_FOUND", status
    dated = await member_in(world, clan)
    from sqlalchemy import update

    await session.execute(
        update(ClanMembership).where(ClanMembership.user_id == dated.user_id).values(revoked_at=now())
    )
    assert code(await post_admin(real_client, token, clan_id, dated.user_id)) == "NOT_FOUND"
    other_clan, _ = await world.business_owner()
    foreign = await member_in(world, other_clan)
    assert code(await post_admin(real_client, token, clan_id, foreign.user_id)) == "NOT_FOUND"

    assert code(await post_admin(real_client, token, clan_id, bo.user_id)) == "STATE_CONFLICT"  # self
    former = await member_in(world, clan)
    await world.grant(former, "BUSINESS_OWNER", clan)  # keeps the role, is not the owner
    assert code(await post_admin(real_client, token, clan_id, former.user_id)) == "STATE_CONFLICT"

    existing = await member_in(world, clan)
    await world.grant(existing, "FAMILY_ADMIN", clan)
    await world.fa(clan, existing, FA_CODE)
    assert code(await post_admin(real_client, token, clan_id, existing.user_id)) == "STATE_CONFLICT"
    branch = await world.branch(clan)
    limited = await member_in(world, clan)
    await world.fa(clan, limited, FA_CODE, branch_id=branch)
    assert code(await post_admin(real_client, token, clan_id, limited.user_id)) == "STATE_CONFLICT"
    assert await audit(session, "family_admin.assign", clan_id) == []


async def test_a_locked_account_can_still_be_appointed_decision_32(real_client, session, world):
    """Only the MEMBERSHIP must be ACTIVE, not users.status (documented guess, decision 32)."""
    clan, bo = await world.business_owner()
    locked = await world.user("LOCKED")
    await world.member(clan, locked)
    r = await post_admin(real_client, await world.session_for(bo), clan.clan_id, locked.user_id)
    assert r.status_code == 201


async def test_an_existing_active_role_row_is_reused_not_duplicated(real_client, session, world):
    clan, bo = await world.business_owner()
    member = await member_in(world, clan)
    await world.grant(member, "FAMILY_ADMIN", clan)  # role without an assignment
    r = await post_admin(real_client, await world.session_for(bo), clan.clan_id, member.user_id)
    assert r.status_code == 201
    assert len(await fa_role_rows(session, clan.clan_id, member.user_id)) == 1
    [log] = await audit(session, "family_admin.assign", clan.clan_id)
    assert log.new_data["role_granted"] is False


async def test_access_rules_for_appoint_and_revoke(real_client, session, world):
    clan, bo = await world.business_owner()
    member = await member_in(world, clan)
    fa = await member_in(world, clan)
    await world.fa(clan, fa, FA_CODE)
    clan_id = clan.clan_id
    # FA (even with MEMBER_ACCOUNT_MANAGE) and plain members cannot appoint or revoke.
    fa_token = await world.session_for(fa)
    assert code(await post_admin(real_client, fa_token, clan_id, member.user_id)) == "FORBIDDEN"
    assert code(await delete_admin(real_client, fa_token, clan_id, fa.user_id)) == "FORBIDDEN"
    member_token = await world.session_for(member)
    assert code(await post_admin(real_client, member_token, clan_id, member.user_id)) == "FORBIDDEN"
    # BO of another clan and System Admin: the clan is not visible.
    _other, other_bo = await world.business_owner()
    other_token = await world.session_for(other_bo)
    assert code(await post_admin(real_client, other_token, clan_id, member.user_id)) == "NOT_FOUND"
    assert code(await delete_admin(real_client, other_token, clan_id, fa.user_id)) == "NOT_FOUND"
    sa = await world.user()
    await world.grant(sa, "SYSTEM_ADMIN")
    sa_token = await world.session_for(sa)
    assert code(await post_admin(real_client, sa_token, clan_id, member.user_id)) == "NOT_FOUND"
    # A clan that is not ACTIVE blocks its own BO.
    inactive, inactive_bo = await world.business_owner("SUSPENDED")
    target = await member_in(world, inactive)
    inactive_token = await world.session_for(inactive_bo)
    assert code(await post_admin(real_client, inactive_token, inactive.clan_id, target.user_id)) == "FORBIDDEN"
    # Validation never beats authorization.
    r = await real_client.post(f"/api/v1/clans/{clan_id}/admins", headers=bearer(member_token), json={"bad": 1})
    assert (r.status_code, code(r)) == (403, "FORBIDDEN")
    assert await assignments(session, clan_id, member.user_id) == []
    assert bo is not None


# ----- revoke -----


async def test_revoke_deletes_permissions_revokes_assignment_and_role_with_immediate_effect(
    real_client, session, world
):
    clan, bo = await world.business_owner()
    bo_token = await world.session_for(bo)
    member = await member_in(world, clan)
    clan_id, member_id = clan.clan_id, member.user_id
    await post_admin(real_client, bo_token, clan_id, member_id, [FA_CODE, "PERSON_VIEW"])
    [assignment] = await assignments(session, clan_id, member_id)
    assignment_id = assignment.assignment_id
    member_token = await world.session_for(member)
    url = f"/api/v1/clans/{clan_id}/users"
    assert (await real_client.get(url, headers=bearer(member_token))).status_code == 200

    r = await delete_admin(real_client, bo_token, clan_id, member_id)
    assert r.status_code == 204 and r.content == b""
    assert code(await real_client.get(url, headers=bearer(member_token))) == "FORBIDDEN"  # next request

    await session.refresh(assignment)
    assert assignment.revoked_at is not None
    assert await codes_of(session, assignment_id) == set()
    [role_row] = await fa_role_rows(session, clan_id, member_id)
    assert role_row.revoked_at is not None
    membership = (
        await session.execute(
            select(ClanMembership).where(ClanMembership.clan_id == clan_id, ClanMembership.user_id == member_id)
        )
    ).scalar_one()
    assert membership.status == "ACTIVE" and membership.revoked_at is None  # still a member

    [log] = await audit(session, "family_admin.revoke", clan_id)
    assert log.actor_id == bo.user_id and log.entity_id == assignment_id
    assert log.old_data["permission_codes"] == sorted([FA_CODE, "PERSON_VIEW"])  # history lives here
    assert log.old_data["assignment_ids"] == [str(assignment_id)]
    assert log.new_data["revoked_assignments"] == 1 and log.new_data["roles_revoked"] == 1
    assert member.firebase_uid not in str(log.old_data) + str(log.new_data)

    assert code(await put_perms(real_client, bo_token, clan_id, member_id, [FA_CODE])) == "NOT_FOUND"
    assert code(await delete_admin(real_client, bo_token, clan_id, member_id)) == "NOT_FOUND"


async def test_reappoint_after_revoke_does_not_violate_the_unique_role_index(real_client, session, world):
    clan, bo = await world.business_owner()
    token = await world.session_for(bo)
    member = await member_in(world, clan)
    clan_id, member_id = clan.clan_id, member.user_id
    first = (await post_admin(real_client, token, clan_id, member_id, [FA_CODE])).json()["assignment_id"]
    assert (await delete_admin(real_client, token, clan_id, member_id)).status_code == 204
    r = await post_admin(real_client, token, clan_id, member_id, ["PERSON_VIEW"])
    assert r.status_code == 201 and r.json()["assignment_id"] != first
    assert len(await assignments(session, clan_id, member_id)) == 1
    assert len(await assignments(session, clan_id, member_id, active=False)) == 2  # history kept
    rows = await fa_role_rows(session, clan_id, member_id)
    assert sorted(row.revoked_at is None for row in rows) == [False, True]  # one revoked, one active
    assert (await real_client.get(f"/api/v1/clans/{clan_id}/users", headers=bearer(await world.session_for(member)))).status_code == 403
    assert (await put_perms(real_client, token, clan_id, member_id, [FA_CODE])).status_code == 200


async def test_revoke_takes_every_active_assignment_and_leaves_other_users_alone(real_client, session, world):
    clan, bo = await world.business_owner()
    token = await world.session_for(bo)
    fa = await member_in(world, clan)
    await world.grant(fa, "FAMILY_ADMIN", clan)
    branch, other_branch = await world.branch(clan), await world.branch(clan)
    wide = await world.fa(clan, fa, FA_CODE)
    limited = await world.fa(clan, fa, "PERSON_VIEW", branch_id=branch)
    # KI-08: the DB refuses a second clan-wide row, so the third one is for another branch.
    second_limited = await world.fa(clan, fa, "TREE_VIEW", branch_id=other_branch)
    other = await member_in(world, clan)
    await world.grant(other, "FAMILY_ADMIN", clan)
    other_assignment = await world.fa(clan, other, FA_CODE)
    ids = [wide.assignment_id, limited.assignment_id, second_limited.assignment_id]
    other_id = other_assignment.assignment_id

    assert (await delete_admin(real_client, token, clan.clan_id, fa.user_id)).status_code == 204
    assert await assignments(session, clan.clan_id, fa.user_id) == []
    for assignment_id in ids:
        assert await codes_of(session, assignment_id) == set()
    [log] = await audit(session, "family_admin.revoke", clan.clan_id)
    assert sorted(log.old_data["assignment_ids"]) == sorted(str(i) for i in ids)
    assert log.old_data["permission_codes"] == sorted([FA_CODE, "PERSON_VIEW", "TREE_VIEW"])
    assert len(await assignments(session, clan.clan_id, other.user_id)) == 1
    assert await codes_of(session, other_id) == {FA_CODE}
    assert all(row.revoked_at is None for row in await fa_role_rows(session, clan.clan_id, other.user_id))


async def test_a_suspended_member_can_still_be_revoked_and_non_fas_are_404(real_client, session, world):
    clan, bo = await world.business_owner()
    token = await world.session_for(bo)
    fa = await member_in(world, clan, "SUSPENDED")
    await world.grant(fa, "FAMILY_ADMIN", clan)
    await world.fa(clan, fa, FA_CODE)
    assert (await delete_admin(real_client, token, clan.clan_id, fa.user_id)).status_code == 204

    plain = await member_in(world, clan)
    other_clan, _ = await world.business_owner()
    foreign = await member_in(world, other_clan)
    await world.fa(other_clan, foreign, FA_CODE)
    revoked = await member_in(world, clan)
    await world.fa(clan, revoked, FA_CODE, revoked=True)
    for target in (plain.user_id, foreign.user_id, revoked.user_id, bo.user_id, uuid.uuid4()):
        assert code(await delete_admin(real_client, token, clan.clan_id, target)) == "NOT_FOUND"
    assert len(await assignments(session, other_clan.clan_id, foreign.user_id)) == 1  # untouched
    assert (await real_client.delete(f"/api/v1/clans/{clan.clan_id}/admins/not-a-uuid", headers=bearer(token))).status_code == 422


# ----- the dev seed stays consistent (assignment AND user_roles) -----


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("seed_dev_under_test", BE_DIR / "scripts" / "seed_dev.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _user(session, email) -> User:
    return (await session.execute(select(User).where(User.email == email))).scalar_one()


async def test_dev_seed_family_admin_has_assignment_and_role_and_put_edits_it(
    real_client, session, world, capsys
):
    seed_dev = _load_seed_module()
    await seed_dev.seed(session)  # get-or-create inside this test's rolled-back transaction
    capsys.readouterr()

    from app.models.family.entities import Clan

    clan = (await session.execute(select(Clan).where(Clan.clan_code == "DEV-CLAN-A"))).scalar_one()
    bo = await _user(session, seed_dev.email_of("bo-a"))
    fa = await _user(session, seed_dev.email_of("fa-a"))
    member = await _user(session, seed_dev.email_of("member-a"))
    clan_id, fa_id, bo_id = clan.clan_id, fa.user_id, bo.user_id

    # The seed-made FA has BOTH halves, consistent with what POST now creates.
    [assignment] = await assignments(session, clan_id, fa_id)
    assert assignment.branch_id is None
    assert await codes_of(session, assignment.assignment_id) == {seed_dev.FA_PERMISSION}
    [role_row] = await fa_role_rows(session, clan_id, fa_id)
    assert role_row.revoked_at is None
    assert len(await fa_role_rows(session, clan_id, member.user_id)) == 0  # members are not FAs

    bo_token = await world.session_for(bo)
    # The existing PUT edits the seed's assignment.
    r = await put_perms(real_client, bo_token, clan_id, fa_id, [seed_dev.FA_PERMISSION, "PERSON_VIEW"])
    assert r.status_code == 200 and r.json()["assignment_id"] == str(assignment.assignment_id)
    assert await codes_of(session, assignment.assignment_id) == {seed_dev.FA_PERMISSION, "PERSON_VIEW"}

    # POST/DELETE work on seed data too: the BO cannot be appointed, a member can.
    assert code(await post_admin(real_client, bo_token, clan_id, bo_id)) == "STATE_CONFLICT"
    assert code(await post_admin(real_client, bo_token, clan_id, fa_id)) == "STATE_CONFLICT"
    assert (await post_admin(real_client, bo_token, clan_id, member.user_id, [FA_CODE])).status_code == 201
    assert len(await fa_role_rows(session, clan_id, member.user_id)) == 1

    # Revoking the seed FA clears all three: assignment, permissions and role row.
    assert (await delete_admin(real_client, bo_token, clan_id, fa_id)).status_code == 204
    assert await assignments(session, clan_id, fa_id) == []
    assert await codes_of(session, assignment.assignment_id) == set()
    assert all(row.revoked_at is not None for row in await fa_role_rows(session, clan_id, fa_id))
