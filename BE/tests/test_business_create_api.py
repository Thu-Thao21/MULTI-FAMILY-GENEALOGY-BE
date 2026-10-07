"""POST /admin/business-registrations/{id}/business over HTTP (Mốc E, step E5): the real router and
the real authorization on fake repositories whose transaction (FakeTx) really rolls back.

Who may call, the conditions, the clan code, the idempotency (replay, conflict, errors not stored,
a request that dies half-way leaves nothing), the rows written, the audit, and what must never leak."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.controllers.family_management.business_admin_use_cases as use_cases
from app.controllers.family_management.registration_admin_router import router
from app.core.dates import add_months
from app.core.errors import register_exception_handlers
from app.core.idempotency import IDEMPOTENCY_TTL, compute_request_hash
from app.core.request_id import RequestIdMiddleware
from app.db.postgres import get_db
from app.dependencies.auth import get_user_access_repo
from app.dependencies.permissions import get_family_repo, get_idempotency_repo
from tests.fakes import FakeFamilyRepo, FakeIdempotencyRepo, FakeTx, FakeUserAccessRepo, make_user

PREFIX = "/api/v1/admin/business-registrations"
ENDPOINT = "POST /admin/business-registrations/{registration_id}/business"
FROZEN = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
PERSONAL = {
    "name": "Tran Thi Zed", "email": "Applicant.Zed@Example.TEST", "phone": "+84 912 345 678",
    "clan_name": "Ho Tran Zed", "origin_place": "Zed Village",
}
RESPONSE_KEYS = {"clan_id", "clan_code", "clan_status", "subscription_id", "plan_id", "subscription_status", "starts_at", "ends_at"}


class BizWorld:
    def __init__(self, *, raise_server_exceptions: bool = True, client_ip: str = "testclient") -> None:
        self.repo = FakeUserAccessRepo()
        self.family = FakeFamilyRepo(users=self.repo.users)
        self.idem = FakeIdempotencyRepo(calls=self.family.calls)  # ONE list: the order across repositories
        self.tx = FakeTx(idem=self.idem, family=self.family, users=self.repo)
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)
        register_exception_handlers(app)
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.tx
        app.dependency_overrides[get_user_access_repo] = lambda: self.repo
        app.dependency_overrides[get_family_repo] = lambda: self.family
        app.dependency_overrides[get_idempotency_repo] = lambda: self.idem
        self.client = TestClient(app, raise_server_exceptions=raise_server_exceptions, client=(client_ip, 4000))
        self.plan = self.family.add_plan("TEST-ACTIVE", price="199000.00")

    # ---- people ----
    def user(self, status="ACTIVE", **kw):
        return self.repo.add_user(make_user(status, **kw))

    def token(self, user) -> str:
        now = datetime.now(timezone.utc)
        return self.repo.seed_session(user, token=f"tok-{uuid.uuid4().hex}", created_at=now - timedelta(minutes=5),
                                      expires_at=now + timedelta(hours=8))

    def sa(self):
        user = self.user()
        self.repo.grant(user, "SYSTEM_ADMIN")
        return user, self.token(user)

    def registration(self, status="APPROVED", **kw):
        return self.family.add_registration(kw.pop("plan", self.plan), status=status, **kw)

    # ---- calls ----
    def post(self, token, registration_id, *, key="__new__", body="__none__", headers=None):
        self.tx.begin()  # a new request is a new transaction
        hdrs = {"Authorization": f"Bearer {token}"}
        if key == "__new__":
            key = f"key-{uuid.uuid4().hex}"
        if key is not None:
            hdrs["Idempotency-Key"] = key
        hdrs.update(headers or {})
        kwargs = {} if body == "__none__" else {"json": body}
        r = self.client.post(f"{PREFIX}/{registration_id}/business", headers=hdrs, **kwargs)
        r.sent_key = key
        return r

    def written(self) -> bool:
        return bool(self.family.clans or self.family.clan_profiles or self.family.subscriptions
                    or self.idem.rows or self.repo.audit)


def code(r) -> str:
    return r.json()["error"]["code"]


@pytest.fixture
def w(monkeypatch) -> BizWorld:
    monkeypatch.setattr(use_cases, "utcnow", lambda: FROZEN)
    return BizWorld()


# ------------------------------------------------------------------ who may call


def non_sa_tokens(w: BizWorld) -> dict[str, str]:
    clan = w.family.add_clan("ACTIVE")
    bo = w.user()
    w.repo.grant(bo, "BUSINESS_OWNER", clan.clan_id)
    w.family.add_owner(clan, bo)
    w.family.add_member(clan, bo)
    fa = w.user()
    w.family.add_member(clan, fa)
    w.repo.grant(fa, "FAMILY_ADMIN", clan.clan_id)
    w.family.add_fa_assignment(clan, fa, ["MEMBER_ACCOUNT_MANAGE", "AUDIT_VIEW"])
    member = w.user()
    w.family.add_member(clan, member)
    scoped_sa = w.user()
    w.repo.grant(scoped_sa, "SYSTEM_ADMIN", clan.clan_id)  # an SA grant tied to a clan is not system scope
    plain = w.user()
    return {n: w.token(u) for n, u in (("business owner", bo), ("family admin", fa), ("member", member),
                                       ("clan scoped SA grant", scoped_sa), ("account without role", plain))}


def test_an_anonymous_caller_is_401_and_a_restricted_sa_is_403_password_change_required(w):
    reg = w.registration()
    r = w.client.post(f"{PREFIX}/{reg.registration_id}/business", headers={"Idempotency-Key": "key-0123456789"})
    assert (r.status_code, code(r)) == (401, "UNAUTHENTICATED")
    sa = w.user(first_login_required=True)
    w.repo.grant(sa, "SYSTEM_ADMIN")
    r = w.post(w.token(sa), reg.registration_id)
    assert (r.status_code, code(r)) == (403, "PASSWORD_CHANGE_REQUIRED")
    assert not w.written()


def test_everyone_who_is_not_a_system_admin_gets_403_before_any_validation_or_lookup(w):
    reg = w.registration()
    tokens = non_sa_tokens(w)  # (this setup adds a clan of its own)
    state = (len(w.family.clans), len(w.family.clan_profiles), len(w.family.subscriptions), len(w.idem.rows), len(w.repo.audit))
    for who, token in tokens.items():
        for r in (
            w.post(token, reg.registration_id),
            w.post(token, reg.registration_id, key=None),  # header missing: still 403, not 422
            w.post(token, reg.registration_id, key="short", body={"bogus": 1}),
            w.post(token, "not-a-uuid"),
            w.post(token, uuid.uuid4()),  # unknown id: no 404 for them
            w.post(token, reg.registration_id, body={"clan_code": "lower"}),
        ):
            assert (r.status_code, code(r)) == (403, "FORBIDDEN"), who
    assert state == (len(w.family.clans), len(w.family.clan_profiles), len(w.family.subscriptions), len(w.idem.rows), len(w.repo.audit))
    assert "lock_registration" not in w.family.calls and "idem.insert" not in w.family.calls


# ------------------------------------------------------------------ validation


def test_the_idempotency_key_is_required_and_must_be_8_to_128_visible_characters(w):
    _sa, token = w.sa()
    reg = w.registration()
    for key in (None, "", "1234567", "x" * 129, "has space inside"):
        r = w.post(token, reg.registration_id, key=key)
        assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR"), key
        assert "Idempotency-Key" in r.json()["error"]["message"]
        if key:
            assert key not in r.text  # the value is never echoed
    assert not w.written() and "lock_registration" not in w.family.calls
    for key in ("12345678", "x" * 128, str(uuid.uuid4())):
        assert w.post(token, w.registration().registration_id, key=key).status_code == 201, key


@pytest.mark.parametrize("body", [
    {"plan_id": str(uuid.uuid4())}, {"clan_status": "ACTIVE"}, {"extra": 1}, {"clan_code": "lower-case"},
    {"clan_code": "AB"}, {"clan_code": "A" * 51}, {"clan_code": "WITH SPACE"}, {"clan_code": 5}, {"clan_code": ["A"]},
    [], "text", 5,
])
def test_a_bad_body_is_422_and_the_plan_can_never_come_from_the_request(w, body):
    _sa, token = w.sa()
    reg = w.registration()
    r = w.post(token, reg.registration_id, body=body)
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")
    assert not w.written() and "lock_registration" not in w.family.calls


@pytest.mark.parametrize("body", ["__none__", {}, None, {"clan_code": None}])
def test_no_body_an_empty_body_or_a_null_code_all_mean_generate_a_code(w, body):
    _sa, token = w.sa()
    r = w.post(token, w.registration().registration_id, body=body)
    assert r.status_code == 201 and r.json()["clan_code"].startswith("CLAN-")


def test_a_registration_id_that_is_not_a_uuid_is_422(w):
    _sa, token = w.sa()
    r = w.post(token, "not-a-uuid")
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")


# ------------------------------------------------------------------ the conditions


def test_an_unknown_registration_is_404_and_leaves_no_key_behind(w):
    _sa, token = w.sa()
    r = w.post(token, uuid.uuid4())
    assert (r.status_code, code(r)) == (404, "NOT_FOUND") and not w.written()


@pytest.mark.parametrize("status", ["DRAFT", "PENDING", "NEED_SUPPLEMENT", "REJECTED", "CANCELLED"])
def test_only_an_approved_registration_gets_a_business_and_the_409_names_the_status(w, status):
    _sa, token = w.sa()
    reg = w.registration(status=status, **{"name": PERSONAL["name"], "email": PERSONAL["email"]})
    r = w.post(token, reg.registration_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
    message = r.json()["error"]["message"]
    assert status in message and "APPROVED" in message
    for secret in (PERSONAL["name"], PERSONAL["email"]):
        assert secret not in message
    assert not w.written()
    assert "get_plan_by_id" not in w.family.calls and "create_clan" not in w.family.calls


def test_a_registration_that_already_has_a_business_is_409_duplicate_resource(w):
    _sa, token = w.sa()
    reg = w.registration()
    assert w.post(token, reg.registration_id).status_code == 201
    before = (len(w.family.clans), len(w.family.subscriptions), len(w.repo.audit), len(w.idem.rows))
    r = w.post(token, reg.registration_id)  # a NEW key: this is another request, not a replay
    assert (r.status_code, code(r)) == (409, "DUPLICATE_RESOURCE")
    assert (len(w.family.clans), len(w.family.subscriptions), len(w.repo.audit), len(w.idem.rows)) == before


@pytest.mark.parametrize("plan_status", ["INACTIVE", "RETIRED"])
def test_the_plan_must_still_be_active_even_though_the_approval_checked_it(w, plan_status):
    _sa, token = w.sa()
    reg = w.registration(plan=w.family.add_plan(f"TEST-{plan_status}", status=plan_status))
    r = w.post(token, reg.registration_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "plan" in r.json()["error"]["message"].lower()
    assert not w.written() and "create_clan" not in w.family.calls


def test_a_plan_that_no_longer_exists_is_409_too(w):
    _sa, token = w.sa()
    reg = w.registration()
    del w.family.plans[reg.requested_plan_id]
    r = w.post(token, reg.registration_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and not w.written()


def test_the_plan_is_the_one_of_the_registration_read_from_the_database(w):
    _sa, token = w.sa()
    other = w.family.add_plan("TEST-OTHER", months=1)
    reg = w.registration(plan=w.family.add_plan("TEST-CHOSEN", months=6))
    body = w.post(token, reg.registration_id).json()
    assert body["plan_id"] == str(reg.requested_plan_id) != str(other.plan_id)
    [sub] = w.family.subscriptions
    assert sub.plan_id == reg.requested_plan_id and sub.ends_at == add_months(FROZEN, 6)


# ------------------------------------------------------------------ the clan code


def test_a_clan_code_given_by_the_sa_is_used_as_it_is(w):
    _sa, token = w.sa()
    r = w.post(token, w.registration().registration_id, body={"clan_code": "HO-TRAN_01"})
    assert r.status_code == 201 and r.json()["clan_code"] == "HO-TRAN_01"
    assert "get_clan_by_code" in w.family.calls


def test_a_clan_code_that_is_taken_is_409_duplicate_resource_and_writes_nothing(w):
    _sa, token = w.sa()
    assert w.post(token, w.registration().registration_id, body={"clan_code": "HO-TRAN"}).status_code == 201
    before = (len(w.family.clans), len(w.idem.rows), len(w.repo.audit))
    r = w.post(token, w.registration().registration_id, body={"clan_code": "HO-TRAN"})
    assert (r.status_code, code(r)) == (409, "DUPLICATE_RESOURCE")
    assert (len(w.family.clans), len(w.idem.rows), len(w.repo.audit)) == before


def test_a_generated_code_is_clan_dash_plus_eight_safe_characters_and_each_clan_gets_its_own(w):
    _sa, token = w.sa()
    codes = {w.post(token, w.registration().registration_id).json()["clan_code"] for _ in range(5)}
    assert len(codes) == 5
    import re

    assert all(re.fullmatch(r"CLAN-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{8}", c) for c in codes)


def test_a_generated_code_that_collides_is_drawn_again(w, monkeypatch):
    _sa, token = w.sa()
    taken = w.family.add_clan("ACTIVE")
    taken.clan_code = "CLAN-AAAAAAAA"
    draws = iter(["CLAN-AAAAAAAA", "CLAN-AAAAAAAA", "CLAN-BBBBBBBB"])
    monkeypatch.setattr(use_cases, "generate_clan_code", lambda: next(draws))
    r = w.post(token, w.registration().registration_id)
    assert r.status_code == 201 and r.json()["clan_code"] == "CLAN-BBBBBBBB"
    assert w.family.calls.count("create_clan") == 3  # two collisions, then success
    assert "get_clan_by_code" not in w.family.calls  # a generated code is not pre-checked: the index decides


def test_three_collisions_in_a_row_are_a_500_and_write_nothing(w, monkeypatch):
    w = BizWorld(raise_server_exceptions=False)
    monkeypatch.setattr(use_cases, "utcnow", lambda: FROZEN)
    _sa, token = w.sa()
    taken = w.family.add_clan("ACTIVE")
    taken.clan_code = "CLAN-AAAAAAAA"
    monkeypatch.setattr(use_cases, "generate_clan_code", lambda: "CLAN-AAAAAAAA")
    r = w.post(token, w.registration().registration_id)
    assert (r.status_code, code(r)) == (500, "INTERNAL_ERROR")
    assert w.family.calls.count("create_clan") == 3  # three attempts in all, never more
    assert not w.family.clan_profiles and not w.idem.rows and not w.repo.audit


def test_the_unique_indexes_are_the_last_line_of_defence_and_give_the_same_409(w):
    _sa, token = w.sa()
    # the pre-check says "free", the index says "taken" (a lost race)
    w.family.create_clan_errors = ["clans_clan_code_key"]
    r = w.post(token, w.registration().registration_id, body={"clan_code": "RACE-LOST"})
    assert (r.status_code, code(r)) == (409, "DUPLICATE_RESOURCE") and "code" in r.json()["error"]["message"].lower()
    w.family.create_clan_errors = ["clans_registration_id_key"]
    for body in ("__none__", {"clan_code": "RACE-LOST-2"}):
        r = w.post(token, w.registration().registration_id, body=body)
        assert (r.status_code, code(r)) == (409, "DUPLICATE_RESOURCE") and "Business" in r.json()["error"]["message"]
        w.family.create_clan_errors = ["clans_registration_id_key"]
    assert not w.written()


@pytest.mark.parametrize("name", ["clans_status_check", "clans_created_by_fkey", "some_other_index", None])
def test_any_other_integrity_error_is_a_bug_and_a_500_never_a_409_and_is_not_retried(w, name):
    w = BizWorld(raise_server_exceptions=False)
    _sa, token = w.sa()
    w.family.create_clan_errors = [name]
    r = w.post(token, w.registration().registration_id)
    assert (r.status_code, code(r)) == (500, "INTERNAL_ERROR")
    assert w.family.calls.count("create_clan") == 1  # only the code collision is retried
    assert not w.written()


# ------------------------------------------------------------------ success: what is written


def test_a_success_is_201_with_exactly_the_contract_fields_and_no_store(w):
    sa, token = w.sa()
    reg = w.registration()
    r = w.post(token, reg.registration_id)
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    assert "idempotency-replayed" not in r.headers
    body = r.json()
    assert set(body) == RESPONSE_KEYS
    assert (body["clan_status"], body["subscription_status"]) == ("PENDING", "PENDING")
    assert body["plan_id"] == str(reg.requested_plan_id)
    assert body["starts_at"] == "2026-10-07T12:00:00Z" and body["ends_at"] == "2027-10-07T12:00:00Z"
    for hidden in (PERSONAL["clan_name"], reg.representative_email, reg.representative_name, str(reg.registration_id)):
        assert hidden not in r.text


def test_the_clan_the_profile_and_the_subscription_are_written_together_in_pending(w):
    sa, token = w.sa()
    reg = w.registration(**{"clan_name": PERSONAL["clan_name"], "origin_place": PERSONAL["origin_place"]})
    body = w.post(token, reg.registration_id).json()
    [clan] = w.family.clans.values()
    assert (str(clan.clan_id), clan.clan_code, clan.status) == (body["clan_id"], body["clan_code"], "PENDING")
    assert (clan.registration_id, clan.name, clan.created_by) == (reg.registration_id, PERSONAL["clan_name"], sa.user_id)
    assert clan.activated_at is None
    [profile] = w.family.clan_profiles
    assert (profile.clan_id, profile.origin_place) == (clan.clan_id, PERSONAL["origin_place"])
    [sub] = w.family.subscriptions
    assert (str(sub.subscription_id), sub.clan_id, sub.plan_id, sub.status, sub.auto_renew) == (
        body["subscription_id"], clan.clan_id, reg.requested_plan_id, "PENDING", False)
    assert (sub.starts_at, sub.ends_at) == (FROZEN, add_months(FROZEN, 12))
    assert w.tx.events == ["commit"]  # one transaction, one commit


def test_a_registration_without_a_place_of_origin_gets_an_empty_profile_value(w):
    _sa, token = w.sa()
    reg = w.registration(origin_place=None)
    assert w.post(token, reg.registration_id).status_code == 201
    assert w.family.clan_profiles[0].origin_place is None


@pytest.mark.parametrize("months, now, ends", [
    (1, datetime(2026, 1, 31, 9, 0, tzinfo=timezone.utc), datetime(2026, 2, 28, 9, 0, tzinfo=timezone.utc)),
    (1, datetime(2028, 1, 31, 9, 0, tzinfo=timezone.utc), datetime(2028, 2, 29, 9, 0, tzinfo=timezone.utc)),
    (12, datetime(2028, 2, 29, 9, 0, tzinfo=timezone.utc), datetime(2029, 2, 28, 9, 0, tzinfo=timezone.utc)),
    (3, datetime(2026, 11, 15, 9, 0, tzinfo=timezone.utc), datetime(2027, 2, 15, 9, 0, tzinfo=timezone.utc)),
])
def test_the_subscription_dates_are_provisional_and_use_calendar_months(w, monkeypatch, months, now, ends):
    monkeypatch.setattr(use_cases, "utcnow", lambda: now)
    _sa, token = w.sa()
    reg = w.registration(plan=w.family.add_plan("TEST-M", months=months))
    assert w.post(token, reg.registration_id).status_code == 201
    [sub] = w.family.subscriptions
    assert (sub.starts_at, sub.ends_at) == (now, ends) and sub.ends_at > sub.starts_at


def test_the_registration_itself_does_not_change_and_no_history_row_is_written(w):
    _sa, token = w.sa()
    reviewer = uuid.uuid4()
    reg = w.registration(reviewed_by=reviewer, reviewed_at=FROZEN)
    snapshot = (reg.status, reg.reviewed_by, reg.reviewed_at, reg.rejection_reason, reg.updated_at)
    assert w.post(token, reg.registration_id).status_code == 201
    assert snapshot == (reg.status, reg.reviewed_by, reg.reviewed_at, reg.rejection_reason, reg.updated_at)
    assert reg.status == "APPROVED" and w.family.registration_history == []
    assert "add_registration_status_history" not in w.family.calls and "apply_registration_review" not in w.family.calls


def test_no_owner_no_membership_no_role_is_created(w):
    sa, token = w.sa()
    roles_before = len(w.repo.roles)
    assert w.post(token, w.registration().registration_id).status_code == 201
    assert w.family.owners == [] and w.family.memberships == [] and len(w.repo.roles) == roles_before


def test_the_audit_row_holds_ids_the_plan_code_statuses_and_the_request_id_only(w):
    sa, token = w.sa()
    reg = w.registration(**{"name": PERSONAL["name"], "email": PERSONAL["email"], "phone": PERSONAL["phone"],
                            "clan_name": PERSONAL["clan_name"], "origin_place": PERSONAL["origin_place"]})
    r = w.post(token, reg.registration_id, body={"clan_code": "HO-TRAN-ZED"})
    [audit] = w.repo.audit
    [clan] = w.family.clans.values()
    [sub] = w.family.subscriptions
    assert (audit["actor_id"], audit["action"], audit["entity_type"], audit["entity_id"], audit["clan_id"]) == (
        sa.user_id, "business.create", "clan", clan.clan_id, clan.clan_id)
    assert audit["old_data"] is None and audit.get("reason") is None
    assert set(audit["new_data"]) == {"registration_id", "plan_id", "plan_code", "subscription_id", "clan_status", "subscription_status", "request_id"}
    assert audit["new_data"] == {
        "registration_id": str(reg.registration_id), "plan_id": str(reg.requested_plan_id), "plan_code": "TEST-ACTIVE",
        "subscription_id": str(sub.subscription_id), "clan_status": "PENDING", "subscription_status": "PENDING",
        "request_id": r.headers["X-Request-ID"],
    }
    dump = repr(audit)
    for secret in (*PERSONAL.values(), "HO-TRAN-ZED", "@"):
        assert secret not in dump, secret
    assert audit["occurred_at"] == FROZEN


def test_the_audit_records_the_connecting_address_not_a_forwarded_one(monkeypatch):
    monkeypatch.setattr(use_cases, "utcnow", lambda: FROZEN)
    w = BizWorld(client_ip="203.0.113.9")
    _sa, token = w.sa()
    r = w.post(token, w.registration().registration_id, headers={"X-Forwarded-For": "198.51.100.1"})
    assert r.status_code == 201 and w.repo.audit[0]["ip_address"] == "203.0.113.9"


def test_nothing_about_the_applicant_the_key_or_the_code_reaches_a_log(w, caplog):
    caplog.set_level(logging.DEBUG)
    _sa, token = w.sa()
    reg = w.registration(**{"email": PERSONAL["email"], "name": PERSONAL["name"], "clan_name": PERSONAL["clan_name"]})
    r = w.post(token, reg.registration_id, key="my-very-own-key-12345", body={"clan_code": "HO-TRAN-ZED"})
    logged = " | ".join(x.getMessage() for x in caplog.records if not x.name.startswith(("httpx", "httpcore")))
    for secret in (PERSONAL["email"], PERSONAL["name"], PERSONAL["clan_name"], "my-very-own-key-12345", "HO-TRAN-ZED"):
        assert secret not in logged, secret
    assert r.headers["X-Request-ID"] in logged


# ------------------------------------------------------------------ the idempotency row


def test_the_key_row_is_completed_in_the_same_transaction_with_the_response_that_was_sent(w):
    sa, token = w.sa()
    reg = w.registration()
    r = w.post(token, reg.registration_id, key="key-for-the-row-1")
    [row] = w.idem.rows
    expected_hash = compute_request_hash(method="POST", endpoint=ENDPOINT, path_params={"registration_id": reg.registration_id}, body={})
    assert (row.actor_id, row.endpoint, row.idempotency_key, row.request_hash) == (sa.user_id, ENDPOINT, "key-for-the-row-1", expected_hash)
    assert (row.status, row.response_status, row.response_body) == ("COMPLETED", 201, r.json())
    assert (row.resource_type, str(row.resource_id)) == ("clan", r.json()["clan_id"])
    assert row.expires_at - row.created_at == IDEMPOTENCY_TTL and row.created_at == FROZEN
    assert w.tx.events == ["commit"]  # the key was never committed on its own


def test_the_stored_response_holds_no_secret_and_no_applicant_data(w):
    _sa, token = w.sa()
    reg = w.registration(**{"name": PERSONAL["name"], "email": PERSONAL["email"], "clan_name": PERSONAL["clan_name"]})
    w.post(token, reg.registration_id)
    stored = repr(w.idem.rows[0].response_body)
    for secret in (PERSONAL["name"], PERSONAL["email"], PERSONAL["clan_name"], "password", "token"):
        assert secret.lower() not in stored.lower(), secret


def test_the_same_key_and_the_same_request_replays_the_first_response_and_writes_nothing(w):
    _sa, token = w.sa()
    reg = w.registration()
    first = w.post(token, reg.registration_id, key="replay-key-0001", body={"clan_code": "HO-REPLAY"})
    w.family.calls.clear()
    tx_events = list(w.tx.events)
    again = w.post(token, reg.registration_id, key="replay-key-0001", body={"clan_code": "HO-REPLAY"})
    assert again.status_code == 201 and again.json() == first.json()
    assert again.headers["idempotency-replayed"] == "true" and again.headers["cache-control"] == "no-store"
    assert (len(w.family.clans), len(w.family.clan_profiles), len(w.family.subscriptions), len(w.repo.audit), len(w.idem.rows)) == (1, 1, 1, 1, 1)
    assert w.tx.events == tx_events  # no second commit
    for call in ("lock_registration", "create_clan", "get_plan_by_id", "create_subscription"):
        assert call not in w.family.calls, call  # the work does not run again


def test_absent_empty_and_null_bodies_are_the_same_request_for_the_replay(w):
    _sa, token = w.sa()
    reg = w.registration()
    first = w.post(token, reg.registration_id, key="same-request-key", body={"clan_code": None})
    for body in ("__none__", {}, None):
        again = w.post(token, reg.registration_id, key="same-request-key", body=body)
        assert again.status_code == 201 and again.json() == first.json() and again.headers["idempotency-replayed"] == "true"
    assert len(w.family.clans) == 1


def test_a_replay_does_not_look_at_the_state_of_the_world_again(w):
    """The registration or the plan changed afterwards: the first answer is still the answer."""
    _sa, token = w.sa()
    reg = w.registration()
    first = w.post(token, reg.registration_id, key="state-changed-key")
    reg.status = "CANCELLED"
    w.family.plans[reg.requested_plan_id].status = "RETIRED"
    again = w.post(token, reg.registration_id, key="state-changed-key")
    assert again.status_code == 201 and again.json() == first.json()


def test_the_same_key_with_a_different_request_is_409_idempotency_key_conflict(w):
    _sa, token = w.sa()
    reg, other = w.registration(), w.registration()
    first = w.post(token, reg.registration_id, key="shared-key-0001", body={"clan_code": "FIRST-CODE"})
    snapshot = (dict(w.family.clans), list(w.family.subscriptions), list(w.repo.audit), [vars(r).copy() for r in w.idem.rows])
    for r in (
        w.post(token, reg.registration_id, key="shared-key-0001", body={"clan_code": "OTHER-CODE"}),
        w.post(token, reg.registration_id, key="shared-key-0001"),  # no code now
        w.post(token, other.registration_id, key="shared-key-0001", body={"clan_code": "FIRST-CODE"}),  # another registration
    ):
        assert (r.status_code, code(r)) == (409, "IDEMPOTENCY_KEY_CONFLICT")
    assert snapshot == (dict(w.family.clans), list(w.family.subscriptions), list(w.repo.audit), [vars(r).copy() for r in w.idem.rows])
    assert w.idem.rows[0].response_body == first.json()


def test_a_key_belongs_to_one_caller_another_sa_with_the_same_key_is_not_a_replay(w):
    _sa, token = w.sa()
    _sa2, token2 = w.sa()
    reg, other = w.registration(), w.registration()
    first = w.post(token, reg.registration_id, key="common-key-0001")
    again = w.post(token2, reg.registration_id, key="common-key-0001")  # same key, same request, other caller
    assert (again.status_code, code(again)) == (409, "DUPLICATE_RESOURCE")  # evaluated for real: a Business exists
    third = w.post(token2, other.registration_id, key="common-key-0001")
    assert third.status_code == 201 and third.json()["clan_id"] != first.json()["clan_id"]
    assert len(w.idem.rows) == 2


def test_a_different_key_for_the_same_registration_is_a_new_request_and_its_key_is_not_kept(w):
    _sa, token = w.sa()
    reg = w.registration()
    assert w.post(token, reg.registration_id, key="winner-key-0001").status_code == 201
    loser = w.post(token, reg.registration_id, key="loser-key-0001")
    assert (loser.status_code, code(loser)) == (409, "DUPLICATE_RESOURCE")
    assert [r.idempotency_key for r in w.idem.rows] == ["winner-key-0001"]
    again = w.post(token, reg.registration_id, key="loser-key-0001")  # still a 409, never a replay of anything
    assert (again.status_code, code(again)) == (409, "DUPLICATE_RESOURCE") and "idempotency-replayed" not in again.headers


def test_an_error_is_not_stored_so_a_retry_checks_the_conditions_again(w):
    _sa, token = w.sa()
    reg = w.registration(status="PENDING")
    first = w.post(token, reg.registration_id, key="retry-after-409-1")
    assert (first.status_code, code(first)) == (409, "STATE_CONFLICT") and w.idem.rows == []
    reg.status = "APPROVED"  # the registration is approved meanwhile
    again = w.post(token, reg.registration_id, key="retry-after-409-1")
    assert again.status_code == 201 and "idempotency-replayed" not in again.headers


def test_a_request_that_dies_half_way_leaves_nothing_behind_and_the_key_is_free(monkeypatch):
    monkeypatch.setattr(use_cases, "utcnow", lambda: FROZEN)
    w = BizWorld(raise_server_exceptions=False)
    _sa, token = w.sa()
    reg = w.registration()
    original = w.family.create_subscription

    async def dies(**kw):
        raise RuntimeError("the process died here")

    w.family.create_subscription = dies
    r = w.post(token, reg.registration_id, key="dies-half-way-001")
    assert (r.status_code, code(r)) == (500, "INTERNAL_ERROR")
    # the clan and the profile were written before the failure: all of it is rolled back, key included
    assert not w.written() and w.tx.events == ["rollback"]
    w.family.create_subscription = original
    ok = w.post(token, reg.registration_id, key="dies-half-way-001")  # the SAME key works now
    assert ok.status_code == 201 and "idempotency-replayed" not in ok.headers
    assert len(w.family.clans) == 1 and len(w.idem.rows) == 1


def test_a_failed_commit_leaves_nothing_behind_either(monkeypatch):
    monkeypatch.setattr(use_cases, "utcnow", lambda: FROZEN)
    w = BizWorld(raise_server_exceptions=False)
    _sa, token = w.sa()
    reg = w.registration()
    w.tx.fail_commit = True
    r = w.post(token, reg.registration_id, key="commit-fails-0001")
    assert (r.status_code, code(r)) == (503, "DATABASE_UNAVAILABLE") and not w.written()
    w.tx.fail_commit = False
    assert w.post(token, reg.registration_id, key="commit-fails-0001").status_code == 201


def test_an_expired_key_is_reused_in_place_for_a_new_request(w):
    sa, token = w.sa()
    reg = w.registration()
    stale = w.post(token, reg.registration_id, key="old-key-00000001", body={"clan_code": "OLD-CODE"})
    assert stale.status_code == 201
    old_row = w.idem.rows[0]
    old_row.expires_at = FROZEN - timedelta(seconds=1)  # 7 days later
    for clan in list(w.family.clans.values()):
        del w.family.clans[clan.clan_id]  # (the old business is gone, to make the point about the key only)
    r = w.post(token, reg.registration_id, key="old-key-00000001", body={"clan_code": "NEW-CODE"})
    assert r.status_code == 201 and r.json()["clan_code"] == "NEW-CODE" and "idempotency-replayed" not in r.headers
    assert len(w.idem.rows) == 1 and w.idem.rows[0] is not None
    assert w.idem.rows[0].response_body["clan_code"] == "NEW-CODE" and w.idem.rows[0].expires_at == FROZEN + IDEMPOTENCY_TTL
    assert "idem.reset" in w.idem.calls


# ------------------------------------------------------------------ locks, order, and a stuck lock


def test_the_order_of_work_is_idempotency_then_registration_then_the_clan_and_the_rest(w):
    _sa, token = w.sa()
    reg = w.registration()
    w.family.calls.clear()
    assert w.post(token, reg.registration_id).status_code == 201
    calls = w.family.calls
    expected = ["idem.set_lock_timeout", "idem.insert", "lock_registration", "get_clan_by_registration_id",
                "get_plan_by_id", "create_clan", "create_clan_profile", "create_subscription", "idem.complete"]
    assert [c for c in calls if c in expected] == expected
    assert calls.count("lock_registration") == 1 and calls.index("idem.insert") < calls.index("lock_registration")
    assert "lock_user" not in w.repo.calls and "lock_user" not in calls  # never FOR UPDATE on users
    assert w.tx.events == ["commit"]


@pytest.mark.parametrize("where", ["lock_registration", "idem.insert"])
def test_a_lock_that_stays_taken_too_long_is_409_with_retry_after_and_writes_nothing(w, where):
    _sa, token = w.sa()
    reg = w.registration()
    if where == "lock_registration":
        w.family.lock_wait_error = True
    else:
        w.idem.wait_error = True
    r = w.post(token, reg.registration_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and r.headers["retry-after"] == "1"
    assert not w.written() and w.tx.events == ["rollback"]


# ------------------------------------------------------------------ real app: no rate limit, CORS


def test_the_endpoint_is_not_rate_limited_and_a_browser_can_read_the_replay_marker():
    from app.main import app as real_app

    w = BizWorld()
    _sa, token = w.sa()
    reg = w.registration()
    real_app.dependency_overrides.update({
        get_db: lambda: w.tx, get_user_access_repo: lambda: w.repo,
        get_family_repo: lambda: w.family, get_idempotency_repo: lambda: w.idem})
    try:
        assert real_app.state.rate_limiters.enabled is True
        client = TestClient(real_app, client=("203.0.113.78", 4000))
        origin = "http://localhost:5173"
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "real-app-key-0001", "Origin": origin}
        w.tx.begin()
        first = client.post(f"{PREFIX}/{reg.registration_id}/business", headers=headers)
        assert first.status_code == 201
        w.tx.begin()
        replay = client.post(f"{PREFIX}/{reg.registration_id}/business", headers=headers)
        assert replay.status_code == 201 and replay.headers["Idempotency-Replayed"] == "true"
        exposed = replay.headers["access-control-expose-headers"].lower()
        assert "idempotency-replayed" in exposed and "retry-after" in exposed and "x-request-id" in exposed
        preflight = client.options(f"{PREFIX}/{reg.registration_id}/business", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key"})
        assert preflight.status_code == 200 and "idempotency-key" in preflight.headers["access-control-allow-headers"].lower()
        for _ in range(40):  # far past the Guest threshold of 5 per hour
            w.tx.begin()
            r = client.post(f"{PREFIX}/{uuid.uuid4()}/business", headers={**headers, "Idempotency-Key": f"k-{uuid.uuid4().hex}"})
            assert r.status_code == 404
    finally:
        for dep in (get_db, get_user_access_repo, get_family_repo, get_idempotency_repo):
            real_app.dependency_overrides.pop(dep, None)
