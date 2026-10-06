"""User administration (Mốc F) on the real DB through the real routers. Rolled back.

DB-level facts the fakes cannot prove: SQL filters and LIKE escaping, clan isolation of
the list queries, audit rows, revoked sessions, FOR NO KEY UPDATE / FOR UPDATE SQL
validity, and the FA permission rows themselves.
"""

from __future__ import annotations

import uuid
import pytest
from sqlalchemy import func, select

from app.models.family.entities import FamilyAdminAssignment, FamilyAdminPermission
from app.models.user_access.entities import AuditLog, User, UserSession
from tests.integration.factory import bearer

FA_CODE = "MEMBER_ACCOUNT_MANAGE"


def code(r) -> str:
    return r.json()["error"]["code"]


async def sa_token(world):
    """An SA that is the only active one in this transaction unless a test adds more."""
    await world.isolate_system_admins()
    sa = await world.user()
    await world.grant(sa, "SYSTEM_ADMIN")
    return sa, await world.session_for(sa)


async def audit_rows(session, entity_id):
    rows = await session.execute(select(AuditLog).where(AuditLog.entity_id == entity_id))
    return list(rows.scalars().all())


async def fa_codes(session, assignment_id) -> set[str]:
    rows = await session.execute(
        select(FamilyAdminPermission.permission_code).where(
            FamilyAdminPermission.assignment_id == assignment_id
        )
    )
    return set(rows.scalars().all())


# ----- GET /admin/users -----


async def test_list_users_filters_search_and_pagination(real_client, world):
    _sa, token = await sa_token(world)
    tag = uuid.uuid4().hex[:10]
    mixed = await world.user(email=f"Mixed.{tag}@Example.test", display_name=f"Zed {tag}")
    locked = await world.user("LOCKED", display_name=f"Locked {tag}")
    plain = [await world.user(display_name=f"Plain {tag} {i}") for i in range(3)]

    r = await real_client.get(f"/api/v1/admin/users?q={tag}&page_size=2&page=2", headers=bearer(token))
    body = r.json()
    assert r.status_code == 200 and body["total"] == 5 and len(body["items"]) == 2
    assert body["page"] == 2 and body["page_size"] == 2

    r = await real_client.get(f"/api/v1/admin/users?q=MIXED.{tag.upper()}", headers=bearer(token))
    assert [i["email"] for i in r.json()["items"]] == [f"Mixed.{tag}@Example.test"]  # not lowercased

    r = await real_client.get(f"/api/v1/admin/users?q={tag}&status=LOCKED", headers=bearer(token))
    assert [i["user_id"] for i in r.json()["items"]] == [str(locked.user_id)]
    assert "firebase_uid" not in r.text and mixed.firebase_uid not in r.text
    assert len(plain) == 3


async def test_search_escapes_like_wildcards(real_client, world):
    _sa, token = await sa_token(world)
    tag = uuid.uuid4().hex[:10]
    percent = await world.user(display_name=f"{tag}-100%-done")
    await world.user(display_name=f"{tag}-100X-done")
    under = await world.user(display_name=f"{tag}_under")
    await world.user(display_name=f"{tag}Xunder")

    r = await real_client.get(f"/api/v1/admin/users?q={tag}-100%25", headers=bearer(token))
    assert [i["user_id"] for i in r.json()["items"]] == [str(percent.user_id)]
    r = await real_client.get(f"/api/v1/admin/users?q={tag}_under", headers=bearer(token))
    assert [i["user_id"] for i in r.json()["items"]] == [str(under.user_id)]
    r = await real_client.get("/api/v1/admin/users?q=%25", headers=bearer(token))  # a lone "%"
    assert r.status_code == 200
    assert all("%" in (i["email"] + i["display_name"]) for i in r.json()["items"])


async def test_user_detail_with_memberships(real_client, world):
    _sa, token = await sa_token(world)
    clan, bo = await world.business_owner()
    r = await real_client.get(f"/api/v1/admin/users/{bo.user_id}", headers=bearer(token))
    body = r.json()
    assert r.status_code == 200 and body["user_id"] == str(bo.user_id)
    assert body["requires_password_change"] is False
    [m] = body["memberships"]
    assert m["clan_id"] == str(clan.clan_id) and m["roles"] == ["BUSINESS_OWNER"]
    assert bo.firebase_uid not in r.text
    missing = await real_client.get(f"/api/v1/admin/users/{uuid.uuid4()}", headers=bearer(token))
    assert code(missing) == "NOT_FOUND"


async def test_system_routes_reject_non_sa_and_restricted(real_client, world):
    clan, bo = await world.business_owner()
    r = await real_client.get("/api/v1/admin/users", headers=bearer(await world.session_for(bo)))
    assert (r.status_code, code(r)) == (403, "FORBIDDEN")
    restricted = await world.user(first_login_required=True)
    await world.grant(restricted, "SYSTEM_ADMIN")
    r = await real_client.get("/api/v1/admin/users", headers=bearer(await world.session_for(restricted)))
    assert (r.status_code, code(r)) == (403, "PASSWORD_CHANGE_REQUIRED")


# ----- PATCH /admin/users/{id}/status -----


async def patch(client, token, user_id, status, reason="itest"):
    return await client.patch(
        f"/api/v1/admin/users/{user_id}/status",
        headers=bearer(token),
        json={"status": status, "reason": reason},
    )


async def test_lock_revokes_sessions_writes_audit_and_blocks_the_user(real_client, session, world):
    _sa, token = await sa_token(world)
    victim = await world.user()
    victim_id = victim.user_id
    t1, t2 = await world.session_for(victim), await world.session_for(victim)
    r = await patch(real_client, token, victim_id, "LOCKED", "suspicious")
    assert r.status_code == 200
    assert r.json()["status"] == "LOCKED" and r.json()["revoked_session_count"] == 2

    rows = (await session.execute(select(UserSession).where(UserSession.user_id == victim_id))).scalars().all()
    assert len(rows) == 2 and all(s.revoked_at is not None and s.revoke_reason == "USER_LOCKED" for s in rows)
    status = await session.scalar(select(User.status).where(User.user_id == victim_id))
    assert status == "LOCKED"
    [log] = await audit_rows(session, victim_id)
    assert log.action == "user.status.update" and log.entity_type == "user"
    assert log.old_data == {"status": "ACTIVE"} and log.reason == "suspicious"
    assert log.new_data["status"] == "LOCKED" and log.new_data["revoked_sessions"] == 2
    assert log.new_data["request_id"] and log.actor_id is not None
    for token_value in (t1, t2):
        again = await real_client.get("/api/v1/auth/me", headers=bearer(token_value))
        assert (again.status_code, code(again)) == (401, "SESSION_INVALID")


async def test_unlock_then_user_can_log_in_again_but_old_sessions_stay_dead(real_client, session, world):
    _sa, token = await sa_token(world)
    user = await world.user("LOCKED")
    old = await world.session_for(user, revoked=True)
    r = await patch(real_client, token, user.user_id, "ACTIVE")
    assert r.status_code == 200 and r.json()["revoked_session_count"] == 0
    assert code(await real_client.get("/api/v1/auth/me", headers=bearer(old))) == "SESSION_INVALID"
    fresh = await world.session_for(user)
    assert (await real_client.get("/api/v1/auth/me", headers=bearer(fresh))).status_code == 200


@pytest.mark.parametrize(
    "old,new,ok",
    [
        ("ACTIVE", "LOCKED", True), ("ACTIVE", "SUSPENDED", True), ("ACTIVE", "DISABLED", True),
        ("LOCKED", "ACTIVE", True), ("SUSPENDED", "LOCKED", True), ("DISABLED", "ACTIVE", True),
        ("PENDING", "DISABLED", True),
        ("PENDING", "ACTIVE", False), ("DISABLED", "LOCKED", False), ("ACTIVE", "ACTIVE", False),
    ],
)
async def test_transitions_on_db(real_client, session, world, old, new, ok):
    _sa, token = await sa_token(world)
    user = await world.user(old)
    r = await patch(real_client, token, user.user_id, new)
    if ok:
        assert r.status_code == 200
        assert await session.scalar(select(User.status).where(User.user_id == user.user_id)) == new
    else:
        assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
        assert await audit_rows(session, user.user_id) == []


async def test_cannot_lock_last_sa_even_self_and_nothing_is_written(real_client, session, world):
    sa, token = await sa_token(world)
    sa_id = sa.user_id
    r = await patch(real_client, token, sa_id, "LOCKED")
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
    assert await session.scalar(select(User.status).where(User.user_id == sa_id)) == "ACTIVE"
    assert await audit_rows(session, sa_id) == []


async def test_can_lock_one_of_two_sas(real_client, session, world):
    sa, token = await sa_token(world)
    other = await world.user()
    await world.grant(other, "SYSTEM_ADMIN")
    assert (await patch(real_client, token, other.user_id, "SUSPENDED")).status_code == 200
    assert code(await patch(real_client, token, sa.user_id, "DISABLED")) == "STATE_CONFLICT"


async def test_status_request_validation_and_missing_user(real_client, world):
    _sa, token = await sa_token(world)
    user = await world.user()
    for body in ({"status": "PENDING", "reason": "x"}, {"status": "LOCKED"}, {"status": "LOCKED", "reason": ""}):
        r = await real_client.patch(
            f"/api/v1/admin/users/{user.user_id}/status", headers=bearer(token), json=body
        )
        assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")
    assert code(await patch(real_client, token, uuid.uuid4(), "LOCKED")) == "NOT_FOUND"


# ----- GET /clans/{id}/users -----


async def test_clan_users_never_lists_another_clan(real_client, world):
    clan, bo = await world.business_owner()
    fa = await world.user()
    await world.member(clan, fa)
    await world.grant(fa, "FAMILY_ADMIN", clan)
    await world.fa(clan, fa, FA_CODE)
    suspended = await world.user()
    await world.member(clan, suspended, "SUSPENDED")
    other_clan, other_bo = await world.business_owner()
    foreign = await world.user()
    await world.member(other_clan, foreign)
    await world.grant(foreign, "FAMILY_ADMIN", other_clan)  # a role in ANOTHER clan

    r = await real_client.get(f"/api/v1/clans/{clan.clan_id}/users", headers=bearer(await world.session_for(bo)))
    body = r.json()
    assert r.status_code == 200 and body["total"] == 3
    ids = {i["user_id"]: i for i in body["items"]}
    assert set(ids) == {str(bo.user_id), str(fa.user_id), str(suspended.user_id)}
    assert str(foreign.user_id) not in r.text and str(other_bo.user_id) not in r.text
    assert ids[str(fa.user_id)]["is_family_admin"] is True and ids[str(fa.user_id)]["roles"] == ["FAMILY_ADMIN"]
    assert ids[str(bo.user_id)]["roles"] == ["BUSINESS_OWNER"] and ids[str(bo.user_id)]["is_family_admin"] is False
    assert "firebase_uid" not in r.text

    r = await real_client.get(
        f"/api/v1/clans/{clan.clan_id}/users?membership_status=SUSPENDED", headers=bearer(await world.session_for(bo))
    )
    assert [i["user_id"] for i in r.json()["items"]] == [str(suspended.user_id)]
    r = await real_client.get(
        f"/api/v1/clans/{clan.clan_id}/users?page_size=2&page=2", headers=bearer(await world.session_for(bo))
    )
    assert r.json()["total"] == 3 and len(r.json()["items"]) == 1


async def test_clan_users_access_rules_on_db(real_client, world):
    clan, bo = await world.business_owner()
    other_clan, _ = await world.business_owner()
    bo_token = await world.session_for(bo)
    r = await real_client.get(f"/api/v1/clans/{other_clan.clan_id}/users", headers=bearer(bo_token))
    assert (r.status_code, code(r)) == (404, "NOT_FOUND")
    inactive, inactive_bo = await world.business_owner("PENDING")
    r = await real_client.get(f"/api/v1/clans/{inactive.clan_id}/users", headers=bearer(await world.session_for(inactive_bo)))
    assert (r.status_code, code(r)) == (403, "FORBIDDEN")
    fa = await world.user()
    await world.member(clan, fa)
    await world.fa(clan, fa, FA_CODE)
    assert (await real_client.get(f"/api/v1/clans/{clan.clan_id}/users", headers=bearer(await world.session_for(fa)))).status_code == 200
    sa = await world.user()
    await world.grant(sa, "SYSTEM_ADMIN")
    r = await real_client.get(f"/api/v1/clans/{clan.clan_id}/users", headers=bearer(await world.session_for(sa)))
    assert (r.status_code, code(r)) == (404, "NOT_FOUND")  # SA has no implicit clan access


# ----- PUT /clans/{id}/admins/{user_id}/permissions -----


async def put(client, token, clan, user_id, codes):
    return await client.put(
        f"/api/v1/clans/{clan.clan_id}/admins/{user_id}/permissions",
        headers=bearer(token),
        json={"permission_codes": codes},
    )


async def fa_in(world, clan, *codes, **kw):
    fa = await world.user()
    await world.member(clan, fa)
    await world.grant(fa, "FAMILY_ADMIN", clan)
    assignment = await world.fa(clan, fa, *codes, **kw)
    return fa, assignment


async def test_bo_replaces_permissions_with_immediate_effect_and_audit(real_client, session, world):
    clan, bo = await world.business_owner()
    bo_token = await world.session_for(bo)
    fa, assignment = await fa_in(world, clan, "PERSON_VIEW", "TREE_VIEW")
    assignment_id = assignment.assignment_id
    fa_token = await world.session_for(fa)
    url = f"/api/v1/clans/{clan.clan_id}/users"
    assert code(await real_client.get(url, headers=bearer(fa_token))) == "FORBIDDEN"

    r = await put(real_client, bo_token, clan, fa.user_id, [FA_CODE, "PERSON_VIEW"])
    assert r.status_code == 200
    assert r.json()["permission_codes"] == sorted([FA_CODE, "PERSON_VIEW"])
    assert r.json()["assignment_id"] == str(assignment_id)
    assert await fa_codes(session, assignment_id) == {FA_CODE, "PERSON_VIEW"}
    assert (await real_client.get(url, headers=bearer(fa_token))).status_code == 200
    [log] = await audit_rows(session, assignment_id)
    assert log.action == "family_admin.permissions.update" and log.clan_id == clan.clan_id
    assert log.old_data["permission_codes"] == ["PERSON_VIEW", "TREE_VIEW"]
    assert log.new_data["permission_codes"] == sorted([FA_CODE, "PERSON_VIEW"])
    granted_by = await session.scalar(
        select(FamilyAdminPermission.granted_by).where(
            FamilyAdminPermission.assignment_id == assignment_id,
            FamilyAdminPermission.permission_code == FA_CODE,
        )
    )
    assert granted_by == bo.user_id

    assert (await put(real_client, bo_token, clan, fa.user_id, ["PERSON_VIEW"])).status_code == 200
    assert code(await real_client.get(url, headers=bearer(fa_token))) == "FORBIDDEN"


async def test_empty_list_keeps_the_assignment_and_unchanged_set_writes_nothing(real_client, session, world):
    clan, bo = await world.business_owner()
    token = await world.session_for(bo)
    fa, assignment = await fa_in(world, clan, FA_CODE)
    assignment_id = assignment.assignment_id

    assert (await put(real_client, token, clan, fa.user_id, [FA_CODE])).status_code == 200
    assert await audit_rows(session, assignment_id) == []  # unchanged: no audit

    r = await put(real_client, token, clan, fa.user_id, [])
    assert r.status_code == 200 and r.json()["permission_codes"] == []
    assert await fa_codes(session, assignment_id) == set()
    revoked_at = await session.scalar(
        select(FamilyAdminAssignment.revoked_at).where(FamilyAdminAssignment.assignment_id == assignment_id)
    )
    assert revoked_at is None


async def test_unknown_code_is_422_and_other_codes_are_not_applied(real_client, session, world):
    clan, bo = await world.business_owner()
    fa, assignment = await fa_in(world, clan, FA_CODE)
    r = await put(real_client, await world.session_for(bo), clan, fa.user_id, ["PERSON_VIEW", "NOT_A_PERMISSION"])
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR") and "NOT_A_PERMISSION" not in r.text
    assert await fa_codes(session, assignment.assignment_id) == {FA_CODE}


async def test_every_delegable_code_in_the_permissions_table_is_accepted(real_client, session, world):
    """Every code of the permissions table except the non-delegable ones (Mốc F2 Q1:
    ADMIN_MANAGE -> 403) can be delegated; adding a non-delegable code turns the PUT into 403."""
    from app.dependencies.permissions import NON_DELEGABLE_PERMISSION_CODES

    all_codes = list((await session.execute(select_permission_codes())).scalars().all())
    assert FA_CODE in all_codes and len(all_codes) >= 10
    assert NON_DELEGABLE_PERMISSION_CODES <= set(all_codes)
    delegable = [c for c in all_codes if c not in NON_DELEGABLE_PERMISSION_CODES]
    clan, bo = await world.business_owner()
    fa, assignment = await fa_in(world, clan)
    token = await world.session_for(bo)
    r = await put(real_client, token, clan, fa.user_id, delegable)
    assert r.status_code == 200 and set(r.json()["permission_codes"]) == set(delegable)
    assert await fa_codes(session, assignment.assignment_id) == set(delegable)
    r = await put(real_client, token, clan, fa.user_id, all_codes)
    assert (r.status_code, code(r)) == (403, "FORBIDDEN")
    assert await fa_codes(session, assignment.assignment_id) == set(delegable)


def select_permission_codes():
    from app.models.user_access.entities import Permission

    return select(Permission.code)


async def test_target_rules_on_db(real_client, session, world):
    clan, bo = await world.business_owner()
    token = await world.session_for(bo)
    plain = await world.user()
    await world.member(clan, plain)
    assert code(await put(real_client, token, clan, plain.user_id, [FA_CODE])) == "NOT_FOUND"
    assert code(await put(real_client, token, clan, uuid.uuid4(), [FA_CODE])) == "NOT_FOUND"
    revoked, _ = await fa_in(world, clan, FA_CODE, revoked=True)
    assert code(await put(real_client, token, clan, revoked.user_id, [FA_CODE])) == "NOT_FOUND"
    suspended, _ = await fa_in(world, clan, FA_CODE)
    from sqlalchemy import update

    from app.models.family.entities import ClanMembership

    await session.execute(
        update(ClanMembership)
        .where(ClanMembership.user_id == suspended.user_id)
        .values(status="SUSPENDED")
    )
    assert code(await put(real_client, token, clan, suspended.user_id, [FA_CODE])) == "NOT_FOUND"
    other_clan, _ = await world.business_owner()
    foreign, _ = await fa_in(world, other_clan, FA_CODE)
    assert code(await put(real_client, token, clan, foreign.user_id, [FA_CODE])) == "NOT_FOUND"


async def test_branch_limited_and_duplicate_assignments_on_db(real_client, session, world):
    clan, bo = await world.business_owner()
    token = await world.session_for(bo)
    branch = await world.branch(clan)
    fa, branch_assignment = await fa_in(world, clan, FA_CODE, branch_id=branch)
    assert code(await put(real_client, token, clan, fa.user_id, [FA_CODE])) == "NOT_FOUND"

    clan_wide = await world.fa(clan, fa, "PERSON_VIEW")
    r = await put(real_client, token, clan, fa.user_id, ["TREE_VIEW"])
    assert r.status_code == 200 and r.json()["assignment_id"] == str(clan_wide.assignment_id)
    assert await fa_codes(session, branch_assignment.assignment_id) == {FA_CODE}  # untouched

    await world.fa(clan, fa, "AUDIT_VIEW")  # DB allows a 2nd active clan-wide assignment (KI-08)
    r = await put(real_client, token, clan, fa.user_id, ["TREE_VIEW"])
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")


async def test_fa_and_other_clan_bo_cannot_change_permissions(real_client, session, world):
    clan, _bo = await world.business_owner()
    fa, assignment = await fa_in(world, clan, FA_CODE)
    r = await put(real_client, await world.session_for(fa), clan, fa.user_id, [])
    assert (r.status_code, code(r)) == (403, "FORBIDDEN")
    _other, other_bo = await world.business_owner()
    r = await put(real_client, await world.session_for(other_bo), clan, fa.user_id, [])
    assert (r.status_code, code(r)) == (404, "NOT_FOUND")
    inactive, inactive_bo = await world.business_owner("SUSPENDED")
    fa2, _ = await fa_in(world, inactive, FA_CODE)
    r = await put(real_client, await world.session_for(inactive_bo), inactive, fa2.user_id, [])
    assert (r.status_code, code(r)) == (403, "FORBIDDEN")
    assert await fa_codes(session, assignment.assignment_id) == {FA_CODE}
    count = await session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.entity_id == assignment.assignment_id))
    assert count == 0
