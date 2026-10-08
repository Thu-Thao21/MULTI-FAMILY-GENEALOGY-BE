"""POST /admin/clans/{id}/activate and GET /admin/clans/{id} over HTTP (Mốc E, step E7): the real routers
and the real authorization on fake repositories, with a unit of work that really rolls back (OwnerTx).

Who may call, every condition and what its 409 says, the rows written, the dates (calendar months, 31
January, leap years), the audit (nothing personal), the lock order, atomicity, and the road a new Owner
walks: provisioned, first login with the temporary password, password change, and the clan becoming
usable ONLY when the SA activates it, in either order."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import app.controllers.family_management.clan_admin_use_cases as clan_cases
import app.controllers.family_management.owner_provisioning_use_cases as owner_cases
from app.controllers.auth_access.user_admin_router import router as user_admin_router
from app.controllers.family_management.clan_admin_router import router as clan_router
from app.core.dates import add_months
from tests.fakes import make_user
from tests.test_owner_provisioning_api import (
    FROZEN,
    OWNER_EMAIL,
    OWNER_NAME,
    OWNER_PHONE,
    OwnerWorld,
    app_logs,
    code,
    everything_stored,
)

PERSONAL = (OWNER_EMAIL, OWNER_EMAIL.lower(), OWNER_NAME, OWNER_PHONE)


class ActWorld(OwnerWorld):
    def __init__(self, **kw) -> None:
        super().__init__(raise_server_exceptions=False, **kw)
        self.repo.calls = self.family.calls  # ONE list: the order of locks across the repositories
        self.client.app.include_router(clan_router, prefix="/api/v1")
        self.client.app.include_router(user_admin_router, prefix="/api/v1")

    @staticmethod
    def _h(token):
        return {"Authorization": f"Bearer {token}"}

    def activate(self, token, clan_id, **kw):
        self.tx.begin()
        return self.client.post(f"/api/v1/admin/clans/{clan_id}/activate", headers=self._h(token), **kw)

    def read(self, token, clan_id):
        return self.client.get(f"/api/v1/admin/clans/{clan_id}", headers=self._h(token))

    def subscription(self, clan, plan, *, status="PENDING", starts=None, months=None, ends=None):
        starts = starts or FROZEN - timedelta(days=3)  # the provisional dates E5 wrote
        ends = ends or add_months(starts, months or plan.billing_period_months)
        return asyncio.run(self.family.create_subscription(
            clan_id=clan.clan_id, plan_id=plan.plan_id, starts_at=starts, ends_at=ends, status=status, now=starts))

    def ready(self, *, owner_status="PENDING", months=12, plan_status="ACTIVE", clan_status="PENDING"):
        """A clan with an Owner (member, role, ownership) and one PENDING subscription."""
        clan = self.family.add_clan(clan_status)
        clan.registration_id = uuid.uuid4()
        plan = self.family.add_plan(f"PLAN-{uuid.uuid4().hex[:6]}", months=months, status=plan_status)
        owner = self.user(owner_status)
        self.repo.grant(owner, "BUSINESS_OWNER", clan.clan_id)
        self.family.add_owner(clan, owner)
        self.family.add_member(clan, owner)
        sub = self.subscription(clan, plan)
        return clan, owner, sub, plan

    def audit(self):
        return [a for a in self.repo.audit if a["action"] == "clan.activate"]


@pytest.fixture
def clock():
    return [FROZEN]


@pytest.fixture
def w(monkeypatch, clock) -> ActWorld:
    monkeypatch.setattr(clan_cases, "utcnow", lambda: clock[0])
    monkeypatch.setattr(owner_cases, "utcnow", lambda: clock[0])
    return ActWorld()


def unchanged(w, clan, sub, before):
    assert (clan.status, clan.activated_at, clan.updated_at) == before[:3]
    assert (sub.status, sub.starts_at, sub.ends_at) == before[3:]
    assert not w.audit()


def snapshot(clan, sub):
    return (clan.status, clan.activated_at, clan.updated_at, sub.status, sub.starts_at, sub.ends_at)


# ------------------------------------------------------------------ who may call


def test_nobody_but_a_system_admin_reaches_either_route(w):
    sa, sa_token = w.sa()
    clan, owner, sub, _plan = w.ready()
    owner.status = "ACTIVE"  # (an Owner who already changed the password: a PENDING one holds only a restricted session)
    outsider = w.user()
    scoped_sa = w.user()
    w.repo.grant(scoped_sa, "SYSTEM_ADMIN", clan.clan_id)  # a System Admin tied to ONE clan is not a system admin
    before = snapshot(clan, sub)
    for who in (owner, outsider, scoped_sa):
        token = w.token(who)
        for r in (w.activate(token, clan.clan_id), w.activate(token, "not-a-uuid"),  # 403 before validation
                  w.read(token, clan.clan_id), w.read(token, "not-a-uuid")):
            assert (r.status_code, code(r)) == (403, "FORBIDDEN")
    assert w.client.post(f"/api/v1/admin/clans/{clan.clan_id}/activate").status_code == 401
    assert w.client.get(f"/api/v1/admin/clans/{clan.clan_id}").status_code == 401
    restricted = w.user("PENDING", first_login_required=True)
    w.repo.grant(restricted, "SYSTEM_ADMIN")
    w.repo.set_cred(restricted, must_change_password=True)
    assert w.activate(w.token(restricted), clan.clan_id).status_code == 403
    unchanged(w, clan, sub, before)


def test_unknown_clans_are_404_and_bad_ids_are_422(w):
    _sa, token = w.sa()
    for r in (w.activate(token, uuid.uuid4()), w.read(token, uuid.uuid4())):
        assert (r.status_code, code(r)) == (404, "NOT_FOUND")
    for r in (w.activate(token, "x"), w.read(token, "x")):
        assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")


def test_the_route_is_guarded_by_exactly_the_planned_actions():
    from app.dependencies.permissions import Action
    from tests.test_owner_recovery_api import _actions_of

    wanted = {("POST", "/admin/clans/{clan_id}/activate"): Action.CLAN_ACTIVATE, ("GET", "/admin/clans/{clan_id}"): Action.CLAN_READ}
    assert {(m, r.path): _actions_of(r) for r in clan_router.routes for m in r.methods} == {k: [v] for k, v in wanted.items()}


# ------------------------------------------------------------------ success


def test_an_activation_makes_the_clan_and_its_subscription_active_from_now(w):
    sa, token = w.sa()
    clan, owner, sub, plan = w.ready(months=12)
    old = (sub.starts_at, sub.ends_at)
    commits = w.tx.events.count("commit")
    r = w.activate(token, clan.clan_id)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store", r.text
    body = r.json()
    assert set(body) == {"clan_id", "status", "activated_at", "subscription_id", "subscription_status", "starts_at", "ends_at"}
    assert (body["clan_id"], body["status"], body["subscription_id"], body["subscription_status"]) == (str(clan.clan_id), "ACTIVE", str(sub.subscription_id), "ACTIVE")
    assert datetime.fromisoformat(body["activated_at"]) == FROZEN == datetime.fromisoformat(body["starts_at"])
    assert datetime.fromisoformat(body["ends_at"]) == add_months(FROZEN, 12)
    assert (clan.status, clan.activated_at, clan.updated_at) == ("ACTIVE", FROZEN, FROZEN)
    assert (sub.status, sub.starts_at, sub.ends_at) == ("ACTIVE", FROZEN, add_months(FROZEN, 12))
    assert (sub.starts_at, sub.ends_at) != old  # the provisional dates of E5 are replaced
    assert w.tx.events.count("commit") == commits + 1  # ONE commit
    assert "rollback" not in w.tx.events[-2:]


@pytest.mark.parametrize("now, months, ends", [
    (datetime(2026, 1, 31, 8, 30, tzinfo=timezone.utc), 1, datetime(2026, 2, 28, 8, 30, tzinfo=timezone.utc)),
    (datetime(2028, 1, 31, 8, 30, tzinfo=timezone.utc), 1, datetime(2028, 2, 29, 8, 30, tzinfo=timezone.utc)),
    (datetime(2028, 2, 29, 23, 59, 59, tzinfo=timezone.utc), 12, datetime(2029, 2, 28, 23, 59, 59, tzinfo=timezone.utc)),
    (datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc), 6, datetime(2027, 4, 8, 9, 0, tzinfo=timezone.utc)),
    (datetime(2026, 12, 15, 0, 0, tzinfo=timezone.utc), 3, datetime(2027, 3, 15, 0, 0, tzinfo=timezone.utc)),
])
def test_the_subscription_lasts_the_plans_calendar_months_from_the_moment_of_activation(w, clock, now, months, ends):
    _sa, token = w.sa()
    clan, _owner, sub, _plan = w.ready(months=months)
    clock[0] = now
    r = w.activate(token, clan.clan_id)
    assert r.status_code == 200
    assert (sub.starts_at, sub.ends_at) == (now, ends) and clan.activated_at == now


def test_the_audit_row_holds_ids_statuses_and_dates_and_nothing_personal(w, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    sa, token = w.sa()
    clan, owner, sub, plan = w.ready()
    assert w.activate(token, clan.clan_id).status_code == 200
    [row] = w.audit()
    assert (row["actor_id"], row["entity_type"], row["entity_id"], row["clan_id"]) == (sa.user_id, "clan", clan.clan_id, clan.clan_id)
    assert row["old_data"] == {"status": "PENDING", "subscription_status": "PENDING"}
    data = row["new_data"]
    assert set(data) == {"status", "subscription_id", "subscription_status", "plan_id", "plan_code", "owner_user_id", "starts_at", "ends_at", "request_id"}
    assert (data["status"], data["subscription_status"], data["plan_code"], data["owner_user_id"]) == ("ACTIVE", "ACTIVE", plan.code, str(owner.user_id))
    text = repr(w.repo.audit) + app_logs(caplog)
    for hidden in (*PERSONAL, owner.email, "@"):
        assert hidden not in text, hidden


def test_no_idempotency_key_is_needed_or_looked_at_and_no_key_is_written(w):
    _sa, token = w.sa()
    clan, _o, _s, _p = w.ready()
    w.tx.begin()
    r = w.client.post(f"/api/v1/admin/clans/{clan.clan_id}/activate", headers={**w._h(token), "Idempotency-Key": "ignored-key-123"})
    assert r.status_code == 200 and w.idem.rows == [] and "idempotency-replayed" not in r.headers


def test_the_lock_order_is_the_clan_then_the_subscriptions_and_the_users_row_is_never_locked(w):
    _sa, token = w.sa()
    clan, _o, _s, _p = w.ready()
    w.family.calls.clear()
    assert w.activate(token, clan.clan_id).status_code == 200
    calls = w.family.calls
    assert calls.index("idem.set_lock_timeout") < calls.index("lock_clan") < calls.index("lock_subscriptions") < calls.index("activate_clan") < calls.index("activate_subscription")
    assert "lock_user" not in calls and calls.count("lock_clan") == 1 and calls.count("lock_subscriptions") == 1


def test_a_failure_at_commit_leaves_both_rows_as_they_were(w):
    _sa, token = w.sa()
    clan, _o, sub, _p = w.ready()
    before = snapshot(clan, sub)
    w.tx.fail_commit = True
    r = w.activate(token, clan.clan_id)
    assert (r.status_code, code(r)) == (503, "DATABASE_UNAVAILABLE")
    unchanged(w, clan, sub, before)
    w.tx.fail_commit = False
    assert w.activate(token, clan.clan_id).status_code == 200  # nothing was left half done


# ------------------------------------------------------------------ the 409s


@pytest.mark.parametrize("status", ["ACTIVE", "SUSPENDED", "LOCKED", "EXPIRED", "INACTIVE"])
def test_only_a_pending_clan_is_activated_and_the_409_names_the_current_status(w, status):
    _sa, token = w.sa()
    clan, _o, sub, _p = w.ready(clan_status=status)
    if status == "ACTIVE":
        clan.activated_at = FROZEN - timedelta(days=1)
    before = snapshot(clan, sub)
    r = w.activate(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
    message = r.json()["error"]["message"]
    assert f"The clan is {status}" in message and ("activated at" in message) is (status == "ACTIVE")
    unchanged(w, clan, sub, before)


def test_a_second_activation_is_409_active_which_after_a_lost_response_means_the_first_one_worked(w):
    _sa, token = w.sa()
    clan, _o, sub, _p = w.ready()
    first = w.activate(token, clan.clan_id)
    assert first.status_code == 200
    state = snapshot(clan, sub)
    again = w.activate(token, clan.clan_id)
    assert (again.status_code, code(again)) == (409, "STATE_CONFLICT")
    assert "ACTIVE" in again.json()["error"]["message"] and first.json()["activated_at"][:19] in again.json()["error"]["message"]
    assert snapshot(clan, sub) == state and len(w.audit()) == 1  # ... and nothing was written twice


def test_a_clan_without_an_owner_is_409(w):
    _sa, token = w.sa()
    clan, owner, sub, _p = w.ready()
    w.family.owners.clear()
    before = snapshot(clan, sub)
    r = w.activate(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "no Owner" in r.json()["error"]["message"]
    unchanged(w, clan, sub, before)


def test_an_owner_whose_ownership_ended_does_not_count(w):
    _sa, token = w.sa()
    clan, owner, sub, _p = w.ready()
    w.family.owners[0].ended_at = FROZEN - timedelta(days=1)
    assert w.activate(token, clan.clan_id).status_code == 409 and clan.status == "PENDING"


@pytest.mark.parametrize("change", ["no membership", "membership INVITED", "membership revoked"])
def test_the_owner_must_be_an_active_member_of_the_clan(w, change):
    _sa, token = w.sa()
    clan, owner, sub, _p = w.ready()
    [membership] = w.family.memberships
    if change == "no membership":
        w.family.memberships.clear()
    elif change == "membership INVITED":
        membership.status = "INVITED"
    else:
        membership.revoked_at = FROZEN - timedelta(hours=1)
    before = snapshot(clan, sub)
    r = w.activate(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "active member" in r.json()["error"]["message"]
    unchanged(w, clan, sub, before)


def test_the_owner_must_still_hold_the_business_owner_role_in_this_clan(w):
    _sa, token = w.sa()
    clan, owner, sub, _p = w.ready()
    def drop_owner_grants():
        w.repo.roles[:] = [g for g in w.repo.roles if g.user_id != owner.user_id]

    drop_owner_grants()
    r = w.activate(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "Business Owner role" in r.json()["error"]["message"]
    w.repo.grant(owner, "BUSINESS_OWNER", uuid.uuid4())  # the role of ANOTHER clan does not do
    assert w.activate(token, clan.clan_id).status_code == 409
    drop_owner_grants()
    w.repo.grant(owner, "BUSINESS_OWNER", clan.clan_id, revoked=True)  # a revoked grant does not do
    assert w.activate(token, clan.clan_id).status_code == 409 and clan.status == "PENDING"


@pytest.mark.parametrize("status", ["LOCKED", "DISABLED", "SUSPENDED", "WEIRD"])
def test_an_owner_account_that_is_locked_disabled_suspended_or_unknown_blocks_the_activation(w, status):
    _sa, token = w.sa()
    clan, owner, sub, _p = w.ready()
    owner.status = status
    before = snapshot(clan, sub)
    r = w.activate(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and f"Owner account is {status}" in r.json()["error"]["message"]
    unchanged(w, clan, sub, before)


@pytest.mark.parametrize("status", ["PENDING", "ACTIVE"])
def test_the_owner_need_not_have_changed_the_password_yet(w, status):
    _sa, token = w.sa()
    clan, owner, sub, _p = w.ready(owner_status=status)
    assert w.activate(token, clan.clan_id).status_code == 200 and clan.status == "ACTIVE"


def test_the_subscription_conditions(w):
    _sa, token = w.sa()
    # none at all
    clan, _o, sub, _p = w.ready()
    w.family.subscriptions.remove(sub)
    r = w.activate(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "no PENDING subscription" in r.json()["error"]["message"]
    # only an EXPIRED one
    sub.status = "EXPIRED"
    w.family.subscriptions.append(sub)
    assert "no PENDING subscription" in w.activate(token, clan.clan_id).json()["error"]["message"]
    # one ACTIVE already
    sub.status = "ACTIVE"
    assert "already has an ACTIVE subscription" in w.activate(token, clan.clan_id).json()["error"]["message"]
    # an ACTIVE one next to a PENDING one: still refused, nothing is activated twice
    pending = w.subscription(clan, _p)
    r = w.activate(token, clan.clan_id)
    assert r.status_code == 409 and pending.status == "PENDING" and clan.status == "PENDING"
    # two PENDING ones
    sub.status = "PENDING"
    r = w.activate(token, clan.clan_id)
    assert r.status_code == 409 and "more than one PENDING" in r.json()["error"]["message"]
    assert (sub.status, pending.status, clan.status) == ("PENDING", "PENDING", "PENDING")


@pytest.mark.parametrize("plan_status", ["INACTIVE", "ARCHIVED"])
def test_a_plan_that_is_no_longer_active_is_409_and_nothing_changes(w, plan_status):
    _sa, token = w.sa()
    clan, _o, sub, plan = w.ready(plan_status=plan_status)
    before = snapshot(clan, sub)
    r = w.activate(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "plan of the subscription is no longer available" in r.json()["error"]["message"]
    unchanged(w, clan, sub, before)
    plan.status = "ACTIVE"
    assert w.activate(token, clan.clan_id).status_code == 200  # the way out of the KI-32 jam: the plan is ACTIVE again


def test_a_subscription_whose_plan_is_gone_is_409(w):
    _sa, token = w.sa()
    clan, _o, sub, plan = w.ready()
    del w.family.plans[plan.plan_id]
    assert w.activate(token, clan.clan_id).status_code == 409 and clan.status == "PENDING"


def test_no_409_carries_an_email_a_name_or_a_phone(w):
    _sa, token = w.sa()
    clan, owner, sub, _p = w.ready()
    owner.display_name = OWNER_NAME
    owner.status = "LOCKED"
    texts = [w.activate(token, clan.clan_id).text]
    owner.status = "ACTIVE"
    w.family.owners.clear()
    texts.append(w.activate(token, clan.clan_id).text)
    for text in texts:
        for hidden in (*PERSONAL, owner.email):
            assert hidden not in text


# ------------------------------------------------------------------ the road of a new Owner


def provision(w, token, clan):
    created = w.post(token, clan.clan_id)
    assert created.status_code == 201, created.text
    [owner] = w.owner_users()
    return owner, created.json()


def sign_in(w, owner, *, just_now=False):
    auth_time = datetime.now(timezone.utc) if just_now else None  # after a password change the ID token must be newer than it
    return w.client.post("/api/v1/auth/session", json={"id_token": w.provider.issue(owner.firebase_uid, auth_time=auth_time)})


def change_password(w, access, owner):
    return w.client.post("/api/v1/auth/change-password", headers={"Authorization": f"Bearer {access}"},
                         json={"new_password": "A-brand-new-pass-1", "recent_id_token": w.provider.issue(owner.firebase_uid)})


def clan_action(w, access, clan_id):
    return w.client.get(f"/api/v1/clans/{clan_id}/users", headers={"Authorization": f"Bearer {access}"})


def me(w, access):
    return w.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}).json()


@pytest.mark.parametrize("activate_first", [False, True])
def test_provision_first_login_password_change_and_the_clan_works_only_once_it_is_activated(activate_first):
    w = ActWorld()  # the real clock: /auth/session and /auth/change-password read the real time
    sa, token = w.sa()
    clan, _reg = w.clan()
    plan = w.family.add_plan("E2E-PLAN", months=12)
    sub = w.subscription(clan, plan, starts=datetime.now(timezone.utc) - timedelta(days=1))
    owner, created = provision(w, token, clan)
    assert (clan.status, owner.status) == ("PENDING", "PENDING")  # the Owner exists; the clan is still PENDING

    if activate_first:  # the SA activates BEFORE the Owner ever signs in
        done = w.activate(token, clan.clan_id)
        assert done.status_code == 200 and (clan.status, owner.status) == ("ACTIVE", "PENDING")

    first = sign_in(w, owner)  # a clan that is PENDING does not stop the sign-in
    assert first.status_code == 201 and first.json()["requires_password_change"] is True
    restricted = first.json()["access_token"]
    assert clan_action(w, restricted, clan.clan_id).status_code == 403  # a restricted session reaches nothing of the clan
    assert change_password(w, restricted, owner).status_code == 204 and owner.status == "ACTIVE"
    full = sign_in(w, owner, just_now=True)  # every session died with the change: sign in again
    assert full.status_code == 201 and full.json()["requires_password_change"] is False
    access = full.json()["access_token"]

    if not activate_first:
        membership = me(w, access)["memberships"][0]
        assert (membership["clan_status"], membership["permissions"]) == ("PENDING", [])
        denied = clan_action(w, access, clan.clan_id)
        assert (denied.status_code, code(denied)) == (403, "FORBIDDEN")  # the clan is PENDING: the Owner can do nothing in it
        assert w.activate(token, clan.clan_id).status_code == 200  # ... until the SA activates it

    membership = me(w, access)["memberships"][0]
    assert membership["clan_status"] == "ACTIVE" and "clan.users.list" in membership["permissions"]
    assert clan_action(w, access, clan.clan_id).status_code == 200  # the same session now works
    assert (sub.status, clan.status) == ("ACTIVE", "ACTIVE")


# ------------------------------------------------------------------ GET /admin/clans/{id}


def test_the_clan_is_read_without_any_personal_data(w, caplog):
    sa, token = w.sa()
    clan, _reg = w.clan()
    plan = w.family.add_plan("READ-PLAN", months=6)
    sub = w.subscription(clan, plan)
    owner, created = provision(w, token, clan)
    r = w.read(token, clan.clan_id)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert set(body) == {"clan_id", "clan_code", "status", "registration_id", "created_at", "activated_at", "subscription", "owner_user_id", "last_owner_job"}
    assert (body["clan_id"], body["clan_code"], body["status"], body["registration_id"], body["activated_at"]) == (
        str(clan.clan_id), clan.clan_code, "PENDING", str(clan.registration_id), None)
    assert body["owner_user_id"] == str(owner.user_id)
    assert body["subscription"] == {
        "subscription_id": str(sub.subscription_id), "plan_id": str(plan.plan_id), "plan_code": "READ-PLAN", "status": "PENDING",
        "starts_at": sub.starts_at.isoformat().replace("+00:00", "Z"), "ends_at": sub.ends_at.isoformat().replace("+00:00", "Z")}
    assert body["last_owner_job"] == {"job_id": created["job_id"], "status": "SUCCEEDED", "needs_cleanup": False}
    text = r.text
    for hidden in (*PERSONAL, owner.firebase_uid, clan.name, "email", "phone", "display_name", "firebase"):
        assert hidden not in text, hidden
    assert w.read(token, clan.clan_id).json() == body  # a read changes nothing


def test_a_new_clan_has_no_owner_no_job_and_maybe_no_subscription(w):
    _sa, token = w.sa()
    clan = w.family.add_clan("PENDING")
    body = w.read(token, clan.clan_id).json()
    assert (body["owner_user_id"], body["last_owner_job"], body["subscription"], body["registration_id"]) == (None, None, None, None)


def test_the_subscription_shown_is_the_active_one_then_a_pending_one_then_the_latest(w):
    _sa, token = w.sa()
    clan = w.family.add_clan("ACTIVE")
    plan = w.family.add_plan("P", months=1)
    old = w.subscription(clan, plan, status="EXPIRED", starts=FROZEN - timedelta(days=400))
    newer = w.subscription(clan, plan, status="CANCELLED", starts=FROZEN - timedelta(days=100))
    assert w.read(token, clan.clan_id).json()["subscription"]["subscription_id"] == str(newer.subscription_id)  # the latest
    pending = w.subscription(clan, plan, status="PENDING", starts=FROZEN - timedelta(days=50))
    assert w.read(token, clan.clan_id).json()["subscription"]["subscription_id"] == str(pending.subscription_id)
    active = w.subscription(clan, plan, status="ACTIVE", starts=FROZEN - timedelta(days=200))
    assert w.read(token, clan.clan_id).json()["subscription"]["subscription_id"] == str(active.subscription_id)


def test_the_latest_owner_job_is_the_newest_one(w):
    from tests.test_owner_provisioning_api import seed_job

    _sa, token = w.sa()
    clan = w.family.add_clan("PENDING")
    seed_job(w, clan.clan_id, "a@example.test", status="FAILED", created=FROZEN - timedelta(days=2))
    newest = seed_job(w, clan.clan_id, "b@example.test", status="FAILED_RETRYABLE", created=FROZEN - timedelta(hours=1))
    job = w.read(token, clan.clan_id).json()["last_owner_job"]
    assert job == {"job_id": str(newest.job_id), "status": "FAILED_RETRYABLE", "needs_cleanup": False}


def test_an_activated_clan_shows_its_dates(w):
    _sa, token = w.sa()
    clan, _o, sub, _p = w.ready()
    assert w.activate(token, clan.clan_id).status_code == 200
    body = w.read(token, clan.clan_id).json()
    assert body["status"] == "ACTIVE" and body["activated_at"].startswith("2026-10-08T09:00:00")
    assert body["subscription"]["status"] == "ACTIVE" and body["subscription"]["starts_at"].startswith("2026-10-08T09:00:00")
    assert everything_stored(w) is not None
