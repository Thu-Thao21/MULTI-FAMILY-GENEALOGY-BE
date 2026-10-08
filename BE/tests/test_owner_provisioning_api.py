"""POST /admin/clans/{id}/owner and GET /admin/provisioning-jobs/{id} over HTTP (Mốc E6a): the real
routers and the real authorization on fake repositories, a fake Firebase (never the real one) with
fault injection, and a unit of work that really rolls back.

Who may call, the checks, the rows written, the job's states, every failure and its compensation, the
idempotency (replay, in progress, conflict), fencing, and above all: the temporary password exists only
in the one response."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError

import app.controllers.family_management.owner_provisioning_use_cases as use_cases
from app.controllers.auth_access.router import router as auth_router
from app.controllers.family_management.owner_admin_router import router as owner_router
from app.core.config import settings
from app.core.email_sender import EmailDeliveryResult
from app.core.errors import register_exception_handlers
from app.core.firebase import (
    PasswordRejected,
    ProviderEmailTaken,
    ProviderInvalidUser,
    ProviderUnavailable,
    get_identity_provider,
)
from app.core.email_sender import get_email_sender
from app.core.request_id import RequestIdMiddleware
from app.db.postgres import get_db
from app.dependencies.auth import get_user_access_repo
from app.dependencies.permissions import (
    get_family_repo,
    get_idempotency_repo,
    get_provisioning_repo,
)
from tests.fakes import (
    After,
    FakeFamilyRepo,
    FakeIdempotencyRepo,
    FakeIdentityProvider,
    FakeUserAccessRepo,
    _DbError,
    make_user,
)
from tests.fakes_owner import FakeProvisioningRepo, OwnerTx

FROZEN = datetime(2026, 10, 8, 9, 0, 0, tzinfo=timezone.utc)
KNOWN = "Kq7Wm2Xp9Tr4Vz8N"  # the password the tests make the generator return, to look for it everywhere
OWNER_EMAIL = "Owner.Mixed@Example.TEST"
OWNER_NAME = "Tran Thi Owner"
OWNER_PHONE = "+84 912 345 678"
CLAN_NAME = "Ho Owner Clan"


class Crash(BaseException):
    """A process that dies: nothing catches it (not even the use case's rollback guards re-raise it
    as anything else), so the committed state is whatever the last commit left."""


class RecordingSender:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result or EmailDeliveryResult(status=None), error, []

    async def send_owner_temporary_password(self, *, to_email, display_name, temporary_password, expires_at):
        self.calls.append((to_email, display_name, temporary_password, expires_at))
        if self.error is not None:
            raise self.error
        return self.result


class OwnerWorld:
    def __init__(self, *, raise_server_exceptions: bool = True, client_ip: str = "testclient") -> None:
        self.repo = FakeUserAccessRepo()
        self.family = FakeFamilyRepo(users=self.repo.users)
        self.idem = FakeIdempotencyRepo(calls=self.family.calls)  # ONE call list: the order across repositories
        self.jobs = FakeProvisioningRepo(calls=self.family.calls)
        self.tx = OwnerTx(idem=self.idem, family=self.family, users=self.repo, jobs=self.jobs)
        self.provider = FakeIdentityProvider()
        self.provider.probe = self.tx.uncommitted
        self.sender = RecordingSender()
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)
        register_exception_handlers(app)
        app.include_router(owner_router, prefix="/api/v1")
        app.include_router(auth_router, prefix="/api/v1")
        app.dependency_overrides.update({
            get_db: lambda: self.tx,
            get_user_access_repo: lambda: self.repo,
            get_family_repo: lambda: self.family,
            get_idempotency_repo: lambda: self.idem,
            get_provisioning_repo: lambda: self.jobs,
            get_identity_provider: lambda: self.provider,
            get_email_sender: lambda: self.sender,
        })
        self.client = TestClient(app, raise_server_exceptions=raise_server_exceptions, client=(client_ip, 4000))

    # ---- people and data ----
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

    def clan(self, status="PENDING", *, registration=True, **kw):
        clan = self.family.add_clan(status)
        reg = None
        if registration:
            plan = self.family.add_plan(f"PLAN-{uuid.uuid4().hex[:6]}")
            reg = self.family.add_registration(
                plan, status="APPROVED", name=kw.get("name", OWNER_NAME), email=kw.get("email", OWNER_EMAIL),
                phone=kw.get("phone", OWNER_PHONE), clan_name=CLAN_NAME)
            clan.registration_id, clan.name = reg.registration_id, reg.clan_name
        return clan, reg

    # ---- calls ----
    def post(self, token, clan_id, *, key="__new__", body="__none__", headers=None):
        self.tx.begin()  # a new request is a new transaction
        hdrs = {"Authorization": f"Bearer {token}"}
        if key == "__new__":
            key = f"key-{uuid.uuid4().hex}"
        if key is not None:
            hdrs["Idempotency-Key"] = key
        hdrs.update(headers or {})
        kwargs = {} if body == "__none__" else {"json": body}
        r = self.client.post(f"/api/v1/admin/clans/{clan_id}/owner", headers=hdrs, **kwargs)
        r.sent_key = key
        return r

    def get_job(self, token, job_id):
        return self.client.get(f"/api/v1/admin/provisioning-jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})

    # ---- inspection ----
    def job(self):
        [job] = self.jobs.jobs.values()
        return job

    def owner_users(self):
        return [u for u in self.repo.users.values() if u.email.lower() == OWNER_EMAIL.lower()]

    def snapshot(self) -> tuple:
        return (len(self.jobs.jobs), len(self.idem.rows), len(self.repo.audit), len(self.provider.provider_calls),
                len(self.repo.users), len(self.family.owners), len(self.family.memberships), len(self.repo.roles))

    def nothing_written(self) -> bool:
        return not (self.jobs.jobs or self.idem.rows or self.repo.audit or self.provider.provider_calls
                    or self.owner_users() or self.family.owners)


def code(r) -> str:
    return r.json()["error"]["code"]


@pytest.fixture
def w(monkeypatch) -> OwnerWorld:
    monkeypatch.setattr(use_cases, "utcnow", lambda: FROZEN)
    monkeypatch.setattr(use_cases, "_default_password", lambda: KNOWN)
    return OwnerWorld()


def dump(obj) -> str:
    return repr({k: v for k, v in vars(obj).items() if not k.startswith("_")})


def everything_stored(w: OwnerWorld) -> str:
    """Every row any fake repository holds, as text (the Firebase fake and the sender are test doubles)."""
    parts = [dump(x) for x in (*w.repo.users.values(), *w.repo.creds.values(), *w.jobs.jobs.values(),
                               *w.idem.rows, *w.family.clans.values(), *w.family.memberships, *w.family.owners)]
    parts += [repr(a) for a in w.repo.audit] + [repr(r) for r in w.repo.roles]
    parts += [repr(u) for u in w.provider.provider_users.values()] + [repr(w.provider.password_changes)]
    parts += [repr(w.provider.password_shapes), repr(w.tx.events), repr(w.family.calls)]
    return "\n".join(parts)


def app_logs(caplog) -> str:
    return " | ".join(r.getMessage() for r in caplog.records if not r.name.startswith(("httpx", "httpcore")))


# ------------------------------------------------------------------ who may call


def non_sa_tokens(w: OwnerWorld) -> dict[str, str]:
    clan = w.family.add_clan("ACTIVE")
    bo = w.user()
    w.repo.grant(bo, "BUSINESS_OWNER", clan.clan_id)
    w.family.add_owner(clan, bo)
    w.family.add_member(clan, bo)
    fa = w.user()
    w.family.add_member(clan, fa)
    w.repo.grant(fa, "FAMILY_ADMIN", clan.clan_id)
    w.family.add_fa_assignment(clan, fa, ["MEMBER_ACCOUNT_MANAGE"])
    member = w.user()
    w.family.add_member(clan, member)
    scoped_sa = w.user()
    w.repo.grant(scoped_sa, "SYSTEM_ADMIN", clan.clan_id)
    plain = w.user()
    return {n: w.token(u) for n, u in (("business owner", bo), ("family admin", fa), ("member", member),
                                       ("clan scoped SA grant", scoped_sa), ("account without role", plain))}


def test_an_anonymous_caller_is_401_and_a_restricted_sa_is_403_password_change_required(w):
    clan, _ = w.clan()
    r = w.client.post(f"/api/v1/admin/clans/{clan.clan_id}/owner", headers={"Idempotency-Key": "key-0123456789"})
    assert (r.status_code, code(r)) == (401, "UNAUTHENTICATED")
    sa = w.user(first_login_required=True)
    w.repo.grant(sa, "SYSTEM_ADMIN")
    r = w.post(w.token(sa), clan.clan_id)
    assert (r.status_code, code(r)) == (403, "PASSWORD_CHANGE_REQUIRED")
    assert w.nothing_written()


def test_everyone_who_is_not_a_system_admin_gets_403_before_validation_lookup_or_firebase(w):
    clan, _ = w.clan()
    tokens = non_sa_tokens(w)
    before = w.snapshot()
    for who, token in tokens.items():
        for r in (
            w.post(token, clan.clan_id),
            w.post(token, clan.clan_id, key=None),
            w.post(token, clan.clan_id, key="short", body={"bogus": 1}),
            w.post(token, "not-a-uuid"),
            w.post(token, uuid.uuid4()),
            w.get_job(token, uuid.uuid4()),
            w.get_job(token, "not-a-uuid"),
        ):
            assert (r.status_code, code(r)) == (403, "FORBIDDEN"), who
    assert w.snapshot() == before and w.provider.provider_calls == []


# ------------------------------------------------------------------ validation


def test_header_body_and_path_are_validated(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    for key in (None, "", "1234567", "x" * 129, "has space inside"):
        r = w.post(token, clan.clan_id, key=key)
        assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR"), key
    for body in ({"extra": 1}, {"email": "not-an-email"}, {"email": "a\x00b@example.test"}, {"display_name": "bad\x07name"},
                 {"phone": "abc"}, {"temporary_password": "x"}, [], "text"):
        r = w.post(token, clan.clan_id, body=body)
        assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR"), body
    assert w.post(token, "not-a-uuid").status_code == 422
    assert w.nothing_written()


def test_an_unknown_clan_is_404_and_writes_and_calls_nothing(w):
    _sa, token = w.sa()
    r = w.post(token, uuid.uuid4())
    assert (r.status_code, code(r)) == (404, "NOT_FOUND") and w.nothing_written()


def test_without_the_admin_api_nothing_is_written_at_all(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    w.provider.admin_api_enabled = False
    r = w.post(token, clan.clan_id)
    assert (r.status_code, code(r)) == (503, "PROVIDER_UNAVAILABLE") and w.nothing_written()


# ------------------------------------------------------------------ success: what is written


def test_a_success_is_201_with_the_owner_and_the_password_shown_once(w):
    sa, token = w.sa()
    clan, reg = w.clan()
    r = w.post(token, clan.clan_id, key="key-success-0001")
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store" and "idempotency-replayed" not in r.headers
    body = r.json()
    assert set(body) == {"job_id", "status", "clan_id", "user_id", "owner_email", "owner_display_name",
                         "temporary_password", "temporary_password_expires_at", "email_delivery_status"}
    assert (body["status"], body["clan_id"], body["owner_email"], body["owner_display_name"]) == (
        "SUCCEEDED", str(clan.clan_id), OWNER_EMAIL, OWNER_NAME)  # the e-mail keeps its letter case
    assert body["temporary_password"] == KNOWN and body["email_delivery_status"] is None
    assert body["temporary_password_expires_at"] == "2026-10-11T09:00:00Z"  # 72 hours after the success
    assert w.sender.calls == [(OWNER_EMAIL, OWNER_NAME, KNOWN, FROZEN + timedelta(hours=72))]


def test_the_owner_account_is_pending_must_change_the_password_and_has_a_72_hour_temporary_one(w):
    sa, token = w.sa()
    clan, _ = w.clan()
    body = w.post(token, clan.clan_id).json()
    [user] = w.owner_users()
    job = w.job()
    assert (str(user.user_id), user.email, user.display_name, user.phone) == (body["user_id"], OWNER_EMAIL, OWNER_NAME, OWNER_PHONE)
    assert (user.status, user.first_login_required, user.email_verified, user.firebase_uid) == (
        "PENDING", True, False, f"own-{job.job_id}")
    cred = w.repo.creds[user.user_id]
    assert (cred.must_change_password, cred.temporary_password_issued_at, cred.temporary_password_expires_at,
            cred.password_changed_at, cred.auth_provider) == (True, FROZEN, FROZEN + timedelta(hours=72), None, "FIREBASE")
    [membership] = [m for m in w.family.memberships if m.user_id == user.user_id]
    assert (membership.clan_id, membership.status, membership.joined_at) == (clan.clan_id, "ACTIVE", FROZEN)
    [grant] = [g for g in w.repo.roles if g.user_id == user.user_id]
    assert (grant.role_code, grant.clan_id) == ("BUSINESS_OWNER", clan.clan_id)
    [owner] = w.family.owners
    assert (owner.clan_id, owner.user_id, owner.started_at, owner.ended_at) == (clan.clan_id, user.user_id, FROZEN, None)
    assert clan.status == "PENDING"  # the clan becomes ACTIVE only through clan.activate (E7)
    assert w.repo.sessions and all(s.user_id != user.user_id for s in w.repo.sessions.values())  # no session for the Owner


def test_the_job_ends_succeeded_with_its_flags_and_the_firebase_user_exists(w):
    sa, token = w.sa()
    clan, _ = w.clan()
    body = w.post(token, clan.clan_id).json()
    job = w.job()
    assert (str(job.job_id), job.status, str(job.user_id), job.attempt_count) == (body["job_id"], "SUCCEEDED", body["user_id"], 1)
    assert (job.firebase_user_created, job.needs_cleanup, job.lease_expires_at, job.error_code) == (True, False, None, None)
    assert (job.requested_by, job.clan_id, job.firebase_uid, job.completed_at) == (sa.user_id, clan.clan_id, f"own-{job.job_id}", FROZEN)
    assert (job.email, job.display_name, job.phone) == (OWNER_EMAIL, OWNER_NAME, OWNER_PHONE)
    fb = w.provider.provider_users[f"own-{job.job_id}"]
    assert (fb.email, fb.display_name, fb.disabled) == (OWNER_EMAIL, OWNER_NAME, False)
    assert [op for op, _ in w.provider.provider_calls] == ["get_user", "create_user"]


def test_the_generated_password_has_the_planned_shape_and_reaches_firebase(monkeypatch):
    monkeypatch.setattr(use_cases, "utcnow", lambda: FROZEN)
    w = OwnerWorld()  # the real generator
    _sa, token = w.sa()
    clan, _ = w.clan()
    password = w.post(token, clan.clan_id).json()["temporary_password"]
    assert len(password) == 16 and re.fullmatch(r"[A-Za-z0-9]{16}", password)
    assert w.provider.password_shapes == [("create_user", 16, True, True, True, False)]
    assert w.sender.calls[0][2] == password


def test_with_the_symbol_option_the_password_holds_a_symbol(monkeypatch):
    monkeypatch.setattr(use_cases, "utcnow", lambda: FROZEN)
    monkeypatch.setattr(settings, "OWNER_TEMP_PASSWORD_REQUIRE_SYMBOL", True)
    w = OwnerWorld()
    _sa, token = w.sa()
    clan, _ = w.clan()
    assert w.post(token, clan.clan_id).status_code == 201
    assert w.provider.password_shapes == [("create_user", 16, True, True, True, True)]


def test_four_commits_and_firebase_is_never_called_with_uncommitted_work_open(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    assert w.post(token, clan.clan_id).status_code == 201
    assert w.tx.events == ["commit"] * 4  # T1 accept, T2 start, T3 firebase_user_created, T4 the rows
    assert w.provider.open_transaction_calls == [] and len(w.provider.provider_calls) == 2


def test_one_audit_row_per_job_state_change_and_nothing_personal_in_any_of_them(w):
    sa, token = w.sa()
    clan, _ = w.clan()
    r = w.post(token, clan.clan_id)
    job = w.job()
    rows = [a for a in w.repo.audit if a["action"] == "provisioning_job.transition"]
    assert [a["new_data"]["event"] for a in rows] == ["created", "started", "succeeded"]
    assert [(a["old_data"] or {}).get("status") for a in rows] == [None, "PENDING", "RUNNING"]
    assert [a["new_data"]["status"] for a in rows] == ["PENDING", "RUNNING", "SUCCEEDED"]
    for a in rows:
        assert (a["actor_id"], a["entity_type"], a["entity_id"], a["clan_id"]) == (sa.user_id, "provisioning_job", job.job_id, clan.clan_id)
        assert set(a["new_data"]) == {"event", "status", "attempt_count", "error_code", "needs_cleanup", "user_id", "request_id"}
        assert a["new_data"]["request_id"] == r.headers["X-Request-ID"] and a.get("reason") is None
    assert rows[2]["new_data"]["user_id"] == str(job.user_id)
    blob = repr(rows)
    for secret in (OWNER_EMAIL, OWNER_EMAIL.lower(), OWNER_NAME, OWNER_PHONE, CLAN_NAME, KNOWN, job.firebase_uid, "@"):
        assert secret not in blob, secret


def test_the_audit_records_the_connecting_address_not_a_forwarded_one(monkeypatch):
    monkeypatch.setattr(use_cases, "utcnow", lambda: FROZEN)
    w = OwnerWorld(client_ip="203.0.113.9")
    _sa, token = w.sa()
    clan, _ = w.clan()
    assert w.post(token, clan.clan_id, headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 201
    assert {a["ip_address"] for a in w.repo.audit if a["action"] == "provisioning_job.transition"} == {"203.0.113.9"}


# ------------------------------------------------------------------ where the owner's data comes from


def test_by_default_the_owner_is_the_representative_of_the_business_registration(w):
    _sa, token = w.sa()
    clan, reg = w.clan(name="Rep Name", email="Rep.Mail@Example.TEST", phone="+84 900 000 001")
    body = w.post(token, clan.clan_id).json()
    assert (body["owner_email"], body["owner_display_name"]) == ("Rep.Mail@Example.TEST", "Rep Name")
    assert w.job().phone == "+84 900 000 001"


def test_the_body_may_override_each_field_on_its_own(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    body = w.post(token, clan.clan_id, body={"email": "Other.Person@Example.TEST", "phone": "+84 911 111 111"}).json()
    assert (body["owner_email"], body["owner_display_name"]) == ("Other.Person@Example.TEST", OWNER_NAME)
    assert w.job().phone == "+84 911 111 111"
    clan2, _ = w.clan()
    body2 = w.post(token, clan2.clan_id, body={"display_name": "A. New Name"}).json()
    assert (body2["owner_email"], body2["owner_display_name"]) == (OWNER_EMAIL, "A. New Name")


def test_a_clan_without_a_registration_needs_the_email_and_the_name_in_the_body(w):
    _sa, token = w.sa()
    clan, _ = w.clan(registration=False)
    for body in ("__none__", {}, {"email": "only.mail@example.test"}, {"display_name": "Only Name"}):
        r = w.post(token, clan.clan_id, body=body)
        assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR"), body
        assert "body." in r.json()["error"]["message"]
    assert w.nothing_written()
    ok = w.post(token, clan.clan_id, body={"email": "only.mail@example.test", "display_name": "Only Name"})
    assert ok.status_code == 201 and w.job().phone is None


# ------------------------------------------------------------------ the password exists only in the response


def test_the_password_is_nowhere_but_the_response_and_the_sender(w, caplog):
    caplog.set_level(logging.DEBUG)
    _sa, token = w.sa()
    clan, _ = w.clan()
    r = w.post(token, clan.clan_id)
    assert r.json()["temporary_password"] == KNOWN
    assert KNOWN not in everything_stored(w), "the password reached a stored row, an audit row, a key or a call log"
    assert KNOWN not in app_logs(caplog)
    jr = w.get_job(token, r.json()["job_id"])
    assert KNOWN not in jr.text and OWNER_EMAIL not in jr.text and OWNER_PHONE not in jr.text


def test_the_stored_idempotency_response_has_no_password_and_no_personal_data(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    body = w.post(token, clan.clan_id).json()
    [row] = w.idem.rows
    assert row.status == "COMPLETED" and row.response_status == 201
    assert row.response_body == {"job_id": body["job_id"], "status": "SUCCEEDED", "clan_id": str(clan.clan_id), "user_id": body["user_id"]}
    assert (row.resource_type, str(row.resource_id)) == ("provisioning_job", body["job_id"])
    assert not any("password" in k for k in row.response_body)


def test_nothing_personal_reaches_a_log_on_success(w, caplog):
    caplog.set_level(logging.DEBUG)
    _sa, token = w.sa()
    clan, _ = w.clan()
    r = w.post(token, clan.clan_id, key="my-very-own-key-12345")
    logged = app_logs(caplog)
    for secret in (OWNER_EMAIL, OWNER_EMAIL.lower(), OWNER_NAME, OWNER_PHONE, CLAN_NAME, KNOWN, "my-very-own-key-12345"):
        assert secret not in logged, secret
    assert r.headers["X-Request-ID"] in logged


# ------------------------------------------------------------------ the idempotency


def test_a_replay_answers_with_the_job_and_nulls_never_the_password(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    first = w.post(token, clan.clan_id, key="key-replay-00001", body={"phone": "+84 922 222 222"}).json()
    w.provider.provider_calls.clear()
    stored = (len(w.jobs.jobs), len(w.idem.rows), len(w.repo.audit), len(w.repo.users))
    again = w.post(token, clan.clan_id, key="key-replay-00001", body={"phone": "+84 922 222 222"})
    assert again.status_code == 201 and again.headers["idempotency-replayed"] == "true" and again.headers["cache-control"] == "no-store"
    body = again.json()
    assert (body["job_id"], body["status"], body["clan_id"], body["user_id"]) == (first["job_id"], "SUCCEEDED", first["clan_id"], first["user_id"])
    for field in ("temporary_password", "temporary_password_expires_at", "owner_email", "owner_display_name", "email_delivery_status"):
        assert body[field] is None, field
    assert KNOWN not in again.text and OWNER_EMAIL not in again.text
    assert w.provider.provider_calls == []  # no Firebase call, no new work
    assert stored == (len(w.jobs.jobs), len(w.idem.rows), len(w.repo.audit), len(w.repo.users))


def test_absent_empty_and_null_bodies_are_the_same_request_for_the_replay(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    first = w.post(token, clan.clan_id, key="key-same-request", body={"email": None}).json()
    for body in ("__none__", {}, None):
        again = w.post(token, clan.clan_id, key="key-same-request", body=body)
        assert again.status_code == 201 and again.json()["job_id"] == first["job_id"]
        assert again.headers["idempotency-replayed"] == "true"


def test_the_same_key_with_a_different_request_is_a_conflict(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    other, _ = w.clan()
    w.post(token, clan.clan_id, key="key-conflict-0001")
    for r in (
        w.post(token, clan.clan_id, key="key-conflict-0001", body={"email": "different@example.test"}),
        w.post(token, other.clan_id, key="key-conflict-0001"),  # the clan is in the hash
    ):
        assert (r.status_code, code(r)) == (409, "IDEMPOTENCY_KEY_CONFLICT")
    assert len(w.jobs.jobs) == 1 and len(w.owner_users()) == 1


def test_a_different_key_after_a_success_is_409_the_clan_has_its_owner(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    assert w.post(token, clan.clan_id).status_code == 201
    r = w.post(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "already has an Owner" in r.json()["error"]["message"]
    assert len(w.jobs.jobs) == 1 and [k.idempotency_key for k in w.idem.rows] == [w.idem.rows[0].idempotency_key]


def test_a_request_that_died_leaves_a_key_in_progress_and_the_same_key_gets_409_with_the_job_id(w):
    _sa, token = w.sa()
    clan, _ = w.clan()

    async def die(uid):
        raise Crash()

    w.provider.hooks["get_user"] = die
    with pytest.raises(Crash):
        w.post(token, clan.clan_id, key="key-process-died-1")
    job = w.job()
    assert (job.status, job.attempt_count) == ("RUNNING", 1)  # committed by T1 and T2; nothing recorded the death
    assert job.lease_expires_at == FROZEN + timedelta(seconds=settings.PROVISIONING_LEASE_SECONDS) == FROZEN + timedelta(seconds=90)
    [row] = w.idem.rows
    assert (row.status, row.resource_id) == ("IN_PROGRESS", job.job_id)
    w.provider.hooks.clear()
    again = w.post(token, clan.clan_id, key="key-process-died-1")
    assert (again.status_code, code(again)) == (409, "STATE_CONFLICT")
    assert str(job.job_id) in again.json()["error"]["message"] and again.headers["retry-after"] == "5"
    assert len(w.jobs.jobs) == 1 and w.owner_users() == []  # no second job
    other_key = w.post(token, clan.clan_id)  # another key: the live job of the clan blocks it
    assert (other_key.status_code, code(other_key)) == (409, "STATE_CONFLICT") and str(job.job_id) in other_key.json()["error"]["message"]


def test_an_in_progress_key_with_a_different_request_is_a_conflict_not_a_busy_answer(w):
    _sa, token = w.sa()
    clan, _ = w.clan()

    async def die(uid):
        raise Crash()

    w.provider.hooks["get_user"] = die
    with pytest.raises(Crash):
        w.post(token, clan.clan_id, key="key-died-and-changed")
    w.provider.hooks.clear()
    r = w.post(token, clan.clan_id, key="key-died-and-changed", body={"email": "other@example.test"})
    assert (r.status_code, code(r)) == (409, "IDEMPOTENCY_KEY_CONFLICT")


# ------------------------------------------------------------------ the checks before any job exists


@pytest.mark.parametrize("status", ["ACTIVE", "SUSPENDED", "EXPIRED", "LOCKED", "INACTIVE"])
def test_only_a_pending_clan_gets_an_owner_and_the_409_names_the_status(w, status):
    _sa, token = w.sa()
    clan, _ = w.clan(status)
    r = w.post(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and status in r.json()["error"]["message"]
    assert w.nothing_written()


def test_a_clan_that_already_has_an_owner_is_409(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    w.family.add_owner(clan, w.user())
    r = w.post(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and w.provider.provider_calls == []
    assert w.jobs.jobs == {}


def test_an_email_that_is_already_an_account_is_409_in_any_letter_case(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    existing = w.user()
    existing.email = OWNER_EMAIL.upper()
    r = w.post(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "DUPLICATE_RESOURCE")
    assert w.jobs.jobs == {} and w.provider.provider_calls == []


def seed_job(w, clan_id, email, *, status, needs_cleanup=False, created=FROZEN - timedelta(hours=1)):
    import asyncio

    job = asyncio.run(w.jobs.insert_pending(job_id=uuid.uuid4(), clan_id=clan_id, requested_by=uuid.uuid4(),
                                            email=email, display_name="X", phone=None, now=created))
    job.status = status
    if status == "RUNNING":
        job.lease_expires_at = FROZEN + timedelta(seconds=30)
    if needs_cleanup:
        job.firebase_user_created, job.needs_cleanup = True, True
    return job


def test_a_live_job_for_the_clan_blocks_a_new_one_and_a_live_job_for_the_email_on_another_clan_too(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    other, _ = w.clan()
    for status in ("PENDING", "RUNNING", "FAILED_RETRYABLE"):
        job = seed_job(w, clan.clan_id, "someone.else@example.test", status=status)
        r = w.post(token, clan.clan_id)
        assert (r.status_code, code(r)) == (409, "STATE_CONFLICT"), status
        assert str(job.job_id) in r.json()["error"]["message"] and status in r.json()["error"]["message"]
        del w.jobs.jobs[job.job_id]
    seed_job(w, other.clan_id, OWNER_EMAIL.upper(), status="RUNNING")  # the same e-mail, another clan
    r = w.post(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "DUPLICATE_RESOURCE")
    assert w.provider.provider_calls == [] and w.idem.rows == []


def test_a_firebase_cleanup_still_owed_blocks_the_clan_and_the_email_first(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    other, _ = w.clan()
    owed = seed_job(w, other.clan_id, OWNER_EMAIL.lower(), status="FAILED", needs_cleanup=True)
    r = w.post(token, clan.clan_id)  # blocked through the E-MAIL
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "clean-up" in r.json()["error"]["message"]
    assert str(owed.job_id) in r.json()["error"]["message"]
    del w.jobs.jobs[owed.job_id]
    on_clan = seed_job(w, clan.clan_id, "another@example.test", status="FAILED", needs_cleanup=True)
    r = w.post(token, clan.clan_id)  # blocked through the CLAN
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and str(on_clan.job_id) in r.json()["error"]["message"]
    assert w.provider.provider_calls == [] and w.idem.rows == []


def test_a_failed_job_without_a_pending_cleanup_does_not_block_a_new_one(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    old = seed_job(w, clan.clan_id, OWNER_EMAIL, status="FAILED")
    r = w.post(token, clan.clan_id)
    assert r.status_code == 201 and r.json()["job_id"] != str(old.job_id)
    assert len(w.jobs.jobs) == 2 and w.provider.provider_users.keys() == {f"own-{r.json()['job_id']}"}


def test_the_unique_indexes_are_the_last_line_of_defence_and_give_the_same_409(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    other, _ = w.clan()
    w.jobs.blind_blocking = True  # the pre-check says "nothing in the way": only the indexes can answer
    seed_job(w, clan.clan_id, "someone.else@example.test", status="RUNNING")
    r = w.post(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
    seed_job(w, other.clan_id, OWNER_EMAIL.upper(), status="PENDING")
    clan3, _ = w.clan()
    r = w.post(token, clan3.clan_id)
    assert (r.status_code, code(r)) == (409, "DUPLICATE_RESOURCE")
    assert w.idem.rows == [] and w.provider.provider_calls == []


# ------------------------------------------------------------------ failures: the job, the key, firebase, the password


def failed_world(monkeypatch):
    monkeypatch.setattr(use_cases, "utcnow", lambda: FROZEN)
    monkeypatch.setattr(use_cases, "_default_password", lambda: KNOWN)
    return OwnerWorld(raise_server_exceptions=False)


def run_failure(w, *, key="key-failure-0001"):
    _sa, token = w.sa()
    clan, _ = w.clan()
    return clan, token, w.post(token, clan.clan_id, key=key)


def assert_clean_failure(w, r, caplog=None):
    """Whatever failed: no Owner rows, the key is free, the password is nowhere, and the error names the job."""
    assert w.owner_users() == [] and w.family.owners == []
    assert w.idem.rows == []  # a failure is not stored: the key is released
    assert KNOWN not in r.text and KNOWN not in everything_stored(w) and OWNER_EMAIL not in r.text
    assert str(w.job().job_id) in r.json()["error"]["message"] or w.job().status == "FAILED"
    if caplog is not None:
        assert KNOWN not in app_logs(caplog) and OWNER_EMAIL not in app_logs(caplog)


@pytest.mark.parametrize("operation, fault, http, error, job_error", [
    ("get_user", ProviderUnavailable("timeout"), 503, "PROVIDER_UNAVAILABLE", "PROVIDER_UNAVAILABLE"),
    ("create_user", ProviderUnavailable("timeout"), 503, "PROVIDER_UNAVAILABLE", "PROVIDER_UNAVAILABLE"),
    ("create_user", PasswordRejected(), 503, "PROVIDER_UNAVAILABLE", "PASSWORD_POLICY_REJECTED"),
])
def test_a_temporary_provider_failure_leaves_a_retryable_job_and_nothing_else(monkeypatch, caplog, operation, fault, http, error, job_error):
    caplog.set_level(logging.DEBUG)
    w = failed_world(monkeypatch)
    w.provider.faults[operation] = [fault]
    _clan, _token, r = run_failure(w)
    assert (r.status_code, code(r)) == (http, error)
    job = w.job()
    assert (job.status, job.error_code, job.lease_expires_at, job.needs_cleanup, job.attempt_count) == ("FAILED_RETRYABLE", job_error, None, False, 1)
    assert job.firebase_user_created is False and w.provider.provider_users == {}
    assert w.provider.open_transaction_calls == []
    assert [a["new_data"]["event"] for a in w.repo.audit] == ["created", "started", "failed_retryable"]
    assert w.repo.audit[-1]["new_data"]["error_code"] == job_error
    assert_clean_failure(w, r, caplog)


def test_the_password_policy_has_its_own_code_distinct_from_an_outage(monkeypatch):
    w = failed_world(monkeypatch)
    w.provider.faults["create_user"] = [PasswordRejected()]
    _clan, _token, r = run_failure(w)
    assert w.job().error_code == "PASSWORD_POLICY_REJECTED" != "PROVIDER_UNAVAILABLE"
    assert "password policy" in r.json()["error"]["message"]


def test_a_create_whose_answer_was_lost_leaves_the_firebase_user_and_a_retryable_job(monkeypatch):
    w = failed_world(monkeypatch)
    w.provider.faults["create_user"] = [After(ProviderUnavailable("timeout"))]
    _clan, _token, r = run_failure(w)
    job = w.job()
    assert (r.status_code, job.status, job.firebase_user_created) == (503, "FAILED_RETRYABLE", False)  # we cannot know
    assert list(w.provider.provider_users) == [f"own-{job.job_id}"]  # ... but the user is there: a retry's get_user finds it
    assert [op for op, _ in w.provider.provider_calls] == ["get_user", "create_user"]  # no delete: it is retryable


def test_a_final_failure_commits_the_cleanup_flags_before_the_delete_and_lowers_them_after(monkeypatch):
    w = failed_world(monkeypatch)
    seen = {}

    async def spy(uid):
        job = w.job()
        seen.update(status=job.status, needs_cleanup=job.needs_cleanup, created=job.firebase_user_created,
                    uncommitted=w.tx.uncommitted(), uid=uid)

    w.provider.hooks["delete_user"] = spy
    w.provider.faults["create_user"] = [ProviderInvalidUser()]
    _clan, _token, r = run_failure(w)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
    # at the moment of the delete: FAILED + needs_cleanup + firebase_user_created were ALREADY committed
    assert seen == {"status": "FAILED", "needs_cleanup": True, "created": True, "uncommitted": False, "uid": f"own-{w.job().job_id}"}
    job = w.job()
    assert (job.status, job.error_code, job.needs_cleanup, job.firebase_user_created) == ("FAILED", "PROVIDER_REJECTED_USER", False, False)
    assert [a["new_data"]["event"] for a in w.repo.audit] == ["created", "started", "failed", "cleanup_done"]
    assert [op for op, _ in w.provider.provider_calls] == ["get_user", "create_user", "delete_user"]
    assert_clean_failure(w, r)


def test_the_cleanup_deletes_the_users_own_uid_even_when_we_are_not_sure_it_exists(monkeypatch):
    w = failed_world(monkeypatch)
    w.provider.faults["create_user"] = [ProviderInvalidUser()]
    _clan, _token, r = run_failure(w)
    job = w.job()
    assert ("delete_user", f"own-{job.job_id}") in w.provider.provider_calls  # firebase_user_created was never true before
    assert job.firebase_user_created is False  # confirmed absent afterwards


def test_an_email_taken_by_another_firebase_account_is_409_and_that_account_is_never_touched(monkeypatch):
    w = failed_world(monkeypatch)
    from app.core.firebase import ProviderUser

    stranger = ProviderUser(uid="google-uid-stranger", email=OWNER_EMAIL.upper(), display_name="Stranger", disabled=False)
    w.provider.provider_users[stranger.uid] = stranger
    _clan, _token, r = run_failure(w)
    assert (r.status_code, code(r)) == (409, "DUPLICATE_RESOURCE")
    job = w.job()
    assert (job.status, job.error_code, job.needs_cleanup) == ("FAILED", "PROVIDER_EMAIL_TAKEN", False)
    assert w.provider.provider_users == {stranger.uid: stranger}  # still there, unchanged
    assert [uid for op, uid in w.provider.provider_calls if op == "delete_user"] == [f"own-{job.job_id}"]  # never the stranger's
    assert all(uid.startswith("own-") for op, uid in w.provider.provider_calls if op in ("create_user", "delete_user"))


def test_an_unexpected_user_under_our_uid_is_a_final_failure_and_is_never_deleted(monkeypatch):
    """UID_MISMATCH: a user under own-<job_id> with ANOTHER e-mail is not ours to judge: it stays at Firebase,
    the job is FAILED without needs_cleanup (nothing blocked), audited, and the caller gets a 409."""
    w = failed_world(monkeypatch)
    from app.core.firebase import ProviderUser

    stranger = {}

    async def plant(uid):
        stranger[uid] = ProviderUser(uid=uid, email="not.the.owner@example.test", display_name="Someone Else", disabled=False)
        w.provider.provider_users[uid] = stranger[uid]

    w.provider.hooks["get_user"] = plant
    clan, token, r = run_failure(w)
    job = w.job()
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "left untouched" in r.json()["error"]["message"]
    assert (job.status, job.error_code, job.needs_cleanup, job.lease_expires_at) == ("FAILED", "UID_MISMATCH", False, None)
    assert job.completed_at == FROZEN and job.firebase_user_created is False
    assert [op for op, _ in w.provider.provider_calls] == ["get_user"]  # no create, no set_password, NO delete
    assert w.provider.provider_users == stranger  # the stranger is still there, unchanged
    rows = [a for a in w.repo.audit if a["action"] == "provisioning_job.transition"]
    assert [a["new_data"]["event"] for a in rows] == ["created", "started", "failed"]
    assert (rows[-1]["new_data"]["error_code"], rows[-1]["new_data"]["needs_cleanup"], rows[-1]["new_data"]["status"]) == ("UID_MISMATCH", False, "FAILED")
    blob = repr(rows)
    for secret in ("not.the.owner@example.test", "Someone Else", OWNER_EMAIL, OWNER_EMAIL.lower(), OWNER_NAME, KNOWN, "@"):
        assert secret not in blob, secret
    assert w.idem.rows == [] and w.owner_users() == []
    w.provider.hooks.clear()
    again = w.post(token, clan.clan_id)  # FAILED without needs_cleanup blocks nothing: a new job, a new uid
    assert again.status_code == 201 and again.json()["job_id"] != str(job.job_id)


def test_when_the_delete_fails_the_flags_stay_up_and_keep_the_clan_and_the_email_blocked(monkeypatch):
    w = failed_world(monkeypatch)
    w.provider.faults["create_user"] = [ProviderInvalidUser()]
    w.provider.faults["delete_user"] = [ProviderUnavailable("timeout")]
    clan, token, r = run_failure(w)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")  # the ORIGINAL error, not the cleanup's
    job = w.job()
    assert (job.status, job.needs_cleanup, job.firebase_user_created, job.error_code) == ("FAILED", True, True, "PROVIDER_REJECTED_USER")
    assert [a["new_data"]["event"] for a in w.repo.audit][-2:] == ["failed", "cleanup_failed"]
    blocked = w.post(token, clan.clan_id)
    assert (blocked.status_code, code(blocked)) == (409, "STATE_CONFLICT") and "clean-up" in blocked.json()["error"]["message"]
    assert len(w.jobs.jobs) == 1


def test_a_cleanup_whose_flag_update_fails_still_leaves_the_flags_up(monkeypatch):
    w = failed_world(monkeypatch)
    w.provider.faults["create_user"] = [ProviderInvalidUser()]
    original = w.jobs.finish_cleanup

    async def broken(job, **kw):
        raise OperationalError("UPDATE", {}, Exception("simulated"))

    w.jobs.finish_cleanup = broken
    _clan, _token, r = run_failure(w)
    job = w.job()
    assert r.status_code == 409 and (job.needs_cleanup, job.firebase_user_created) == (True, True)  # the delete is idempotent: a clean-up retry is safe
    w.jobs.finish_cleanup = original


def test_a_database_failure_after_firebase_leaves_a_retryable_job_and_the_firebase_user(monkeypatch):
    w = failed_world(monkeypatch)

    async def broken(job, **kw):
        raise OperationalError("UPDATE", {}, Exception("simulated"))

    w.jobs.mark_firebase_user_created = broken  # T3
    _clan, _token, r = run_failure(w)
    job = w.job()
    assert (r.status_code, code(r)) == (503, "DATABASE_UNAVAILABLE")
    assert (job.status, job.error_code, job.needs_cleanup) == ("FAILED_RETRYABLE", "DATABASE_UNAVAILABLE", False)
    assert list(w.provider.provider_users) == [f"own-{job.job_id}"]  # kept: a retry reuses it with a NEW password
    assert [op for op, _ in w.provider.provider_calls] == ["get_user", "create_user"]
    assert w.idem.rows == [] and w.owner_users() == []


def test_a_database_failure_while_writing_the_rows_rolls_the_rows_back(monkeypatch):
    w = failed_world(monkeypatch)

    async def broken(*a, **kw):
        raise OperationalError("INSERT", {}, Exception("simulated"))

    w.repo.add_clan_role = broken  # T4, after the user, credential, membership were flushed
    _clan, _token, r = run_failure(w)
    job = w.job()
    assert (r.status_code, code(r)) == (503, "DATABASE_UNAVAILABLE") and job.status == "FAILED_RETRYABLE"
    assert w.owner_users() == [] and w.repo.creds == {} and w.family.memberships == [] and w.family.owners == []
    assert w.idem.rows == [] and list(w.provider.provider_users) == [f"own-{job.job_id}"]


def test_an_owner_email_taken_between_the_checks_and_the_rows_is_final_and_cleaned(monkeypatch):
    w = failed_world(monkeypatch)

    async def race(uid):  # another account takes the e-mail while Firebase is being called
        other = w.user()
        other.email = OWNER_EMAIL.lower()
        await w.tx.commit()

    w.provider.hooks["create_user"] = race
    _clan, _token, r = run_failure(w)
    job = w.job()
    assert (r.status_code, code(r)) == (409, "DUPLICATE_RESOURCE")
    assert (job.status, job.error_code, job.needs_cleanup) == ("FAILED", "OWNER_EMAIL_EXISTS", False)
    assert w.provider.provider_users == {} and w.family.owners == []  # compensated


def test_a_clan_that_changed_meanwhile_is_final_and_cleaned(monkeypatch):
    w = failed_world(monkeypatch)
    holder = {}

    async def activate(uid):
        holder["clan"].status = "ACTIVE"

    w.provider.hooks["create_user"] = activate
    _sa, token = w.sa()
    clan, _ = w.clan()
    holder["clan"] = clan
    r = w.post(token, clan.clan_id)
    job = w.job()
    assert (r.status_code, job.status, job.error_code) == (409, "FAILED", "CLAN_STATE_CHANGED")
    assert w.provider.provider_users == {} and w.owner_users() == []


def test_an_unexpected_integrity_error_is_a_500_and_a_retryable_job_never_a_409(monkeypatch):
    w = failed_world(monkeypatch)

    async def odd(**kw):
        raise IntegrityError("INSERT clan_memberships", {}, _DbError("some_unknown_constraint"))

    w.family.create_membership = odd
    _clan, _token, r = run_failure(w)
    job = w.job()
    assert (r.status_code, code(r)) == (500, "INTERNAL_ERROR")
    assert (job.status, job.error_code) == ("FAILED_RETRYABLE", "INTERNAL_ERROR") and w.owner_users() == []


def test_the_active_owner_index_is_read_as_the_clan_having_changed(monkeypatch):
    w = failed_world(monkeypatch)

    async def taken(**kw):
        raise IntegrityError("INSERT clan_ownership_history", {}, _DbError("uq_active_clan_owner"))

    w.family.create_ownership = taken
    _clan, _token, r = run_failure(w)
    assert (r.status_code, w.job().error_code, w.job().status) == (409, "CLAN_STATE_CHANGED", "FAILED")


def test_after_the_maximum_attempts_a_temporary_failure_becomes_final(monkeypatch):
    w = failed_world(monkeypatch)
    monkeypatch.setattr(settings, "PROVISIONING_MAX_ATTEMPTS", 1)
    w.provider.faults["get_user"] = [ProviderUnavailable("timeout")]
    _clan, _token, r = run_failure(w)
    job = w.job()
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "no longer be retried" in r.json()["error"]["message"]
    assert (job.status, job.error_code, job.needs_cleanup) == ("FAILED", "PROVIDER_UNAVAILABLE", False)  # cleaned: nothing existed
    assert [a["new_data"]["event"] for a in w.repo.audit] == ["created", "started", "failed", "cleanup_done"]


def test_a_run_that_was_replaced_writes_nothing_and_deletes_nothing(monkeypatch):
    w = failed_world(monkeypatch)

    async def taken_over(uid):  # another run claims the job (attempt_count moves on) while this one is in Firebase
        w.job().attempt_count += 1
        await w.tx.commit()  # (committed by that other run)

    w.provider.hooks["create_user"] = taken_over
    clan, token, r = run_failure(w)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "replaced" in r.json()["error"]["message"]
    job = w.job()
    assert (job.status, job.attempt_count) == ("RUNNING", 2)  # untouched by the old run
    assert job.firebase_user_created is False  # T3 did not write on behalf of a run that was replaced
    assert job.lease_expires_at == FROZEN + timedelta(seconds=90)  # nor extend the lease the newer attempt owns
    assert w.owner_users() == [] and w.family.owners == []
    assert "delete_user" not in [op for op, _ in w.provider.provider_calls]  # the new run owns the Firebase user now


def test_fencing_looks_at_the_attempt_not_at_the_lease_clock(monkeypatch):
    """A run whose lease has run out, but which nobody replaced, still finishes."""
    w = failed_world(monkeypatch)

    async def lease_over(uid):
        w.job().lease_expires_at = FROZEN - timedelta(hours=5)
        await w.tx.commit()

    w.provider.hooks["create_user"] = lease_over
    _clan, _token, r = run_failure(w)
    assert r.status_code == 201 and w.job().status == "SUCCEEDED"


def test_a_run_whose_job_is_no_longer_running_writes_nothing(monkeypatch):
    w = failed_world(monkeypatch)

    async def finished_elsewhere(uid):
        w.job().status = "FAILED_RETRYABLE"
        w.job().lease_expires_at = None
        await w.tx.commit()

    w.provider.hooks["create_user"] = finished_elsewhere
    _clan, _token, r = run_failure(w)
    assert r.status_code == 409 and w.owner_users() == [] and w.job().status == "FAILED_RETRYABLE"


def test_when_even_the_failure_cannot_be_recorded_the_job_stays_running_and_the_error_is_still_the_original(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    w = failed_world(monkeypatch)
    w.provider.faults["get_user"] = [ProviderUnavailable("timeout")]
    original = w.jobs.finish_retryable

    async def down(job, **kw):
        raise OperationalError("UPDATE", {}, Exception("simulated"))

    w.jobs.finish_retryable = down
    _clan, _token, r = run_failure(w)
    assert (r.status_code, code(r)) == (503, "PROVIDER_UNAVAILABLE")
    job = w.job()
    assert job.status == "RUNNING" and job.lease_expires_at is not None  # a retry takes it over once the lease runs out
    assert "failure_not_recorded" in app_logs(caplog) and OWNER_EMAIL not in app_logs(caplog)
    w.jobs.finish_retryable = original


def test_the_heartbeat_after_firebase_renews_the_lease_and_marks_the_user_created(monkeypatch):
    """T3: firebase_user_created and a fresh lease are committed BEFORE the rows are written."""
    monkeypatch.setattr(use_cases, "utcnow", lambda: FROZEN)
    monkeypatch.setattr(use_cases, "_default_password", lambda: KNOWN)
    w = OwnerWorld()
    seen = {}
    original = w.jobs.finish_succeeded

    async def spy(job, **kw):
        seen.update(created=job.firebase_user_created, lease=job.lease_expires_at, status=job.status)
        await original(job, **kw)

    w.jobs.finish_succeeded = spy
    _sa, token = w.sa()
    clan, _ = w.clan()
    assert w.post(token, clan.clan_id).status_code == 201
    assert seen == {"created": True, "lease": FROZEN + timedelta(seconds=90), "status": "RUNNING"}


def test_a_firebase_user_left_by_an_earlier_attempt_is_reused_with_a_new_password(monkeypatch):
    w = failed_world(monkeypatch)
    from app.core.firebase import ProviderUser

    async def left_behind(uid):  # an earlier attempt of this same job created the user, then its answer was lost
        w.provider.provider_users[uid] = ProviderUser(uid=uid, email=OWNER_EMAIL.upper(), display_name=OWNER_NAME, disabled=False)

    w.provider.hooks["get_user"] = left_behind
    _clan, _token, r = run_failure(w)
    assert r.status_code == 201 and r.json()["temporary_password"] == KNOWN
    job = w.job()
    assert [op for op, _ in w.provider.provider_calls] == ["get_user", "set_password"]  # no create_user: the user is reused
    assert w.provider.password_changes == [f"own-{job.job_id}"]  # ... and its forgotten password is replaced
    assert w.provider.password_shapes == [("set_password", 16, True, True, True, False)]
    assert job.status == "SUCCEEDED" and len(w.owner_users()) == 1


def test_a_parallel_creation_of_the_same_job_is_recognised_and_the_user_is_reused(monkeypatch):
    w = failed_world(monkeypatch)
    from app.core.firebase import ProviderUser

    async def parallel(uid):  # another run of this job creates the user between our get_user and our create_user
        w.provider.provider_users[uid] = ProviderUser(uid=uid, email=OWNER_EMAIL, display_name=OWNER_NAME, disabled=False)

    w.provider.hooks["create_user"] = parallel
    _clan, _token, r = run_failure(w)
    assert r.status_code == 201
    assert [op for op, _ in w.provider.provider_calls] == ["get_user", "create_user", "set_password"]
    assert w.job().status == "SUCCEEDED" and w.provider.password_changes == [f"own-{w.job().job_id}"]


def test_a_run_replaced_between_the_last_two_transactions_writes_no_owner(monkeypatch):
    w = failed_world(monkeypatch)
    original = w.jobs.mark_firebase_user_created

    async def then_taken_over(job, **kw):  # T3 commits, and THEN another run claims the job
        await original(job, **kw)
        job.attempt_count += 1

    w.jobs.mark_firebase_user_created = then_taken_over
    _clan, _token, r = run_failure(w)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "replaced" in r.json()["error"]["message"]
    job = w.job()
    assert (job.status, job.attempt_count) == ("RUNNING", 2)  # still the newer attempt's, untouched by T4
    assert w.owner_users() == [] and w.family.owners == [] and w.repo.creds == {}
    assert "delete_user" not in [op for op, _ in w.provider.provider_calls]


def test_a_replaced_run_that_then_fails_does_not_overwrite_the_newer_attempts_job(monkeypatch):
    w = failed_world(monkeypatch)

    async def taken_over(uid):  # replaced while in Firebase ...
        w.job().attempt_count += 1
        await w.tx.commit()

    w.provider.hooks["create_user"] = taken_over
    w.provider.faults["create_user"] = [ProviderUnavailable("timeout")]  # ... and then the old run's call fails
    _clan, _token, r = run_failure(w)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "replaced" in r.json()["error"]["message"]
    job = w.job()
    assert (job.status, job.attempt_count, job.error_code, job.needs_cleanup) == ("RUNNING", 2, None, False)  # not FAILED_RETRYABLE
    assert [row.status for row in w.idem.rows] == ["IN_PROGRESS"]  # the newer attempt's key is not released either
    assert "delete_user" not in [op for op, _ in w.provider.provider_calls]
    assert [a["new_data"]["event"] for a in w.repo.audit] == ["created", "started"]


# ------------------------------------------------------------------ the e-mail sender


def test_the_sender_result_is_reported_and_a_failure_to_send_never_undoes_the_owner(monkeypatch):
    monkeypatch.setattr(use_cases, "utcnow", lambda: FROZEN)
    w = OwnerWorld()
    w.sender = RecordingSender(result=EmailDeliveryResult(status="SENT"))
    w.client.app.dependency_overrides[get_email_sender] = lambda: w.sender
    _sa, token = w.sa()
    clan, _ = w.clan()
    assert w.post(token, clan.clan_id).json()["email_delivery_status"] == "SENT"
    w.sender = RecordingSender(error=RuntimeError("smtp is down"))
    clan2, _ = w.clan(email="second.owner@example.test")
    r = w.post(token, clan2.clan_id)
    assert r.status_code == 201 and r.json()["email_delivery_status"] == "FAILED" and r.json()["temporary_password"]
    assert [j.status for j in w.jobs.jobs.values()] == ["SUCCEEDED", "SUCCEEDED"]


# ------------------------------------------------------------------ order of work and locks


def test_the_order_of_work_and_the_lock_order(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    w.family.calls.clear()
    assert w.post(token, clan.clan_id).status_code == 201
    calls = w.family.calls
    t1 = ["idem.set_lock_timeout", "idem.insert", "lock_clan", "get_registration_by_id", "job.list_blocking",
          "job.insert_pending", "idem.set_resource"]
    first_phase = calls[: calls.index("idem.set_resource") + 1]
    assert [c for c in first_phase if c in t1] == t1  # T1: the key first, then the clan, the checks, the job
    # T4 locks the idempotency row, then the clan, then the job
    last_lock_clan = len(calls) - 1 - calls[::-1].index("lock_clan")
    last_key_lock = len(calls) - 1 - calls[::-1].index("idem.lock_existing")
    last_job_lock = len(calls) - 1 - calls[::-1].index("job.lock")
    assert last_key_lock < last_lock_clan < last_job_lock < calls.index("create_membership")
    assert "lock_user" not in calls and "lock_user" not in w.repo.calls  # never FOR UPDATE on users
    assert calls.index("job.mark_running") < calls.index("job.mark_created") < calls.index("job.finish_succeeded")


# ------------------------------------------------------------------ item 6: an expired temporary password is refused at login


def test_the_owner_created_by_a_job_is_restricted_and_the_expired_temporary_password_is_refused():
    w = OwnerWorld()  # real clock: /auth/session reads the real time
    sa, token = w.sa()
    clan, _ = w.clan()
    body = w.post(token, clan.clan_id).json()
    [user] = w.owner_users()
    cred = w.repo.creds[user.user_id]
    assert cred.must_change_password is True and cred.temporary_password_expires_at - cred.temporary_password_issued_at == timedelta(hours=72)
    id_token = w.provider.issue(user.firebase_uid)
    ok = w.client.post("/api/v1/auth/session", json={"id_token": id_token})
    assert ok.status_code == 201
    session = ok.json()
    assert session["requires_password_change"] is True and session["user"]["status"] == "PENDING"
    assert session["user"]["user_id"] == body["user_id"]
    cred.temporary_password_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)  # 72 hours later
    expired = w.client.post("/api/v1/auth/session", json={"id_token": w.provider.issue(user.firebase_uid)})
    assert (expired.status_code, code(expired)) == (403, "TEMPORARY_PASSWORD_EXPIRED")
    assert [h.failure_reason for h in w.tx.committed_login_history][-1] == "TEMPORARY_PASSWORD_EXPIRED"


def test_the_owner_cannot_sign_in_at_all_while_the_job_has_not_succeeded():
    w = OwnerWorld(raise_server_exceptions=False)
    _sa, token = w.sa()
    clan, _ = w.clan()
    w.provider.faults["get_user"] = [ProviderUnavailable("timeout")]
    assert w.post(token, clan.clan_id).status_code == 503
    assert w.owner_users() == []  # no users row: an ID token for own-<job> is "unknown uid" at POST /auth/session
    uid = f"own-{w.job().job_id}"
    r = w.client.post("/api/v1/auth/session", json={"id_token": w.provider.issue(uid)})
    assert (r.status_code, code(r)) == (401, "INVALID_ID_TOKEN")


# ------------------------------------------------------------------ GET /admin/provisioning-jobs/{id}


def test_a_job_can_be_read_by_an_sa_without_personal_data(w):
    _sa, token = w.sa()
    clan, _ = w.clan()
    ok = w.post(token, clan.clan_id).json()
    r = w.get_job(token, ok["job_id"])
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert set(body) == {"job_id", "job_type", "clan_id", "status", "user_id", "email_delivery_status", "attempt_count",
                         "needs_cleanup", "error_code", "created_at", "updated_at"}
    assert (body["status"], body["attempt_count"], body["needs_cleanup"], body["error_code"], body["job_type"]) == (
        "SUCCEEDED", 1, False, None, "OWNER_PROVISIONING")
    for hidden in (OWNER_EMAIL, OWNER_EMAIL.lower(), OWNER_PHONE, OWNER_NAME, f"own-{ok['job_id']}", KNOWN, "firebase"):
        assert hidden not in r.text, hidden


def test_a_failed_job_shows_its_error_code_and_pending_cleanup(monkeypatch):
    w = failed_world(monkeypatch)
    w.provider.faults["create_user"] = [ProviderInvalidUser()]
    w.provider.faults["delete_user"] = [ProviderUnavailable("timeout")]
    _clan, token, _r = run_failure(w)
    body = w.get_job(token, w.job().job_id).json()
    assert (body["status"], body["needs_cleanup"], body["error_code"], body["user_id"]) == ("FAILED", True, "PROVIDER_REJECTED_USER", None)


def test_an_unknown_job_is_404_and_a_bad_id_is_422(w):
    _sa, token = w.sa()
    r = w.get_job(token, uuid.uuid4())
    assert (r.status_code, code(r)) == (404, "NOT_FOUND")
    assert w.get_job(token, "not-a-uuid").status_code == 422


# ------------------------------------------------------------------ real app: not rate limited


def test_the_endpoints_are_not_rate_limited_on_the_real_app(monkeypatch):
    from app.main import app as real_app

    monkeypatch.setattr(use_cases, "utcnow", lambda: FROZEN)
    w = OwnerWorld()
    _sa, token = w.sa()
    overrides = {
        get_db: lambda: w.tx, get_user_access_repo: lambda: w.repo, get_family_repo: lambda: w.family,
        get_idempotency_repo: lambda: w.idem, get_provisioning_repo: lambda: w.jobs,
        get_identity_provider: lambda: w.provider, get_email_sender: lambda: w.sender,
    }
    real_app.dependency_overrides.update(overrides)
    try:
        assert real_app.state.rate_limiters.enabled is True
        client = TestClient(real_app, client=("203.0.113.79", 4000))
        for _ in range(40):  # far past the Guest threshold of 5 per hour
            w.tx.begin()
            r = client.post(f"/api/v1/admin/clans/{uuid.uuid4()}/owner",
                            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"k-{uuid.uuid4().hex}"})
            assert r.status_code == 404
            assert client.get(f"/api/v1/admin/provisioning-jobs/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}).status_code == 404
    finally:
        for dependency in overrides:
            real_app.dependency_overrides.pop(dependency, None)
