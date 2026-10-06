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
