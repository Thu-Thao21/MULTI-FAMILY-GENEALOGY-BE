"""System Admin registration administration over HTTP (Mốc E, step E4): the real router and the
real authorization on fake repositories. List, detail and review: who may call, what is shown,
the state machine, the plan check, history, audit, and what must never leak."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.controllers.family_management.registration_admin_router import router
from app.core.errors import register_exception_handlers
from app.core.request_id import RequestIdMiddleware
from app.db.postgres import get_db
from app.dependencies.auth import get_user_access_repo
from app.dependencies.permissions import get_family_repo
from tests.fakes import NOW, FakeDb, FakeFamilyRepo, FakeUserAccessRepo, make_user

PREFIX = "/api/v1/admin/business-registrations"
STATUSES = ["PENDING", "APPROVED", "REJECTED", "DRAFT", "NEED_SUPPLEMENT", "CANCELLED"]
NOT_PENDING = [s for s in STATUSES if s != "PENDING"]

PERSONAL = {
    "name": "Tran Thi Zed",
    "email": "Applicant.Zed@Example.TEST",
    "phone": "+84 912 345 678",
    "clan_name": "Ho Tran Zed",
    "origin_place": "Zed Village",
}
REASON = "Missing the founding documents of the clan"


class AdminWorld:
    def __init__(self, *, raise_server_exceptions: bool = True, client_ip: str = "testclient") -> None:
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
        self.client = TestClient(app, raise_server_exceptions=raise_server_exceptions, client=(client_ip, 4000))
        self.plan = self.family.add_plan("TEST-ACTIVE", price="199000.00")

    def user(self, status="ACTIVE", **kw):
        return self.repo.add_user(make_user(status, **kw))

    def token(self, user) -> str:
        now = datetime.now(timezone.utc)
        return self.repo.seed_session(
            user, token=f"tok-{uuid.uuid4().hex}", created_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(hours=8),
        )

    def sa(self):
        user = self.user()
        self.repo.grant(user, "SYSTEM_ADMIN")
        return user, self.token(user)

    def registration(self, **kw):
        return self.family.add_registration(kw.pop("plan", self.plan), **kw)

    # ---- calls ----
    def list(self, token, **params):
        return self.client.get(PREFIX, headers=h(token), params=params)

    def detail(self, token, registration_id):
        return self.client.get(f"{PREFIX}/{registration_id}", headers=h(token))

    def review(self, token, registration_id, decision, reason=None, **extra):
        body = {"decision": decision, **extra}
        if reason is not None:
            body["reason"] = reason
        return self.client.post(f"{PREFIX}/{registration_id}/review", headers=h(token), json=body)


def h(token):
    return {"Authorization": f"Bearer {token}"}


def code(r) -> str:
    return r.json()["error"]["code"]


@pytest.fixture
def w() -> AdminWorld:
    return AdminWorld()


def nothing_written(w: AdminWorld) -> bool:
    return not (w.family.registration_history or w.repo.audit) and w.db.commits == 0


# ------------------------------------------------------------------ who may call


def endpoints(w: AdminWorld, reg):
    return [
        ("list", lambda t: w.list(t)),
        ("detail", lambda t: w.detail(t, reg.registration_id)),
        ("review", lambda t: w.review(t, reg.registration_id, "APPROVED")),
    ]


def test_an_anonymous_caller_is_401_on_every_endpoint(w):
    reg = w.registration()
    for _name, call in endpoints(w, reg):
        r = call("")
        assert (r.status_code, code(r)) == (401, "UNAUTHENTICATED")
    assert w.client.get(PREFIX).status_code == 401 and w.client.get(f"{PREFIX}/{reg.registration_id}").status_code == 401
    assert reg.status == "PENDING" and nothing_written(w)


def test_a_restricted_system_admin_session_is_403_password_change_required(w):
    reg = w.registration()
    sa = w.user(first_login_required=True)
    w.repo.grant(sa, "SYSTEM_ADMIN")
    token = w.token(sa)
    for _name, call in endpoints(w, reg):
        r = call(token)
        assert (r.status_code, code(r)) == (403, "PASSWORD_CHANGE_REQUIRED")
    assert reg.status == "PENDING" and nothing_written(w)


def non_sa_tokens(w: AdminWorld) -> dict[str, str]:
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
    other_clan = w.family.add_clan("ACTIVE")
    other_bo = w.user()
    w.repo.grant(other_bo, "BUSINESS_OWNER", other_clan.clan_id)
    w.family.add_owner(other_clan, other_bo)
    w.family.add_member(other_clan, other_bo)
    scoped_sa = w.user()
    w.repo.grant(scoped_sa, "SYSTEM_ADMIN", clan.clan_id)  # an SA grant tied to a clan is not system scope
    plain = w.user()
    return {name: w.token(u) for name, u in (
        ("business owner", bo), ("family admin", fa), ("member", member),
        ("other clan owner", other_bo), ("clan scoped SA grant", scoped_sa), ("account without role", plain))}


def test_everyone_who_is_not_a_system_admin_gets_403_and_nothing_changes(w):
    reg = w.registration()
    for who, token in non_sa_tokens(w).items():
        for name, call in endpoints(w, reg):
            r = call(token)
            assert (r.status_code, code(r)) == (403, "FORBIDDEN"), (who, name)
    assert reg.status == "PENDING" and reg.reviewed_by is None and nothing_written(w)
    assert "lock_registration" not in w.family.calls and "list_registrations_page" not in w.family.calls


def test_authorization_wins_over_validation_for_every_endpoint(w):
    """A caller without access must not learn anything from validation messages."""
    reg = w.registration()
    for who, token in non_sa_tokens(w).items():
        assert code(w.client.get(PREFIX, headers=h(token), params={"page": 0, "status": "NOPE", "q": "x"})) == "FORBIDDEN", who
        assert code(w.client.get(f"{PREFIX}/not-a-uuid", headers=h(token))) == "FORBIDDEN", who
        assert code(w.client.post(f"{PREFIX}/not-a-uuid/review", headers=h(token), json={"bad": 1})) == "FORBIDDEN", who
        assert code(w.client.post(f"{PREFIX}/{reg.registration_id}/review", headers=h(token),
                                  json={"decision": "REJECTED"})) == "FORBIDDEN", who  # reason missing, still 403
        assert code(w.client.post(f"{PREFIX}/{uuid.uuid4()}/review", headers=h(token),
                                  json={"decision": "APPROVED"})) == "FORBIDDEN", who  # unknown id: no 404 for them


def test_a_non_admin_cannot_tell_whether_a_registration_exists(w):
    reg = w.registration()
    token = next(iter(non_sa_tokens(w).values()))
    known = w.detail(token, reg.registration_id)
    unknown = w.detail(token, uuid.uuid4())
    assert known.status_code == unknown.status_code == 403 and known.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_the_admin_endpoints_are_not_rate_limited_on_the_real_app():
    """The registration limiter belongs to the Guest POSTs only. Use the real app, whose limiter
    is ON, and call every admin endpoint far past the Guest threshold (5 per hour)."""
    from app.main import app as real_app

    w = AdminWorld()
    reg = w.registration()
    sa, token = w.sa()
    real_app.dependency_overrides.update({
        get_db: lambda: w.db, get_user_access_repo: lambda: w.repo, get_family_repo: lambda: w.family})
    try:
        assert real_app.state.rate_limiters.enabled is True  # the limiter really is on
        client = TestClient(real_app, client=("203.0.113.77", 4000))
        for _ in range(40):
            assert client.get(PREFIX, headers=h(token)).status_code == 200
            assert client.get(f"{PREFIX}/{reg.registration_id}", headers=h(token)).status_code == 200
            assert client.post(f"{PREFIX}/{uuid.uuid4()}/review", headers=h(token),
                               json={"decision": "APPROVED"}).status_code == 404
        # the same address IS limited on the Guest registration endpoint of the same app
        blocked = [client.post("/api/v1/business-registrations", json={}).status_code for _ in range(7)]
        assert blocked.count(429) >= 1
    finally:
        for dep in (get_db, get_user_access_repo, get_family_repo):
            real_app.dependency_overrides.pop(dep, None)


def test_the_admin_router_source_never_mentions_the_rate_limiter():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "controllers" / "family_management" / "registration_admin_router.py").read_text(encoding="utf-8")
    assert "rate_limit" not in source.lower().replace("not rate limited", "")


# ------------------------------------------------------------------ list


LIST_KEYS = {"registration_id", "clan_name", "representative_name", "requested_plan_id",
             "requested_plan_code", "status", "created_at", "reviewed_at"}


def test_the_list_shows_exactly_the_planned_fields_and_none_of_the_personal_contact_data(w):
    _sa, token = w.sa()
    w.registration(name=PERSONAL["name"], email=PERSONAL["email"], phone=PERSONAL["phone"],
                   clan_name=PERSONAL["clan_name"], origin_place=PERSONAL["origin_place"],
                   rejection_reason="private reason", reviewed_by=uuid.uuid4())
    r = w.list(token)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    [item] = body["items"]
    assert set(item) == LIST_KEYS
    assert (item["clan_name"], item["representative_name"], item["requested_plan_code"]) == (
        "Ho Tran Zed", "Tran Thi Zed", "TEST-ACTIVE")
    assert body["total"] == 1 and (body["page"], body["page_size"]) == (1, 20)
    for absent in (PERSONAL["email"], PERSONAL["phone"], PERSONAL["origin_place"], "private reason",
                   "representative_email", "representative_phone", "origin_place", "rejection_reason",
                   "reviewed_by", "tracking_code", "status_history", "attachments", "clan_id"):
        assert absent not in r.text, absent


def test_the_list_is_newest_first_with_the_id_as_the_tie_breaker(w):
    _sa, token = w.sa()
    t = NOW
    old = w.registration(created_at=t - timedelta(days=2))
    new = w.registration(created_at=t)
    tie_a = w.registration(created_at=t - timedelta(days=1))
    tie_b = w.registration(created_at=t - timedelta(days=1))
    ids = [i["registration_id"] for i in w.list(token).json()["items"]]
    tied = sorted([str(tie_a.registration_id), str(tie_b.registration_id)], reverse=True)
    assert ids == [str(new.registration_id)] + tied + [str(old.registration_id)]


@pytest.mark.parametrize("status", STATUSES)
def test_the_status_filter_returns_only_that_status_and_the_total_follows(w, status):
    _sa, token = w.sa()
    for s in STATUSES:
        w.registration(status=s)
        w.registration(status=s)
    body = w.list(token, status=status).json()
    assert body["total"] == 2 and {i["status"] for i in body["items"]} == {status}


def test_an_unknown_status_is_422(w):
    _sa, token = w.sa()
    for bad in ("DONE", "pending", "", "APPROVED,REJECTED"):
        r = w.list(token, status=bad)
        assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR"), bad


def test_created_from_is_inclusive_and_created_to_is_exclusive(w):
    _sa, token = w.sa()
    t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    rows = [w.registration(created_at=t0 + timedelta(seconds=s)) for s in (-1, 0, 1, 2)]
    ids = {i: str(r.registration_id) for i, r in zip((-1, 0, 1, 2), rows)}

    def found(**params):
        return {i["registration_id"] for i in w.list(token, **params).json()["items"]}

    assert found(created_from="2026-10-01T12:00:00Z") == {ids[0], ids[1], ids[2]}  # the bound itself is in
    assert found(created_to="2026-10-01T12:00:02Z") == {ids[-1], ids[0], ids[1]}  # the bound itself is out
    assert found(created_from="2026-10-01T12:00:00Z", created_to="2026-10-01T12:00:01Z") == {ids[0]}
    assert found(created_from="2026-10-01T12:00:01Z", created_to="2026-10-01T12:00:01Z") == set()  # empty, not an error


def test_the_bounds_understand_other_time_zones(w):
    _sa, token = w.sa()
    reg = w.registration(created_at=datetime(2026, 10, 1, 5, 0, 0, tzinfo=timezone.utc))
    same_instant = w.list(token, created_from="2026-10-01T12:00:00+07:00").json()["items"]  # = 05:00Z
    assert [i["registration_id"] for i in same_instant] == [str(reg.registration_id)]
    assert w.list(token, created_from="2026-10-01T12:00:01+07:00").json()["items"] == []


@pytest.mark.parametrize("params", [
    {"created_from": "2026-10-01T12:00:00"}, {"created_to": "2026-10-01"}, {"created_from": "yesterday"},
    {"created_from": "2026-10-02T00:00:00Z", "created_to": "2026-10-01T00:00:00Z"}, {"created_from": ""},
])
def test_a_bound_without_a_time_zone_or_in_the_wrong_order_is_422(w, params):
    _sa, token = w.sa()
    r = w.list(token, **params)
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")


def test_the_search_matches_clan_name_representative_name_and_email_ignoring_case(w):
    _sa, token = w.sa()
    by_clan = w.registration(clan_name="Dòng họ Nguyễn Văn", name="Alpha One", email="alpha@example.test")
    by_name = w.registration(clan_name="Clan Beta", name="Trần Quốc Beta", email="beta@example.test")
    by_mail = w.registration(clan_name="Clan Gamma", name="Gamma Three", email="Zed.Mail@Example.TEST")

    def found(q):
        return {i["registration_id"] for i in w.list(token, q=q).json()["items"]}

    assert found("nguyễn văn") == {str(by_clan.registration_id)}
    assert found("NGUYỄN VĂN") == {str(by_clan.registration_id)}
    assert found("quốc") == {str(by_name.registration_id)}
    assert found("zed.mail@example") == {str(by_mail.registration_id)}
    assert found("clan") == {str(by_name.registration_id), str(by_mail.registration_id)}
    assert found("no such text") == set()


def test_search_wildcards_are_ordinary_characters(w):
    _sa, token = w.sa()
    percent = w.registration(clan_name="Fifty 50% Clan")
    underscore = w.registration(clan_name="Under_score Clan")
    backslash = w.registration(clan_name="Back\\slash Clan")
    plain = w.registration(clan_name="Plain Clan")

    def found(q):
        return {i["registration_id"] for i in w.list(token, q=q).json()["items"]}

    assert found("50%") == {str(percent.registration_id)}
    assert found("r_s") == {str(underscore.registration_id)}
    assert found("k\\s") == {str(backslash.registration_id)}
    assert found("%%") == set() and found("__") == set() and plain.registration_id


def test_search_text_is_collapsed_and_normalized_like_the_stored_names(w):
    import unicodedata

    _sa, token = w.sa()
    reg = w.registration(clan_name=unicodedata.normalize("NFC", "Họ Nguyễn"))
    for q in ("Họ    Nguyễn", unicodedata.normalize("NFD", "Họ Nguyễn"), "  Họ Nguyễn  "):
        assert [i["registration_id"] for i in w.list(token, q=q).json()["items"]] == [str(reg.registration_id)], repr(q)


@pytest.mark.parametrize("bad", ["a", " a ", "x" * 101, "bad\x00text", "tab\there", "new\nline", "bell\x07", "\x7f\x7f", ""])
def test_a_search_with_a_control_character_or_the_wrong_length_is_422_and_never_echoed(w, bad):
    _sa, token = w.sa()
    w.registration()
    r = w.list(token, q=bad)
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")
    assert len(bad.strip()) < 5 or bad.strip() not in r.json()["error"]["message"]  # the text is never echoed
    assert "list_registrations_page" not in w.family.calls  # it never reached the repository


def test_a_search_of_the_exact_limits_is_accepted(w):
    _sa, token = w.sa()
    assert w.list(token, q="ab").status_code == 200
    assert w.list(token, q="x" * 100).status_code == 200


def test_the_search_text_is_not_logged(w, caplog):
    caplog.set_level(logging.DEBUG)
    _sa, token = w.sa()
    w.list(token, q="applicant.secret@example.test")
    # the test client's own request line (httpx) is not the application: look at the app's records
    app_logs = " | ".join(r.getMessage() for r in caplog.records if not r.name.startswith(("httpx", "httpcore")))
    assert "applicant.secret" not in app_logs


def test_paging_and_the_total_follow_the_filters(w):
    _sa, token = w.sa()
    for i in range(7):
        w.registration(created_at=NOW - timedelta(minutes=i), status="PENDING" if i < 5 else "APPROVED")
    first = w.list(token, status="PENDING", page=1, page_size=2).json()
    last = w.list(token, status="PENDING", page=3, page_size=2).json()
    beyond = w.list(token, status="PENDING", page=9, page_size=2).json()
    assert (len(first["items"]), first["total"], first["page"], first["page_size"]) == (2, 5, 1, 2)
    assert (len(last["items"]), last["total"]) == (1, 5)
    assert beyond["items"] == [] and beyond["total"] == 5


@pytest.mark.parametrize("params", [{"page": 0}, {"page": -1}, {"page_size": 0}, {"page_size": 101}, {"page": "x"}])
def test_bad_paging_is_422_and_the_largest_page_is_accepted(w, params):
    _sa, token = w.sa()
    r = w.list(token, **params)
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")
    assert w.list(token, page_size=100).status_code == 200


def test_an_empty_list_is_an_empty_page(w):
    _sa, token = w.sa()
    assert w.list(token).json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


# ------------------------------------------------------------------ detail


def test_the_detail_shows_the_applicants_personal_data_and_everything_the_list_hides(w):
    sa, token = w.sa()
    reviewer = uuid.uuid4()
    reg = w.registration(status="REJECTED", reviewed_by=reviewer, reviewed_at=NOW, rejection_reason=REASON, **{
        "name": PERSONAL["name"], "email": PERSONAL["email"], "phone": PERSONAL["phone"],
        "clan_name": PERSONAL["clan_name"], "origin_place": PERSONAL["origin_place"]})
    r = w.detail(token, reg.registration_id)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert set(body) == LIST_KEYS | {"representative_email", "representative_phone", "origin_place", "reviewed_by",
                                     "rejection_reason", "updated_at", "clan_id", "status_history", "attachments"}
    assert body["representative_email"] == PERSONAL["email"] and body["representative_phone"] == PERSONAL["phone"]
    assert body["origin_place"] == "Zed Village" and body["rejection_reason"] == REASON
    assert body["reviewed_by"] == str(reviewer) and body["requested_plan_code"] == "TEST-ACTIVE"
    assert body["clan_id"] is None and body["status_history"] == [] and body["attachments"] == []


def test_the_detail_history_is_oldest_first_and_attachments_never_show_the_storage_key(w):
    _sa, token = w.sa()
    reg = w.registration(status="APPROVED")
    admin = uuid.uuid4()
    w.family.add_history(reg, "PENDING", "APPROVED", changed_by=admin, reason="ok", at=NOW + timedelta(hours=1))
    w.family.add_history(reg, None, "PENDING", at=NOW)
    attachment = w.family.add_attachment(reg, "founding-act.pdf")
    body = w.detail(token, reg.registration_id).json()
    assert [(h["from_status"], h["to_status"]) for h in body["status_history"]] == [(None, "PENDING"), ("PENDING", "APPROVED")]
    assert body["status_history"][0]["changed_by"] is None and body["status_history"][1]["changed_by"] == str(admin)
    assert set(body["status_history"][1]) == {"from_status", "to_status", "changed_by", "reason", "changed_at"}
    [item] = body["attachments"]
    assert set(item) == {"attachment_id", "file_name", "mime_type", "uploaded_at"}
    assert item["file_name"] == "founding-act.pdf"
    assert attachment.storage_key not in str(body) and "storage_key" not in str(body)


def test_the_detail_never_shows_the_tracking_hash(w):
    _sa, token = w.sa()
    reg = w.registration()
    text = w.detail(token, reg.registration_id).text
    assert reg.tracking_code_hash not in text and "tracking_code" not in text


def test_the_detail_shows_the_clan_once_the_business_exists(w):
    _sa, token = w.sa()
    reg = w.registration(status="APPROVED")
    clan = w.family.add_clan("PENDING")
    clan.registration_id = reg.registration_id
    assert w.detail(token, reg.registration_id).json()["clan_id"] == str(clan.clan_id)


def test_an_unknown_registration_is_404_and_a_bad_id_is_422(w):
    _sa, token = w.sa()
    r = w.detail(token, uuid.uuid4())
    assert (r.status_code, code(r)) == (404, "NOT_FOUND")
    r = w.client.get(f"{PREFIX}/not-a-uuid", headers=h(token))
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")


# ------------------------------------------------------------------ review: approve


REVIEW_KEYS = {"registration_id", "status", "reviewed_by", "reviewed_at", "reason_visible_to_applicant"}


def test_approving_updates_the_registration_writes_one_history_row_and_one_audit_row(w):
    sa, token = w.sa()
    reg = w.registration(**{"name": PERSONAL["name"], "email": PERSONAL["email"], "clan_name": PERSONAL["clan_name"]})
    r = w.review(token, reg.registration_id, "APPROVED")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert set(body) == REVIEW_KEYS
    assert body["status"] == "APPROVED" and body["registration_id"] == str(reg.registration_id)
    assert body["reviewed_by"] == str(sa.user_id) and body["reviewed_at"].endswith("Z")
    assert body["reason_visible_to_applicant"] is False
    assert (reg.status, reg.reviewed_by, reg.rejection_reason) == ("APPROVED", sa.user_id, None)
    assert reg.reviewed_at is not None and reg.updated_at == reg.reviewed_at
    [history] = w.family.registration_history
    assert (history.from_status, history.to_status, history.changed_by) == ("PENDING", "APPROVED", sa.user_id)
    assert history.reason is None and history.changed_at == reg.reviewed_at
    [audit] = w.repo.audit
    assert audit["actor_id"] == sa.user_id and audit.get("clan_id") is None
    assert (audit["action"], audit["entity_type"], audit["entity_id"]) == (
        "registration.review", "business_registration", reg.registration_id)
    assert audit["old_data"] == {"status": "PENDING"}
    assert set(audit["new_data"]) == {"status", "reason_length", "request_id"}
    assert audit["new_data"]["status"] == "APPROVED" and audit["new_data"]["reason_length"] is None
    assert audit.get("reason") is None and audit["occurred_at"] == reg.reviewed_at
    assert w.db.commits == 1 and w.db.rollbacks == 0  # all of it in one transaction


def test_an_approval_note_is_internal_only_it_never_reaches_rejection_reason_or_the_audit(w):
    sa, token = w.sa()
    reg = w.registration()
    note = "Checked by phone, internal note"
    r = w.review(token, reg.registration_id, "APPROVED", note)
    assert r.status_code == 200 and r.json()["reason_visible_to_applicant"] is False
    assert reg.rejection_reason is None  # tracking would publish this column: it stays empty
    [history] = w.family.registration_history
    assert history.reason == note
    [audit] = w.repo.audit
    assert audit["new_data"]["reason_length"] == len(note) and note not in repr(audit)


# ------------------------------------------------------------------ review: reject


def test_rejecting_needs_a_reason_and_makes_it_visible_to_the_applicant(w):
    sa, token = w.sa()
    reg = w.registration()
    r = w.review(token, reg.registration_id, "REJECTED", REASON)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == REVIEW_KEYS and body["status"] == "REJECTED" and body["reason_visible_to_applicant"] is True
    assert (reg.status, reg.rejection_reason, reg.reviewed_by) == ("REJECTED", REASON, sa.user_id)
    [history] = w.family.registration_history
    assert (history.from_status, history.to_status, history.reason) == ("PENDING", "REJECTED", REASON)


@pytest.mark.parametrize("body", [
    {"decision": "REJECTED"}, {"decision": "REJECTED", "reason": None}, {"decision": "REJECTED", "reason": ""},
    {"decision": "REJECTED", "reason": "   "}, {"decision": "REJECTED", "reason": "a\x00b"},
    {"decision": "REJECTED", "reason": "bell\x07"}, {"decision": "REJECTED", "reason": "lone\rcr"},
    {"decision": "REJECTED", "reason": "x" * 2001},
    {"decision": "APPROVED", "reason": "a\x00b"}, {"decision": "APPROVED", "reason": "x" * 2001},
], ids=["missing", "null", "empty", "blank", "nul", "bell", "lone-cr", "too-long", "approve-nul", "approve-too-long"])
def test_a_rejection_without_a_valid_reason_is_422_and_changes_nothing(w, body):
    _sa, token = w.sa()
    reg = w.registration()
    r = w.client.post(f"{PREFIX}/{reg.registration_id}/review", headers=h(token), json=body)
    assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")
    assert "x" * 40 not in r.json()["error"]["message"]
    assert reg.status == "PENDING" and nothing_written(w)
    assert "lock_registration" not in w.family.calls  # rejected before the use case, no lock taken


def test_a_multi_line_reason_is_stored_with_lf(w):
    _sa, token = w.sa()
    reg = w.registration()
    assert w.review(token, reg.registration_id, "REJECTED", "  first line\r\n\tsecond line\nthird  ").status_code == 200
    assert reg.rejection_reason == "first line\n\tsecond line\nthird"
    assert w.family.registration_history[0].reason == reg.rejection_reason


def test_a_reason_of_the_maximum_length_is_accepted(w):
    _sa, token = w.sa()
    reg = w.registration()
    assert w.review(token, reg.registration_id, "REJECTED", "x" * 2000).status_code == 200


# ------------------------------------------------------------------ the audit never holds the text or the applicant


def test_the_audit_row_holds_no_personal_data_no_clan_name_and_never_the_reason_text(w):
    sa, token = w.sa()
    for decision, text in (("REJECTED", REASON), ("APPROVED", "Internal approval note")):
        reg = w.registration(**{"name": PERSONAL["name"], "email": PERSONAL["email"],
                                "phone": PERSONAL["phone"], "clan_name": PERSONAL["clan_name"],
                                "origin_place": PERSONAL["origin_place"]})
        w.review(token, reg.registration_id, decision, text)
    assert len(w.repo.audit) == 2
    for audit in w.repo.audit:
        dump = repr(audit)
        for secret in (*PERSONAL.values(), REASON, "Internal approval note", "Missing the founding"):
            assert secret not in dump, secret
        assert audit.get("reason") is None  # the audit_logs.reason column stays empty
        assert isinstance(audit["new_data"]["reason_length"], int) and audit["new_data"]["reason_length"] > 0
        assert "@" not in dump
    assert w.repo.audit[0]["new_data"]["reason_length"] == len(REASON)


def test_the_reason_the_applicant_and_the_request_never_reach_a_log(w, caplog):
    caplog.set_level(logging.DEBUG)
    _sa, token = w.sa()
    reg = w.registration(**{"email": PERSONAL["email"], "name": PERSONAL["name"]})
    w.review(token, reg.registration_id, "REJECTED", REASON)
    w.detail(token, reg.registration_id)
    logged = caplog.text
    for secret in (REASON, PERSONAL["email"], PERSONAL["name"], "Missing the founding"):
        assert secret not in logged, secret
    assert "request_id=" in logged


# ------------------------------------------------------------------ the state machine


@pytest.mark.parametrize("current", NOT_PENDING)
@pytest.mark.parametrize("decision", ["APPROVED", "REJECTED"])
def test_only_a_pending_registration_can_be_reviewed_and_the_409_names_the_status(w, current, decision):
    sa, token = w.sa()
    original = dict(reviewed_by=uuid.uuid4(), reviewed_at=NOW, rejection_reason="earlier reason") if current in ("APPROVED", "REJECTED") else {}
    reg = w.registration(status=current, **PERSONAL_KW(), **original)
    snapshot = (reg.status, reg.reviewed_by, reg.reviewed_at, reg.rejection_reason, reg.updated_at)
    r = w.review(token, reg.registration_id, decision, REASON)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
    message = r.json()["error"]["message"]
    assert current in message and "PENDING" in message  # the current status is named (only an SA gets here)
    for secret in (*PERSONAL.values(), REASON, "Zed"):
        assert secret not in message, secret
    assert snapshot == (reg.status, reg.reviewed_by, reg.reviewed_at, reg.rejection_reason, reg.updated_at)
    assert nothing_written(w)
    assert "apply_registration_review" not in w.family.calls


def PERSONAL_KW() -> dict:
    return {"name": PERSONAL["name"], "email": PERSONAL["email"], "clan_name": PERSONAL["clan_name"]}


def test_both_decisions_are_final_a_second_review_in_any_direction_is_409(w):
    _sa, token = w.sa()
    for first, second in (("APPROVED", "APPROVED"), ("APPROVED", "REJECTED"), ("REJECTED", "APPROVED"), ("REJECTED", "REJECTED")):
        reg = w.registration()
        assert w.review(token, reg.registration_id, first, REASON).status_code == 200
        before = (reg.status, reg.reviewed_at, reg.rejection_reason)
        again = w.review(token, reg.registration_id, second, "another reason")
        assert (again.status_code, code(again)) == (409, "STATE_CONFLICT"), (first, second)
        assert first in again.json()["error"]["message"]
        assert (reg.status, reg.reviewed_at, reg.rejection_reason) == before
    assert len(w.family.registration_history) == 4 and len(w.repo.audit) == 4  # only the four first reviews


def test_an_unknown_registration_is_404_and_a_bad_id_or_body_is_422(w):
    _sa, token = w.sa()
    r = w.review(token, uuid.uuid4(), "APPROVED")
    assert (r.status_code, code(r)) == (404, "NOT_FOUND") and nothing_written(w)
    reg = w.registration()
    for bad_id in ("not-a-uuid", "1234"):
        r = w.client.post(f"{PREFIX}/{bad_id}/review", headers=h(token), json={"decision": "APPROVED"})
        assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")
    for body in ({}, {"decision": "MAYBE"}, {"decision": "approved"}, {"decision": "PENDING"},
                 {"decision": "APPROVED", "extra": 1}, {"decision": "APPROVED", "reviewed_by": str(uuid.uuid4())},
                 {"decision": "APPROVED", "status": "APPROVED"}):
        r = w.client.post(f"{PREFIX}/{reg.registration_id}/review", headers=h(token), json=body)
        assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR"), body
    assert reg.status == "PENDING" and nothing_written(w)


def test_the_reviewer_is_always_the_signed_in_administrator(w):
    first, first_token = w.sa()
    second, second_token = w.sa()
    a, b = w.registration(), w.registration()
    w.review(first_token, a.registration_id, "APPROVED")
    w.review(second_token, b.registration_id, "REJECTED", REASON)
    assert (a.reviewed_by, b.reviewed_by) == (first.user_id, second.user_id)
    assert [x["actor_id"] for x in w.repo.audit] == [first.user_id, second.user_id]
    assert [x.changed_by for x in w.family.registration_history] == [first.user_id, second.user_id]


# ------------------------------------------------------------------ the plan must still be ACTIVE to approve


@pytest.mark.parametrize("plan_status", ["INACTIVE", "RETIRED"])
def test_approving_needs_a_plan_that_is_still_active(w, plan_status):
    _sa, token = w.sa()
    plan = w.family.add_plan(f"TEST-{plan_status}", status=plan_status)
    reg = w.registration(plan=plan)
    r = w.review(token, reg.registration_id, "APPROVED")
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
    assert "plan" in r.json()["error"]["message"].lower() and "PENDING" not in r.json()["error"]["message"]
    assert reg.status == "PENDING" and reg.reviewed_by is None and nothing_written(w)


def test_approving_when_the_plan_no_longer_exists_is_409_too(w):
    _sa, token = w.sa()
    reg = w.registration()
    del w.family.plans[reg.requested_plan_id]
    r = w.review(token, reg.registration_id, "APPROVED")
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and reg.status == "PENDING" and nothing_written(w)


@pytest.mark.parametrize("plan_status", ["INACTIVE", "RETIRED"])
def test_rejecting_does_not_look_at_the_plan(w, plan_status):
    _sa, token = w.sa()
    plan = w.family.add_plan(f"TEST-{plan_status}", status=plan_status)
    reg = w.registration(plan=plan)
    r = w.review(token, reg.registration_id, "REJECTED", REASON)
    assert r.status_code == 200 and reg.status == "REJECTED"
    assert "get_plan_by_id" not in w.family.calls  # a rejection never reads the plan


def test_rejecting_works_even_when_the_plan_is_gone(w):
    _sa, token = w.sa()
    reg = w.registration()
    del w.family.plans[reg.requested_plan_id]
    assert w.review(token, reg.registration_id, "REJECTED", REASON).status_code == 200


def test_an_active_plan_lets_the_approval_through_and_the_plan_is_read_once(w):
    _sa, token = w.sa()
    reg = w.registration()
    assert w.review(token, reg.registration_id, "APPROVED").status_code == 200
    assert w.family.calls.count("get_plan_by_id") == 1


def test_the_status_check_comes_before_the_plan_check(w):
    """An already reviewed registration is reported for what it is, whatever happened to its plan."""
    _sa, token = w.sa()
    plan = w.family.add_plan("TEST-OLD", status="INACTIVE")
    reg = w.registration(plan=plan, status="REJECTED", rejection_reason="x", reviewed_at=NOW, reviewed_by=uuid.uuid4())
    r = w.review(token, reg.registration_id, "APPROVED")
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "REJECTED" in r.json()["error"]["message"]
    assert "get_plan_by_id" not in w.family.calls


# ------------------------------------------------------------------ locking and transaction


def test_the_registration_is_locked_first_the_users_row_never_and_the_repository_never_commits(w):
    _sa, token = w.sa()
    reg = w.registration()
    w.family.calls.clear()
    w.repo.calls.clear()
    assert w.review(token, reg.registration_id, "APPROVED").status_code == 200
    calls = w.family.calls
    assert calls[0] == "lock_registration"
    assert calls.index("lock_registration") < calls.index("get_plan_by_id") < calls.index("apply_registration_review")
    assert calls.index("apply_registration_review") < calls.index("add_registration_status_history")
    assert calls.count("lock_registration") == 1
    assert "lock_user" not in w.repo.calls  # never FOR UPDATE on users (Mốc F deadlock lesson)
    assert w.db.commits == 1


def test_a_failed_commit_is_a_503_and_commits_nothing():
    w = AdminWorld(raise_server_exceptions=False)
    w.db.fail_commit = True
    _sa, token = w.sa()
    reg = w.registration()
    r = w.review(token, reg.registration_id, "APPROVED")
    assert (r.status_code, code(r)) == (503, "DATABASE_UNAVAILABLE")
    assert w.db.commits == 0


def test_the_audit_row_records_the_connecting_address_not_a_forwarded_one():
    w = AdminWorld(client_ip="203.0.113.9")
    _sa, token = w.sa()
    reg = w.registration()
    r = w.client.post(f"{PREFIX}/{reg.registration_id}/review", headers={**h(token), "X-Forwarded-For": "198.51.100.1"},
                      json={"decision": "APPROVED"})
    assert r.status_code == 200
    assert w.repo.audit[0]["ip_address"] == "203.0.113.9"


def test_a_review_changes_only_the_registration_it_names(w):
    _sa, token = w.sa()
    target, other = w.registration(), w.registration()
    w.review(token, target.registration_id, "REJECTED", REASON)
    assert other.status == "PENDING" and other.reviewed_by is None and other.rejection_reason is None
