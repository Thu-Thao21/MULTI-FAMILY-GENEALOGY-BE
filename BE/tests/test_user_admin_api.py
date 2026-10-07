"""User administration API (Mốc F) over HTTP with the real routers and fakes."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controllers.auth_access.user_admin_router import router
from app.controllers.auth_access.user_admin_use_cases import STATUS_TRANSITIONS
from app.core.errors import register_exception_handlers
from app.core.request_id import RequestIdMiddleware
from app.db.postgres import get_db
from app.dependencies.auth import get_user_access_repo
from app.dependencies.permissions import get_family_repo
from app.models.family.repository import FamilyRepository
from tests.fakes import FakeDb, FakeFamilyRepo, FakeUserAccessRepo, make_user

FA_CODE = "MEMBER_ACCOUNT_MANAGE"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class World:
    def __init__(self) -> None:
        self.repo = FakeUserAccessRepo()
        self.family = FakeFamilyRepo(users=self.repo.users)
        self.db = FakeDb(repo=self.repo)
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)
        register_exception_handlers(app)
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_user_access_repo] = lambda: self.repo
        app.dependency_overrides[get_family_repo] = lambda: self.family
        self.client = TestClient(app)

    def user(self, status="ACTIVE", **kw):
        return self.repo.add_user(make_user(status, **kw))

    def token(self, user) -> str:
        return self.repo.seed_session(
            user,
            token=f"tok-{uuid.uuid4().hex}",
            created_at=utcnow() - timedelta(minutes=5),
            expires_at=utcnow() + timedelta(hours=8),
        )

    def sa(self):
        user = self.user()
        self.repo.grant(user, "SYSTEM_ADMIN")
        return user, self.token(user)

    def bo(self, clan_status="ACTIVE"):
        clan = self.family.add_clan(clan_status)
        bo = self.user()
        self.repo.grant(bo, "BUSINESS_OWNER", clan.clan_id)
        self.family.add_owner(clan, bo)
        self.family.add_member(clan, bo)
        return clan, bo, self.token(bo)

    def fa(self, clan, *codes, branch_id=None):
        fa = self.user()
        self.family.add_member(clan, fa)
        self.repo.grant(fa, "FAMILY_ADMIN", clan.clan_id)
        assignment = self.family.add_fa_assignment(clan, fa, list(codes), branch_id=branch_id)
        return fa, assignment


def h(token):
    return {"Authorization": f"Bearer {token}"}


def code(r):
    return r.json()["error"]["code"]


@pytest.fixture
def w() -> World:
    return World()


# ----- authorization surface -----


def test_unauthenticated_and_restricted_are_rejected(w):
    assert code(w.client.get("/api/v1/admin/users")) == "UNAUTHENTICATED"
    sa = w.user(first_login_required=True)
    w.repo.grant(sa, "SYSTEM_ADMIN")
    r = w.client.get("/api/v1/admin/users", headers=h(w.token(sa)))
    assert (r.status_code, code(r)) == (403, "PASSWORD_CHANGE_REQUIRED")


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/admin/users", None),
        ("get", "/admin/users/{u}", None),
        ("patch", "/admin/users/{u}/status", {"status": "LOCKED", "reason": "x"}),
    ],
)
def test_non_sa_cannot_use_system_routes(w, method, path, body):
    clan, bo, token = w.bo()
    target = w.user()
    r = getattr(w.client, method)(
        "/api/v1" + path.format(u=target.user_id), headers=h(token), **({"json": body} if body else {})
    )
    assert (r.status_code, code(r)) == (403, "FORBIDDEN")
    assert target.status == "ACTIVE"


def test_authorization_wins_over_validation_errors(w):
    """A caller without access must not learn anything from validation messages."""
    clan, bo, _ = w.bo()
    member = w.user()
    w.family.add_member(clan, member)
    token = w.token(member)
    r = w.client.patch(f"/api/v1/admin/users/{member.user_id}/status", headers=h(token), json={"bad": 1})
    assert (r.status_code, code(r)) == (403, "FORBIDDEN")
    r = w.client.put(
        f"/api/v1/clans/{clan.clan_id}/admins/{member.user_id}/permissions",
        headers=h(token), json={"permission_codes": "nope"},
    )
    assert (r.status_code, code(r)) == (403, "FORBIDDEN")
    outsider = w.token(w.user())
    r = w.client.put(
        f"/api/v1/clans/{clan.clan_id}/admins/{member.user_id}/permissions",
        headers=h(outsider), json={"permission_codes": "nope"},
    )
    assert (r.status_code, code(r)) == (404, "NOT_FOUND")


# ----- GET /admin/users -----


def test_list_users_paginates_filters_and_hides_internal_fields(w):
    sa, token = w.sa()
    for i in range(5):
        w.user("LOCKED" if i < 2 else "ACTIVE")
    r = w.client.get("/api/v1/admin/users?page_size=3&page=2", headers=h(token))
    body = r.json()
    assert r.status_code == 200 and body["total"] == 6
    assert body["page"] == 2 and body["page_size"] == 3 and len(body["items"]) == 3
    assert set(body["items"][0]) == {
        "user_id", "email", "display_name", "status", "last_login_at", "created_at",
    }
    assert "firebase_uid" not in r.text
    locked = w.client.get("/api/v1/admin/users?status=LOCKED", headers=h(token)).json()
    assert locked["total"] == 2 and {i["status"] for i in locked["items"]} == {"LOCKED"}


@pytest.mark.parametrize("query", ["page_size=101", "page=0", "status=BOGUS"])
def test_list_users_query_validation(w, query):
    _sa, token = w.sa()
    r = w.client.get(f"/api/v1/admin/users?{query}", headers=h(token))
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")


def test_list_users_search_is_case_insensitive_and_email_is_not_changed(w):
    _sa, token = w.sa()
    mixed = w.user()
    mixed.email = "Mixed.Case@Example.test"
    r = w.client.get("/api/v1/admin/users?q=mixed.CASE", headers=h(token))
    assert [i["email"] for i in r.json()["items"]] == ["Mixed.Case@Example.test"]


# ----- GET /admin/users/{id} -----


def test_user_detail_for_sa(w):
    _sa, token = w.sa()
    clan, bo, _ = w.bo()
    r = w.client.get(f"/api/v1/admin/users/{bo.user_id}", headers=h(token))
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == str(bo.user_id) and body["requires_password_change"] is False
    [m] = body["memberships"]
    assert m["clan_id"] == str(clan.clan_id) and m["roles"] == ["BUSINESS_OWNER"]
    assert "firebase_uid" not in r.text and bo.firebase_uid not in r.text


def test_user_detail_not_found_and_requires_password_change(w):
    _sa, token = w.sa()
    assert code(w.client.get(f"/api/v1/admin/users/{uuid.uuid4()}", headers=h(token))) == "NOT_FOUND"
    pending = w.user("PENDING")
    w.repo.set_cred(pending, must_change_password=True)
    r = w.client.get(f"/api/v1/admin/users/{pending.user_id}", headers=h(token))
    assert r.json()["requires_password_change"] is True
    assert w.client.get("/api/v1/admin/users/not-a-uuid", headers=h(token)).status_code == 422


# ----- PATCH /admin/users/{id}/status -----


def patch(w, token, user_id, status, reason="because"):
    return w.client.patch(
        f"/api/v1/admin/users/{user_id}/status", headers=h(token),
        json={"status": status, "reason": reason},
    )


def test_lock_revokes_every_session_and_audits(w):
    _sa, token = w.sa()
    victim = w.user()
    t1, t2 = w.token(victim), w.token(victim)
    r = patch(w, token, victim.user_id, "LOCKED", "suspicious activity")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "LOCKED" and body["revoked_session_count"] == 2
    assert victim.status == "LOCKED" and w.db.commits == 1
    assert all(s.revoked_at is not None and s.revoke_reason == "USER_LOCKED"
               for s in w.repo.sessions.values() if s.user_id == victim.user_id)
    [log] = w.repo.audit
    assert (log["action"], log["entity_type"], log["entity_id"]) == ("user.status.update", "user", victim.user_id)
    assert log["old_data"] == {"status": "ACTIVE"}
    assert log["new_data"]["status"] == "LOCKED" and log["new_data"]["revoked_sessions"] == 2
    assert log["reason"] == "suspicious activity" and log["actor_id"] == _sa.user_id
    flat = str(log)
    assert victim.email not in flat and victim.firebase_uid not in flat
    assert code(w.client.get("/api/v1/admin/users", headers=h(t1))) == "SESSION_INVALID"
    assert w.client.get("/api/v1/admin/users", headers=h(token)).status_code == 200


@pytest.mark.parametrize(
    "bad",
    ["suspicious\x00activity", "\x00", "bell\x07", "lone\rcr", "\x1b[0m", "\x7f", "\x85", "   ", "x" * 2001],
    ids=["nul-inside", "nul-alone", "bell", "lone-cr", "escape", "del", "c1", "blank", "too-long"],
)
def test_a_status_reason_with_a_control_character_is_422_and_changes_nothing(w, bad):
    """A NUL used to reach the database driver and come back as a 500."""
    sa, token = w.sa()
    victim = w.user()
    w.token(victim)
    r = patch(w, token, victim.user_id, "LOCKED", bad)
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")
    assert "suspicious" not in r.json()["error"]["message"]  # the value is never echoed
    assert victim.status == "ACTIVE" and w.db.commits == 0 and w.repo.audit == []
    assert all(s.revoked_at is None for s in w.repo.sessions.values() if s.user_id == victim.user_id)  # nothing revoked


def test_a_status_reason_may_span_several_lines_and_is_stored_with_lf(w):
    sa, token = w.sa()
    victim = w.user()
    r = patch(w, token, victim.user_id, "LOCKED", "  first line\r\n\tsecond line\nthird  ")
    assert r.status_code == 200
    [log] = w.repo.audit
    assert log["reason"] == "first line\n\tsecond line\nthird"


def test_a_status_reason_at_the_length_limit_is_accepted(w):
    sa, token = w.sa()
    assert patch(w, token, w.user().user_id, "LOCKED", "x" * 2000).status_code == 200


def test_unlock_changes_status_only(w):
    _sa, token = w.sa()
    user = w.user("LOCKED")
    w.repo.set_cred(user, failed_login_count=3)
    r = patch(w, token, user.user_id, "ACTIVE")
    assert r.status_code == 200 and r.json()["revoked_session_count"] == 0
    assert user.status == "ACTIVE" and w.repo.creds[user.user_id].failed_login_count == 3


ALL = ["ACTIVE", "LOCKED", "SUSPENDED", "DISABLED", "PENDING"]


@pytest.mark.parametrize("old", ALL)
@pytest.mark.parametrize("new", ["ACTIVE", "LOCKED", "SUSPENDED", "DISABLED"])
def test_transition_table(w, old, new):
    _sa, token = w.sa()
    user = w.user(old)
    r = patch(w, token, user.user_id, new)
    if new in STATUS_TRANSITIONS[old]:
        assert r.status_code == 200 and user.status == new
    else:
        assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
        assert user.status == old and w.repo.audit == []


def test_agreed_transitions_are_exactly_these():
    assert STATUS_TRANSITIONS == {
        "ACTIVE": {"LOCKED", "SUSPENDED", "DISABLED"},
        "LOCKED": {"ACTIVE", "SUSPENDED", "DISABLED"},
        "SUSPENDED": {"ACTIVE", "LOCKED", "DISABLED"},
        "DISABLED": {"ACTIVE"},
        "PENDING": {"DISABLED"},
    }


def test_pending_cannot_be_set_and_unknown_user_is_404(w):
    _sa, token = w.sa()
    user = w.user()
    assert patch(w, token, user.user_id, "PENDING").status_code == 422
    assert code(patch(w, token, uuid.uuid4(), "LOCKED")) == "NOT_FOUND"


@pytest.mark.parametrize("body", [{"status": "LOCKED"}, {"status": "LOCKED", "reason": ""},
                                  {"status": "LOCKED", "reason": "x", "extra": 1}])
def test_status_body_validation(w, body):
    _sa, token = w.sa()
    user = w.user()
    r = w.client.patch(f"/api/v1/admin/users/{user.user_id}/status", headers=h(token), json=body)
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")
    assert user.status == "ACTIVE"


def test_cannot_lock_the_last_system_admin_not_even_self(w):
    sa, token = w.sa()
    r = patch(w, token, sa.user_id, "LOCKED")
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
    assert sa.status == "ACTIVE" and w.repo.audit == [] and w.db.commits == 0


def test_can_lock_an_sa_when_another_remains(w):
    sa, token = w.sa()
    other, _ = w.sa()
    assert patch(w, token, other.user_id, "SUSPENDED").status_code == 200
    # now `sa` is the last one again
    assert code(patch(w, token, sa.user_id, "DISABLED")) == "STATE_CONFLICT"


def test_lock_order_is_sa_set_first_then_user_row_then_count(w):
    """Deadlock guard: the SA grants are locked BEFORE the target user row."""
    sa, token = w.sa()
    other, _ = w.sa()
    w.repo.calls.clear()
    patch(w, token, other.user_id, "LOCKED")
    first_lock = w.repo.calls.index("lock")
    assert first_lock < w.repo.calls.index("lock_user") < w.repo.calls.index("count")


def test_non_blocking_change_does_not_take_the_sa_lock(w):
    _sa, token = w.sa()
    user = w.user("DISABLED")
    w.repo.calls.clear()
    patch(w, token, user.user_id, "ACTIVE")
    assert "lock" not in w.repo.calls and "lock_user" in w.repo.calls


# ----- GET /clans/{id}/users -----


def test_clan_users_lists_only_this_clan_with_roles_and_fa_flag(w):
    clan, bo, token = w.bo()
    fa, _ = w.fa(clan, FA_CODE)
    member = w.user()
    w.family.add_member(clan, member, status="SUSPENDED")
    w.repo.grant(member, "FAMILY_MEMBER", clan.clan_id)
    other_clan, other_bo, _ = w.bo()
    foreign = w.user()
    w.family.add_member(other_clan, foreign)
    w.repo.grant(foreign, "FAMILY_ADMIN", other_clan.clan_id)  # role in ANOTHER clan

    r = w.client.get(f"/api/v1/clans/{clan.clan_id}/users", headers=h(token))
    body = r.json()
    assert r.status_code == 200 and body["total"] == 3
    by_id = {i["user_id"]: i for i in body["items"]}
    assert set(by_id) == {str(bo.user_id), str(fa.user_id), str(member.user_id)}
    assert str(foreign.user_id) not in r.text and str(other_bo.user_id) not in r.text
    assert by_id[str(bo.user_id)]["roles"] == ["BUSINESS_OWNER"] and not by_id[str(bo.user_id)]["is_family_admin"]
    assert by_id[str(fa.user_id)]["is_family_admin"] is True
    assert by_id[str(member.user_id)]["membership_status"] == "SUSPENDED"
    assert "firebase_uid" not in r.text
    # REVOKED members are listed by default; the filter narrows.
    w.family.add_member(clan, w.user(), status="REVOKED")
    assert w.client.get(f"/api/v1/clans/{clan.clan_id}/users", headers=h(token)).json()["total"] == 4
    only = w.client.get(f"/api/v1/clans/{clan.clan_id}/users?membership_status=REVOKED", headers=h(token))
    assert only.json()["total"] == 1


def test_clan_users_pagination_is_capped_and_clan_filtered(w):
    clan, _bo, token = w.bo()
    for _ in range(5):
        w.family.add_member(clan, w.user())
    r = w.client.get(f"/api/v1/clans/{clan.clan_id}/users?page_size=2&page=3", headers=h(token))
    assert r.json()["total"] == 6 and len(r.json()["items"]) == 2
    assert w.client.get(f"/api/v1/clans/{clan.clan_id}/users?page_size=101", headers=h(token)).status_code == 422
    assert all(c == f"list_clan_members:{clan.clan_id}" for c in w.family.calls if c.startswith("list_clan"))


def test_clan_users_tenant_rules(w):
    clan, bo, token = w.bo()
    other, _other_bo, _ = w.bo()
    assert code(w.client.get(f"/api/v1/clans/{other.clan_id}/users", headers=h(token))) == "NOT_FOUND"
    assert code(w.client.get(f"/api/v1/clans/{uuid.uuid4()}/users", headers=h(token))) == "NOT_FOUND"
    assert code(w.client.get("/api/v1/clans/not-a-uuid/users", headers=h(token))) == "NOT_FOUND"
    plain = w.user()
    w.family.add_member(clan, plain)
    assert code(w.client.get(f"/api/v1/clans/{clan.clan_id}/users", headers=h(w.token(plain)))) == "FORBIDDEN"
    pending_clan, _bo2, token2 = w.bo("PENDING")
    assert code(w.client.get(f"/api/v1/clans/{pending_clan.clan_id}/users", headers=h(token2))) == "FORBIDDEN"


def test_fa_with_member_account_manage_can_list_but_not_edit_permissions(w):
    clan, _bo, _ = w.bo()
    fa, _ = w.fa(clan, FA_CODE)
    token = w.token(fa)
    assert w.client.get(f"/api/v1/clans/{clan.clan_id}/users", headers=h(token)).status_code == 200
    r = w.client.put(
        f"/api/v1/clans/{clan.clan_id}/admins/{fa.user_id}/permissions",
        headers=h(token), json={"permission_codes": []},
    )
    assert (r.status_code, code(r)) == (403, "FORBIDDEN")
    other_fa, _ = w.fa(clan, "PERSON_VIEW")
    assert code(w.client.get(f"/api/v1/clans/{clan.clan_id}/users", headers=h(w.token(other_fa)))) == "FORBIDDEN"


# ----- PUT /clans/{id}/admins/{user_id}/permissions -----


def put(w, token, clan, user, codes):
    return w.client.put(
        f"/api/v1/clans/{clan.clan_id}/admins/{user.user_id}/permissions",
        headers=h(token), json={"permission_codes": codes},
    )


def test_bo_replaces_the_permission_set_and_it_takes_effect_at_once(w):
    clan, bo, token = w.bo()
    fa, assignment = w.fa(clan, "PERSON_VIEW", "TREE_VIEW")
    fa_token = w.token(fa)
    assert code(w.client.get(f"/api/v1/clans/{clan.clan_id}/users", headers=h(fa_token))) == "FORBIDDEN"

    r = put(w, token, clan, fa, [FA_CODE, "PERSON_VIEW"])
    assert r.status_code == 200
    body = r.json()
    assert body["permission_codes"] == sorted([FA_CODE, "PERSON_VIEW"])
    assert body["assignment_id"] == str(assignment.assignment_id)
    assert assignment.codes == {FA_CODE, "PERSON_VIEW"}
    assert w.client.get(f"/api/v1/clans/{clan.clan_id}/users", headers=h(fa_token)).status_code == 200
    [log] = w.repo.audit
    assert log["action"] == "family_admin.permissions.update" and log["clan_id"] == clan.clan_id
    assert log["actor_id"] == bo.user_id and log["entity_id"] == assignment.assignment_id
    assert log["old_data"]["permission_codes"] == ["PERSON_VIEW", "TREE_VIEW"]
    assert log["new_data"]["permission_codes"] == sorted([FA_CODE, "PERSON_VIEW"])

    # Revoking the key permission takes effect on the very next request.
    assert put(w, token, clan, fa, ["PERSON_VIEW"]).status_code == 200
    assert code(w.client.get(f"/api/v1/clans/{clan.clan_id}/users", headers=h(fa_token))) == "FORBIDDEN"


def test_empty_list_removes_permissions_and_keeps_the_assignment(w):
    clan, _bo, token = w.bo()
    fa, assignment = w.fa(clan, FA_CODE)
    r = put(w, token, clan, fa, [])
    assert r.status_code == 200 and r.json()["permission_codes"] == []
    assert assignment.codes == set() and assignment.revoked is False


def test_unchanged_set_is_ok_without_write_or_audit(w):
    clan, _bo, token = w.bo()
    fa, _ = w.fa(clan, FA_CODE)
    r = put(w, token, clan, fa, [FA_CODE])
    assert r.status_code == 200 and w.repo.audit == [] and w.db.commits == 0
    assert "add_fa_permissions" not in w.family.calls


def test_unknown_permission_code_is_422_and_changes_nothing(w):
    clan, _bo, token = w.bo()
    fa, assignment = w.fa(clan, FA_CODE)
    r = put(w, token, clan, fa, [FA_CODE, "MADE_UP_CODE"])
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")
    assert "MADE_UP_CODE" not in r.text and assignment.codes == {FA_CODE}


@pytest.mark.parametrize("codes", [["A", "A"], ["bad code"], [""], ["X" * 101]])
def test_permission_code_shape_validation(w, codes):
    clan, _bo, token = w.bo()
    fa, _ = w.fa(clan, FA_CODE)
    assert put(w, token, clan, fa, codes).status_code == 422


def test_target_must_be_an_active_fa_of_this_clan(w):
    clan, _bo, token = w.bo()
    plain = w.user()
    w.family.add_member(clan, plain)
    assert code(put(w, token, clan, plain, [FA_CODE])) == "NOT_FOUND"          # member, no assignment
    stranger = w.user()
    assert code(put(w, token, clan, stranger, [FA_CODE])) == "NOT_FOUND"       # not a member
    revoked, _ = w.fa(clan, FA_CODE)
    w.family.assignments[-1].revoked = True
    assert code(put(w, token, clan, revoked, [FA_CODE])) == "NOT_FOUND"        # revoked assignment
    suspended, _ = w.fa(clan, FA_CODE)
    next(m for m in w.family.memberships if m.user_id == suspended.user_id).status = "SUSPENDED"
    assert code(put(w, token, clan, suspended, [FA_CODE])) == "NOT_FOUND"      # membership not ACTIVE
    other_clan, _bo2, _ = w.bo()
    foreign, _ = w.fa(other_clan, FA_CODE)
    assert code(put(w, token, clan, foreign, [FA_CODE])) == "NOT_FOUND"        # FA of another clan


def test_branch_limited_assignment_alone_is_404_and_two_clan_wide_is_409(w):
    clan, _bo, token = w.bo()
    fa, _ = w.fa(clan, FA_CODE, branch_id=uuid.uuid4())
    assert code(put(w, token, clan, fa, [FA_CODE])) == "NOT_FOUND"
    # A branch-limited assignment next to a clan-wide one is left untouched.
    w.family.add_fa_assignment(clan, fa, ["PERSON_VIEW"])
    branch = next(a for a in w.family.assignments if a.branch_id is not None)
    assert put(w, token, clan, fa, [FA_CODE]).status_code == 200 and branch.codes == {FA_CODE}
    w.family.add_fa_assignment(clan, fa, ["TREE_VIEW"])  # second clan-wide one
    r = put(w, token, clan, fa, [FA_CODE])
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")


def test_bo_of_another_clan_gets_404_and_nothing_changes(w):
    clan, _bo, _ = w.bo()
    fa, assignment = w.fa(clan, FA_CODE)
    _other, _other_bo, other_token = w.bo()
    r = w.client.put(
        f"/api/v1/clans/{clan.clan_id}/admins/{fa.user_id}/permissions",
        headers=h(other_token), json={"permission_codes": []},
    )
    assert (r.status_code, code(r)) == (404, "NOT_FOUND") and assignment.codes == {FA_CODE}


def test_inactive_clan_blocks_permission_updates(w):
    clan, _bo, token = w.bo("SUSPENDED")
    fa, assignment = w.fa(clan, FA_CODE)
    assert code(put(w, token, clan, fa, [])) == "FORBIDDEN" and assignment.codes == {FA_CODE}


def test_commit_failure_is_503(w):
    _sa, token = w.sa()
    victim = w.user()
    w.db.fail_commit = True
    r = patch(w, token, victim.user_id, "LOCKED")
    assert (r.status_code, code(r)) == (503, "DATABASE_UNAVAILABLE")


# ----- lock modes (deadlock guard, proven against Postgres in the concurrency tests) -----


class _CaptureSession:
    def __init__(self) -> None:
        self.statements: list = []

    async def execute(self, stmt):
        self.statements.append(stmt)

        class _Result:
            def scalar_one_or_none(self_inner):
                return None

        return _Result()


async def test_target_user_row_is_locked_with_no_key_update_not_for_update():
    """FOR UPDATE on users would block the FK KEY SHARE taken by audit/login inserts and
    deadlock two SAs that lock each other. NO KEY UPDATE does not."""
    from sqlalchemy.dialects import postgresql

    from app.models.user_access.repository import UserAccessRepository

    session = _CaptureSession()
    await UserAccessRepository(session).get_user_for_update(uuid.uuid4())
    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "FOR NO KEY UPDATE" in sql and "FOR UPDATE" not in sql.replace("FOR NO KEY UPDATE", "")


async def test_fa_assignment_rows_are_locked_with_no_key_update():
    from sqlalchemy.dialects import postgresql

    session = _CaptureSession()

    class _Rows(_CaptureSession):
        async def execute(self, stmt):
            self.statements.append(stmt)

            class _R:
                def scalars(self_inner):
                    class _S:
                        def all(self_s):
                            return []

                    return _S()

            return _R()

    session = _Rows()
    await FamilyRepository(session).lock_active_fa_assignments(uuid.uuid4(), uuid.uuid4())
    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "FOR NO KEY UPDATE" in sql and "ORDER BY family_admin_assignments.assignment_id" in sql


# =====================================================================================
# Mốc F2: appoint and revoke Family Admin
# =====================================================================================

from app.dependencies.permissions import (  # noqa: E402
    ACTION_RULES,
    NON_DELEGABLE_PERMISSION_CODES,
    Action,
    owner_actions,
)
from sqlalchemy.exc import IntegrityError  # noqa: E402


def make_member(w, clan, status="ACTIVE"):
    user = w.user()
    w.family.add_member(clan, user, status=status)
    return user


def post_admin(w, token, clan, user_id, codes=None, **extra):
    body = {"user_id": str(user_id), **extra}
    if codes is not None:
        body["permission_codes"] = codes
    return w.client.post(f"/api/v1/clans/{clan.clan_id}/admins", headers=h(token), json=body)


def delete_admin(w, token, clan, user_id):
    return w.client.delete(f"/api/v1/clans/{clan.clan_id}/admins/{user_id}", headers=h(token))


def active_assignments(w, clan, user):
    return [
        a for a in w.family.assignments
        if a.clan_id == clan.clan_id and a.user_id == user.user_id and not a.revoked
    ]


def active_fa_roles(w, clan, user):
    return [
        g for g in w.repo.roles
        if g.user_id == user.user_id and g.clan_id == clan.clan_id
        and g.role_code == "FAMILY_ADMIN" and not g.revoked
    ]


# ----- policy surface -----


def test_new_actions_are_bo_only_like_the_existing_fa_permissions_action():
    reference = ACTION_RULES[Action.CLAN_FA_PERMISSIONS_UPDATE]
    assert ACTION_RULES[Action.CLAN_FA_ASSIGN] == reference
    assert ACTION_RULES[Action.CLAN_FA_REVOKE] == reference
    assert reference.allow_owner and reference.fa_permission is None
    assert {"clan.fa.assign", "clan.fa.revoke"} <= set(owner_actions())


def test_only_admin_manage_is_non_delegable():
    assert NON_DELEGABLE_PERMISSION_CODES == frozenset({"ADMIN_MANAGE"})


# ----- POST /clans/{id}/admins -----


def test_bo_appoints_a_member_and_it_takes_effect_at_once(w):
    clan, bo, token = w.bo()
    member = make_member(w, clan)
    member_token = w.token(member)
    url = f"/api/v1/clans/{clan.clan_id}/users"
    assert code(w.client.get(url, headers=h(member_token))) == "FORBIDDEN"

    r = post_admin(w, token, clan, member.user_id, [FA_CODE, "PERSON_VIEW"])
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"clan_id", "user_id", "assignment_id", "permission_codes", "created_at"}
    assert body["user_id"] == str(member.user_id) and body["clan_id"] == str(clan.clan_id)
    assert body["permission_codes"] == sorted([FA_CODE, "PERSON_VIEW"])
    [assignment] = active_assignments(w, clan, member)
    assert str(assignment.assignment_id) == body["assignment_id"]
    assert assignment.branch_id is None and assignment.codes == {FA_CODE, "PERSON_VIEW"}
    assert len(active_fa_roles(w, clan, member)) == 1 and w.db.commits == 1

    assert w.client.get(url, headers=h(member_token)).status_code == 200  # next request
    listed = {i["user_id"]: i for i in w.client.get(url, headers=h(token)).json()["items"]}
    assert listed[str(member.user_id)]["is_family_admin"] is True
    assert "FAMILY_ADMIN" in listed[str(member.user_id)]["roles"]

    [log] = w.repo.audit
    assert log["action"] == "family_admin.assign" and log["clan_id"] == clan.clan_id
    assert log["actor_id"] == bo.user_id and log["entity_id"] == assignment.assignment_id
    assert log["old_data"] is None
    assert log["new_data"]["user_id"] == str(member.user_id)
    assert log["new_data"]["permission_codes"] == sorted([FA_CODE, "PERSON_VIEW"])
    assert log["new_data"]["role_granted"] is True
    assert member.firebase_uid not in str(log) + r.text and member.email not in str(log)


def test_permission_codes_are_optional_and_may_be_empty(w):
    clan, _bo, token = w.bo()
    omitted, empty = make_member(w, clan), make_member(w, clan)
    r = post_admin(w, token, clan, omitted.user_id)
    assert r.status_code == 201 and r.json()["permission_codes"] == []
    r = post_admin(w, token, clan, empty.user_id, [])
    assert r.status_code == 201 and r.json()["permission_codes"] == []
    assert active_assignments(w, clan, omitted)[0].codes == set()


def test_a_new_assignment_can_be_edited_with_the_existing_put(w):
    clan, _bo, token = w.bo()
    member = make_member(w, clan)
    new_id = post_admin(w, token, clan, member.user_id, ["PERSON_VIEW"]).json()["assignment_id"]
    r = put(w, token, clan, member, [FA_CODE])
    assert r.status_code == 200
    assert r.json()["assignment_id"] == new_id and r.json()["permission_codes"] == [FA_CODE]
    assert w.client.get(f"/api/v1/clans/{clan.clan_id}/users", headers=h(w.token(member))).status_code == 200


def test_non_delegable_code_is_403_and_nothing_is_created(w):
    clan, _bo, token = w.bo()
    member = make_member(w, clan)
    for codes in (["ADMIN_MANAGE"], [FA_CODE, "ADMIN_MANAGE"], ["MADE_UP", "ADMIN_MANAGE"]):
        r = post_admin(w, token, clan, member.user_id, codes)
        assert (r.status_code, code(r)) == (403, "FORBIDDEN")
        assert "ADMIN_MANAGE" not in r.text  # codes are never echoed
    assert active_assignments(w, clan, member) == [] and w.repo.audit == [] and w.db.commits == 0


def test_unknown_code_is_422_and_changes_nothing(w):
    clan, _bo, token = w.bo()
    member = make_member(w, clan)
    r = post_admin(w, token, clan, member.user_id, [FA_CODE, "MADE_UP_CODE"])
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR") and "MADE_UP_CODE" not in r.text
    assert active_assignments(w, clan, member) == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"user_id": "not-a-uuid"},
        {"user_id": str(uuid.uuid4()), "permission_codes": ["A", "A"]},
        {"user_id": str(uuid.uuid4()), "permission_codes": ["bad code"]},
        {"user_id": str(uuid.uuid4()), "branch_id": str(uuid.uuid4())},  # no branch scoping
        {"user_id": str(uuid.uuid4()), "extra": 1},
    ],
)
def test_assign_body_validation(w, body):
    clan, _bo, token = w.bo()
    r = w.client.post(f"/api/v1/clans/{clan.clan_id}/admins", headers=h(token), json=body)
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")


def test_target_must_be_an_active_member_of_this_clan(w):
    clan, _bo, token = w.bo()
    assert code(post_admin(w, token, clan, uuid.uuid4())) == "NOT_FOUND"           # unknown user
    assert code(post_admin(w, token, clan, w.user().user_id)) == "NOT_FOUND"       # not a member
    for status in ("INVITED", "SUSPENDED", "REVOKED"):
        member = make_member(w, clan, status)
        assert code(post_admin(w, token, clan, member.user_id)) == "NOT_FOUND", status
    revoked_at = make_member(w, clan)
    next(m for m in w.family.memberships if m.user_id == revoked_at.user_id).revoked_at = utcnow()
    assert code(post_admin(w, token, clan, revoked_at.user_id)) == "NOT_FOUND"
    other_clan, _bo2, _ = w.bo()
    foreign = make_member(w, other_clan)                                             # member elsewhere
    assert code(post_admin(w, token, clan, foreign.user_id)) == "NOT_FOUND"
    assert w.repo.audit == [] and w.family.assignments == []


def test_already_a_family_admin_is_409(w):
    clan, _bo, token = w.bo()
    fa, assignment = w.fa(clan, FA_CODE)
    r = post_admin(w, token, clan, fa.user_id, ["PERSON_VIEW"])
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
    assert assignment.codes == {FA_CODE} and len(active_assignments(w, clan, fa)) == 1
    limited_only = make_member(w, clan)
    w.family.add_fa_assignment(clan, limited_only, [FA_CODE], branch_id=uuid.uuid4())
    assert code(post_admin(w, token, clan, limited_only.user_id)) == "STATE_CONFLICT"
    assert w.repo.audit == []


def test_the_owner_and_other_business_owner_role_holders_cannot_be_appointed(w):
    clan, bo, token = w.bo()
    r = post_admin(w, token, clan, bo.user_id, [FA_CODE])           # the BO appoints themselves
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
    former = make_member(w, clan)                                    # still holds the BO role
    w.repo.grant(former, "BUSINESS_OWNER", clan.clan_id)
    assert code(post_admin(w, token, clan, former.user_id)) == "STATE_CONFLICT"
    assert w.family.assignments == [] and w.repo.audit == []


def test_reappointing_after_a_revoke_creates_a_new_assignment_and_role(w):
    clan, _bo, token = w.bo()
    member = make_member(w, clan)
    first = post_admin(w, token, clan, member.user_id, ["PERSON_VIEW"]).json()["assignment_id"]
    assert delete_admin(w, token, clan, member.user_id).status_code == 204
    second = post_admin(w, token, clan, member.user_id, [FA_CODE])
    assert second.status_code == 201 and second.json()["assignment_id"] != first
    assert len(active_assignments(w, clan, member)) == 1 and len(active_fa_roles(w, clan, member)) == 1
    old = next(a for a in w.family.assignments if str(a.assignment_id) == first)
    assert old.revoked and old.codes == set()  # history stays revoked, not reactivated


def test_an_existing_active_family_admin_role_row_is_not_duplicated(w):
    clan, _bo, token = w.bo()
    member = make_member(w, clan)
    w.repo.grant(member, "FAMILY_ADMIN", clan.clan_id)               # e.g. created by hand/seed
    assert post_admin(w, token, clan, member.user_id).status_code == 201
    assert len(active_fa_roles(w, clan, member)) == 1
    assert w.repo.audit[-1]["new_data"]["role_granted"] is False
    assert "add_clan_role" not in w.repo.calls


def test_lost_race_on_the_role_row_is_409_and_rolled_back(w, monkeypatch):
    clan, _bo, token = w.bo()
    member = make_member(w, clan)

    async def collide(**_kwargs):
        raise IntegrityError("INSERT user_roles", {}, Exception("uq_active_user_role_scope"))

    monkeypatch.setattr(w.repo, "add_clan_role", collide)
    r = post_admin(w, token, clan, member.user_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
    assert w.db.rollbacks == 1 and w.db.commits == 0


def test_lost_race_on_the_assignment_index_is_409_and_rolled_back(w, monkeypatch):
    """Migration 0002 (KI-08): uq_family_admin_active_assignment is the last line of defence.

    A request that gets past the membership lock and loses at INSERT gets the same 409 as the
    one that loses at the lock, never a 500, and nothing stays written.
    """
    clan, _bo, token = w.bo()
    member = make_member(w, clan)

    async def collide(*_args, **_kwargs):
        raise IntegrityError(
            "INSERT family_admin_assignments", {}, Exception("uq_family_admin_active_assignment")
        )

    monkeypatch.setattr(w.family, "create_fa_assignment", collide)
    r = post_admin(w, token, clan, member.user_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
    assert w.db.rollbacks == 1 and w.db.commits == 0
    assert w.repo.audit == [] and w.family.assignments == []


def test_missing_family_admin_role_is_a_500_not_a_leak(w):
    clan, _bo, token = w.bo()
    member = make_member(w, clan)
    w.repo.role_codes_present.discard("FAMILY_ADMIN")
    quiet = TestClient(w.client.app, raise_server_exceptions=False)
    r = quiet.post(f"/api/v1/clans/{clan.clan_id}/admins", headers=h(token),
                   json={"user_id": str(member.user_id)})
    assert (r.status_code, code(r)) == (500, "INTERNAL_ERROR") and "FAMILY_ADMIN" not in r.text


def test_assign_lock_order_is_membership_then_assignments_then_role(w):
    clan, _bo, token = w.bo()
    member = make_member(w, clan)
    w.family.calls.clear()
    w.repo.calls.clear()
    post_admin(w, token, clan, member.user_id, [FA_CODE])
    order = w.family.calls
    assert order.index("lock_membership") < order.index("lock_fa") < order.index("create_fa_assignment")
    assert "lock_user" not in w.repo.calls  # never a FOR UPDATE on the users row
    assert w.repo.calls.index("add_clan_role") >= 0


def test_assign_access_rules(w):
    clan, bo, token = w.bo()
    member = make_member(w, clan)
    # unauthenticated, FA (even with MEMBER_ACCOUNT_MANAGE) and plain members: 401/403
    assert w.client.post(f"/api/v1/clans/{clan.clan_id}/admins", json={"user_id": str(member.user_id)}).status_code == 401
    fa, _ = w.fa(clan, FA_CODE)
    assert code(post_admin(w, w.token(fa), clan, member.user_id)) == "FORBIDDEN"
    assert code(post_admin(w, w.token(member), clan, member.user_id)) == "FORBIDDEN"
    # BO of another clan and a System Admin cannot even see this clan
    _other, _bo2, other_token = w.bo()
    assert code(post_admin(w, other_token, clan, member.user_id)) == "NOT_FOUND"
    _sa, sa_token = w.sa()
    assert code(post_admin(w, sa_token, clan, member.user_id)) == "NOT_FOUND"
    assert code(post_admin(w, token, type("C", (), {"clan_id": uuid.uuid4()})(), member.user_id)) == "NOT_FOUND"
    assert w.client.post("/api/v1/clans/not-a-uuid/admins", headers=h(token),
                         json={"user_id": str(member.user_id)}).status_code == 404
    pending_clan, _bo3, pending_token = w.bo("PENDING")
    target = make_member(w, pending_clan)
    assert code(post_admin(w, pending_token, pending_clan, target.user_id)) == "FORBIDDEN"
    assert active_assignments(w, clan, member) == []
    assert bo is not None


def test_authorization_wins_over_validation_for_assign(w):
    clan, _bo, _ = w.bo()
    plain = make_member(w, clan)
    r = w.client.post(f"/api/v1/clans/{clan.clan_id}/admins", headers=h(w.token(plain)), json={"bad": 1})
    assert (r.status_code, code(r)) == (403, "FORBIDDEN")


# ----- PUT and the non-delegable code -----


def test_put_rejects_admin_manage_with_403(w):
    clan, _bo, token = w.bo()
    fa, assignment = w.fa(clan, FA_CODE)
    r = put(w, token, clan, fa, [FA_CODE, "ADMIN_MANAGE"])
    assert (r.status_code, code(r)) == (403, "FORBIDDEN") and "ADMIN_MANAGE" not in r.text
    assert assignment.codes == {FA_CODE} and w.repo.audit == []


def test_put_keeping_an_existing_admin_manage_is_403_and_dropping_it_works(w):
    """Consequence accepted in the contract (decision 30): the legacy code must be removed."""
    clan, _bo, token = w.bo()
    fa, assignment = w.fa(clan, FA_CODE, "ADMIN_MANAGE")
    assert code(put(w, token, clan, fa, [FA_CODE, "ADMIN_MANAGE"])) == "FORBIDDEN"
    assert assignment.codes == {FA_CODE, "ADMIN_MANAGE"}
    r = put(w, token, clan, fa, [FA_CODE])
    assert r.status_code == 200 and assignment.codes == {FA_CODE}


# ----- DELETE /clans/{id}/admins/{user_id} -----


def test_bo_revokes_a_family_admin_with_immediate_effect(w):
    clan, bo, token = w.bo()
    member = make_member(w, clan)
    post_admin(w, token, clan, member.user_id, [FA_CODE, "PERSON_VIEW"])
    member_token = w.token(member)
    url = f"/api/v1/clans/{clan.clan_id}/users"
    assert w.client.get(url, headers=h(member_token)).status_code == 200

    r = delete_admin(w, token, clan, member.user_id)
    assert r.status_code == 204 and r.content == b""
    assert code(w.client.get(url, headers=h(member_token))) == "FORBIDDEN"  # next request
    assert active_assignments(w, clan, member) == [] and active_fa_roles(w, clan, member) == []
    assert all(a.codes == set() for a in w.family.assignments)               # permission rows deleted
    assert next(m for m in w.family.memberships if m.user_id == member.user_id).status == "ACTIVE"
    log = w.repo.audit[-1]
    assert log["action"] == "family_admin.revoke" and log["clan_id"] == clan.clan_id
    assert log["actor_id"] == bo.user_id
    assert log["old_data"]["user_id"] == str(member.user_id)
    assert log["old_data"]["permission_codes"] == sorted([FA_CODE, "PERSON_VIEW"])  # history kept here
    assert log["new_data"]["revoked_assignments"] == 1 and log["new_data"]["roles_revoked"] == 1
    assert member.firebase_uid not in str(log) and member.email not in str(log)
    # PUT on a revoked assignment: 404
    assert code(put(w, token, clan, member, [FA_CODE])) == "NOT_FOUND"


def test_revoke_takes_every_active_assignment_including_branch_limited_and_duplicates(w):
    clan, _bo, token = w.bo()
    fa, wide = w.fa(clan, FA_CODE)
    limited = w.family.add_fa_assignment(clan, fa, ["PERSON_VIEW"], branch_id=uuid.uuid4())
    duplicate = w.family.add_fa_assignment(clan, fa, ["TREE_VIEW"])
    other_fa, other = w.fa(clan, FA_CODE)                       # a different user is untouched
    assert delete_admin(w, token, clan, fa.user_id).status_code == 204
    for row in (wide, limited, duplicate):
        assert row.revoked and row.codes == set()
    assert not other.revoked and other.codes == {FA_CODE}
    assert w.repo.audit[-1]["new_data"]["revoked_assignments"] == 3
    assert other_fa is not None


def test_a_member_who_is_no_longer_active_can_still_be_revoked(w):
    clan, _bo, token = w.bo()
    fa, assignment = w.fa(clan, FA_CODE)
    next(m for m in w.family.memberships if m.user_id == fa.user_id).status = "SUSPENDED"
    assert delete_admin(w, token, clan, fa.user_id).status_code == 204 and assignment.revoked


def test_revoke_of_someone_who_is_not_a_family_admin_is_404(w):
    clan, bo, token = w.bo()
    plain = make_member(w, clan)
    assert code(delete_admin(w, token, clan, plain.user_id)) == "NOT_FOUND"     # member, not FA
    assert code(delete_admin(w, token, clan, w.user().user_id)) == "NOT_FOUND"  # not a member
    assert code(delete_admin(w, token, clan, uuid.uuid4())) == "NOT_FOUND"      # unknown
    assert code(delete_admin(w, token, clan, bo.user_id)) == "NOT_FOUND"        # the BO is not an FA
    gone, assignment = w.fa(clan, FA_CODE)
    assignment.revoked = True
    assert code(delete_admin(w, token, clan, gone.user_id)) == "NOT_FOUND"      # already revoked
    other_clan, _bo2, _ = w.bo()
    foreign, _ = w.fa(other_clan, FA_CODE)
    assert code(delete_admin(w, token, clan, foreign.user_id)) == "NOT_FOUND"   # FA of another clan
    assert w.repo.audit == []


def test_revoke_access_rules(w):
    clan, _bo, token = w.bo()
    fa, assignment = w.fa(clan, FA_CODE)
    other_fa, _ = w.fa(clan, FA_CODE)
    assert w.client.delete(f"/api/v1/clans/{clan.clan_id}/admins/{fa.user_id}").status_code == 401
    assert code(delete_admin(w, w.token(other_fa), clan, fa.user_id)) == "FORBIDDEN"   # FA cannot
    assert code(delete_admin(w, w.token(fa), clan, fa.user_id)) == "FORBIDDEN"         # not even self
    _o, _b, other_token = w.bo()
    assert code(delete_admin(w, other_token, clan, fa.user_id)) == "NOT_FOUND"
    _sa, sa_token = w.sa()
    assert code(delete_admin(w, sa_token, clan, fa.user_id)) == "NOT_FOUND"
    inactive, _ib, inactive_token = w.bo("SUSPENDED")
    inactive_fa, inactive_assignment = w.fa(inactive, FA_CODE)
    assert code(delete_admin(w, inactive_token, inactive, inactive_fa.user_id)) == "FORBIDDEN"
    assert w.client.delete(f"/api/v1/clans/{clan.clan_id}/admins/not-a-uuid", headers=h(token)).status_code == 422
    assert not assignment.revoked and not inactive_assignment.revoked


def test_full_lifecycle_appoint_edit_revoke_and_appoint_again(w):
    clan, _bo, token = w.bo()
    member = make_member(w, clan)
    first = post_admin(w, token, clan, member.user_id, ["PERSON_VIEW"]).json()["assignment_id"]
    assert put(w, token, clan, member, [FA_CODE, "TREE_VIEW"]).status_code == 200
    assert delete_admin(w, token, clan, member.user_id).status_code == 204
    assert code(put(w, token, clan, member, [FA_CODE])) == "NOT_FOUND"
    assert code(delete_admin(w, token, clan, member.user_id)) == "NOT_FOUND"   # second delete: 404
    again = post_admin(w, token, clan, member.user_id, [FA_CODE])
    assert again.status_code == 201 and again.json()["assignment_id"] != first
    assert [log["action"] for log in w.repo.audit] == [
        "family_admin.assign", "family_admin.permissions.update",
        "family_admin.revoke", "family_admin.assign",
    ]
