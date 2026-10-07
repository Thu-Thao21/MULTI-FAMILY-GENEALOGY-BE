"""Guest registration and tracking over HTTP (Mốc E, step E3): the real router and error
handlers on fake repositories. Covers input rules, the tracking code, duplicates (the check and
the unique index), history, audit, the rate limiter on the endpoints and what must never leak."""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import unicodedata
import uuid

import pytest

from app.core.tokens import hash_tracking_code
from tests.guest_harness import PREFIX, GuestWorld, code_of

PENDING_INDEX = "uq_registration_pending_same_applicant"
HASH_KEY = "business_registrations_tracking_code_hash_key"
PLAN_FKEY = "business_registrations_requested_plan_id_fkey"

PERSONAL = {
    "representative_name": "Tran Thi Zed",
    "representative_email": "Applicant.Zed@Example.TEST",
    "representative_phone": "+84 912 345 678",
    "clan_name": "Ho Tran Zed",
    "origin_place": "Zed Village",
}


@pytest.fixture
def w() -> GuestWorld:
    return GuestWorld()


def row_values(row) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def everything_stored(w: GuestWorld) -> str:
    """Every value the fakes hold: rows, history, audit entries and the unit of work."""
    parts = [row_values(r) for r in w.family.registrations]
    parts += [row_values(r) for r in w.family.registration_history]
    parts += list(w.repo.audit)
    parts.append(vars(w.db))
    return repr(parts)


def only_registration(w: GuestWorld):
    assert len(w.family.registrations) == 1
    return w.family.registrations[0]


def nothing_written(w: GuestWorld) -> bool:
    return not (w.family.registrations or w.family.registration_history or w.repo.audit)


# ------------------------------------------------------------------ the 201


def test_a_registration_is_created_and_answers_with_the_tracking_code_once(w):
    r = w.register(**PERSONAL)
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"registration_id", "tracking_code", "status", "created_at"}
    assert body["status"] == "PENDING"
    assert body["created_at"].endswith("Z")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-request-id"]
    row = only_registration(w)
    assert str(row.registration_id) == body["registration_id"] and row.status == "PENDING"
    assert w.db.commits == 1 and w.db.rollbacks == 0


def test_the_tracking_code_has_at_least_256_bits_of_entropy_and_is_never_reused(w):
    codes = [w.register().json()["tracking_code"] for _ in range(4)]
    assert len(set(codes)) == 4
    for code in codes:
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", code), code
        raw = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
        assert len(raw) == 32  # 256 bits


def test_only_the_sha256_of_the_code_is_stored(w):
    code = w.register().json()["tracking_code"]
    row = only_registration(w)
    assert row.tracking_code_hash == hashlib.sha256(code.encode()).hexdigest()
    assert row.tracking_code_hash == hash_tracking_code(code)
    assert code not in everything_stored(w)


def test_the_stored_fields_are_exactly_what_the_applicant_typed_apart_from_cleaning(w):
    w.register(**PERSONAL)
    row = only_registration(w)
    assert row.representative_email == "Applicant.Zed@Example.TEST"  # never lower-cased
    assert (row.representative_name, row.clan_name, row.origin_place) == (
        "Tran Thi Zed", "Ho Tran Zed", "Zed Village")
    assert row.representative_phone == "+84 912 345 678"
    assert str(row.requested_plan_id) == str(w.plan.plan_id)


def test_the_status_history_and_one_audit_row_are_written_in_the_same_transaction(w):
    body = w.register(**PERSONAL).json()
    [history] = w.family.registration_history
    assert str(history.registration_id) == body["registration_id"]
    assert (history.from_status, history.to_status) == (None, "PENDING")
    assert history.changed_by is None and history.reason is None
    [audit] = w.repo.audit
    assert audit["actor_id"] is None  # a Guest has no account
    assert audit.get("clan_id") is None  # and there is no clan yet
    assert audit["action"] == "registration.create"
    assert audit["entity_type"] == "business_registration"
    assert str(audit["entity_id"]) == body["registration_id"]
    assert audit["old_data"] is None
    assert set(audit["new_data"]) == {"plan_id", "status", "request_id"}
    assert audit["new_data"]["status"] == "PENDING" and audit["new_data"]["plan_id"] == str(w.plan.plan_id)
    assert audit["ip_address"] == "203.0.113.7"
    assert w.db.commits == 1  # all three rows, one commit


def test_the_audit_row_holds_no_personal_data_and_no_tracking_code(w):
    code = w.register(**PERSONAL).json()["tracking_code"]
    [audit] = w.repo.audit
    dump = repr(audit)
    for value in PERSONAL.values():
        assert value not in dump, value
    assert code not in dump and hash_tracking_code(code) not in dump
    assert "@" not in dump


def test_no_account_is_needed_and_a_bearer_header_is_ignored(w):
    assert w.register().status_code == 201
    assert w.register(headers={"Authorization": "Bearer not-a-real-token"}).status_code == 201


def test_the_tracking_code_and_the_applicant_never_reach_a_log(w, caplog):
    caplog.set_level(logging.DEBUG)
    code = w.register(**PERSONAL).json()["tracking_code"]
    w.track(code)
    w.track("a-wrong-code")
    logged = caplog.text + " ".join(r.getMessage() for r in caplog.records)
    assert code not in logged and hash_tracking_code(code) not in logged
    for value in PERSONAL.values():
        assert value not in logged, value
    assert "request_id=" in logged  # the log still lets an operator follow a request


# ------------------------------------------------------------------ input rules


def bad_bodies(w: GuestWorld):
    good = w.body(**PERSONAL)
    cases = {}
    for field in ("representative_name", "representative_email", "clan_name", "requested_plan_id"):
        broken = dict(good)
        del broken[field]
        cases[f"missing-{field}"] = broken
    for field in ("representative_name", "clan_name", "origin_place"):
        cases[f"empty-{field}"] = {**good, field: ""}
        cases[f"blank-{field}"] = {**good, field: "   "}
        cases[f"too-long-{field}"] = {**good, field: "x" * 256}
        cases[f"nul-in-{field}"] = {**good, field: "bad\x00name"}
        cases[f"newline-in-{field}"] = {**good, field: "two\nlines"}
        cases[f"tab-in-{field}"] = {**good, field: "two\tcolumns"}
        cases[f"del-in-{field}"] = {**good, field: "bad\x7fname"}
        cases[f"c1-in-{field}"] = {**good, field: "bad\x85name"}
    for email in ("plain", "a@b", "a@@b.co", "a b@c.co", "@b.co", "a@.co", "a@b.", "x" * 250 + "@b.co"):
        cases[f"email-{email[:12]}"] = {**good, "representative_email": email}
    cases["email-nul"] = {**good, "representative_email": "a\x00@b.co"}
    for phone in ("abc", "12345", "++123456", "123456+", "12 34 56 x", "1" * 31):
        cases[f"phone-{phone[:12]}"] = {**good, "representative_phone": phone}
    cases["plan-not-a-uuid"] = {**good, "requested_plan_id": "not-a-uuid"}
    cases["plan-number"] = {**good, "requested_plan_id": 7}
    cases["unknown-field"] = {**good, "role": "BUSINESS_OWNER"}
    cases["extra-status"] = {**good, "status": "APPROVED"}
    return cases


def test_every_invalid_body_is_422_with_the_standard_envelope_and_writes_nothing():
    probe = GuestWorld()
    for name, body in bad_bodies(probe).items():
        w = GuestWorld()
        r = w.client.post(f"{PREFIX}/business-registrations", json=body)
        assert r.status_code == 422, name
        assert code_of(r) == "VALIDATION_ERROR", name
        envelope = r.json()["error"]
        assert envelope["request_id"] and set(envelope) == {"code", "message", "request_id"}
        assert nothing_written(w) and w.db.commits == 0, name
        assert "create_registration" not in w.family.calls, name
        message = envelope["message"]
        for secret in ("bad\x00name", "two\nlines", "plain", "x" * 40):
            assert secret not in message  # the value is never echoed back


def test_free_text_is_trimmed_collapsed_and_normalized_to_nfc(w):
    nfd_name = unicodedata.normalize("NFD", "  Nguyễn   Văn   Ạ  ")
    nfd_clan = unicodedata.normalize("NFD", "Họ   Nguyễn")
    w.register(representative_name=nfd_name, clan_name=nfd_clan, origin_place="  Hà   Nội ")
    row = only_registration(w)
    assert row.representative_name == unicodedata.normalize("NFC", "Nguyễn Văn Ạ")
    assert row.clan_name == unicodedata.normalize("NFC", "Họ Nguyễn")
    assert row.origin_place == "Hà Nội"
    assert unicodedata.is_normalized("NFC", row.representative_name)


def test_the_email_is_trimmed_but_keeps_its_case_and_the_phone_is_trimmed(w):
    w.register(representative_email="  Ann@Example.TEST \t", representative_phone="  +84 912 345 678 ")
    row = only_registration(w)
    assert row.representative_email == "Ann@Example.TEST"
    assert row.representative_phone == "+84 912 345 678"


def test_the_optional_fields_may_be_omitted_or_null(w):
    r = w.client.post(f"{PREFIX}/business-registrations", json={
        **w.body(), "representative_phone": None, "origin_place": None})
    assert r.status_code == 201
    row = only_registration(w)
    assert row.representative_phone is None and row.origin_place is None


def test_text_at_the_length_limits_is_accepted(w):
    assert w.register(clan_name="c" * 255, representative_name="n" * 255).status_code == 201
    assert w.register(representative_email="e" * 243 + "@example.te").status_code == 201


# ------------------------------------------------------------------ the plan


def test_an_unknown_plan_is_422_and_writes_nothing(w):
    r = w.register(requested_plan_id=str(uuid.uuid4()))
    assert (r.status_code, code_of(r)) == (422, "VALIDATION_ERROR")
    assert "requested_plan_id" in r.json()["error"]["message"]
    assert nothing_written(w) and "create_registration" not in w.family.calls


@pytest.mark.parametrize("status", ["INACTIVE", "RETIRED"])
def test_an_inactive_plan_gets_exactly_the_answer_of_an_unknown_one(w, status):
    plan = w.family.add_plan(f"TEST-{status}", status=status)
    unknown = w.register(requested_plan_id=str(uuid.uuid4()))
    inactive = w.register(requested_plan_id=str(plan.plan_id))
    assert inactive.status_code == unknown.status_code == 422
    assert inactive.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert code_of(inactive) == code_of(unknown) == "VALIDATION_ERROR"
    assert str(plan.plan_id) not in inactive.text and status not in inactive.text  # no probing
    assert nothing_written(w)


# ------------------------------------------------------------------ duplicates


def test_a_pending_duplicate_is_409_and_nothing_is_written(w):
    w.register(**PERSONAL)
    again = w.register(**PERSONAL)
    assert (again.status_code, code_of(again)) == (409, "DUPLICATE_RESOURCE")
    assert len(w.family.registrations) == 1 and len(w.family.registration_history) == 1 and len(w.repo.audit) == 1
    assert w.family.calls.count("create_registration") == 1  # the check stopped it before any write
    assert "Zed" not in again.text and "example" not in again.text


def test_the_duplicate_check_ignores_case_in_the_email_and_the_clan_name(w):
    w.register(representative_email="Ann@Example.TEST", clan_name="Ho Nguyen")
    r = w.register(representative_email="ann@EXAMPLE.test", clan_name="HO NGUYEN")
    assert (r.status_code, code_of(r)) == (409, "DUPLICATE_RESOURCE")


def test_the_duplicate_check_sees_through_the_unicode_spelling(w):
    w.register(representative_email="a@example.test", clan_name="Họ Nguyễn")
    r = w.register(representative_email="a@example.test",
                   clan_name=unicodedata.normalize("NFD", "Họ  Nguyễn"))
    assert (r.status_code, code_of(r)) == (409, "DUPLICATE_RESOURCE")


def test_a_different_clan_name_or_a_different_email_is_not_a_duplicate(w):
    assert w.register(representative_email="a@example.test", clan_name="One").status_code == 201
    assert w.register(representative_email="a@example.test", clan_name="Two").status_code == 201
    assert w.register(representative_email="b@example.test", clan_name="One").status_code == 201


def test_a_registration_that_is_no_longer_pending_does_not_block_a_new_one(w):
    w.register(representative_email="a@example.test", clan_name="One")
    only_registration(w).status = "REJECTED"
    assert w.register(representative_email="a@example.test", clan_name="One").status_code == 201
    assert len(w.family.registrations) == 2


def test_the_unique_index_is_the_last_line_of_defence_and_gives_the_same_409(w):
    """The check says "no" (as in a race); the INSERT then hits uq_registration_pending_same_applicant."""
    w.family.precheck_blind = True
    first = w.register(**PERSONAL)
    assert first.status_code == 201
    second = w.register(**PERSONAL)
    assert (second.status_code, code_of(second)) == (409, "DUPLICATE_RESOURCE")
    assert second.json()["error"]["message"] == w.register(**PERSONAL).json()["error"]["message"]
    assert w.db.rollbacks == 2 and w.db.commits == 1  # the two losers rolled back
    assert len(w.family.registrations) == len(w.family.registration_history) == len(w.repo.audit) == 1


def test_the_same_409_whether_the_check_or_the_index_stops_it(w):
    w.register(**PERSONAL)
    by_check = w.register(**PERSONAL)
    w.family.precheck_blind = True
    by_index = w.register(**PERSONAL)
    assert by_check.status_code == by_index.status_code == 409
    assert by_check.json()["error"]["message"] == by_index.json()["error"]["message"]
    assert by_check.json()["error"]["code"] == by_index.json()["error"]["code"]


def test_a_tracking_code_collision_draws_a_new_code(w):
    w.family.create_registration_errors = [HASH_KEY]
    r = w.register()
    assert r.status_code == 201
    assert w.family.calls.count("create_registration") == 2
    assert w.db.rollbacks == 1 and w.db.commits == 1
    row = only_registration(w)
    assert row.tracking_code_hash == hash_tracking_code(r.json()["tracking_code"])


def test_a_plan_deleted_while_registering_is_422_not_500(w):
    w.family.create_registration_errors = [PLAN_FKEY]
    r = w.register()
    assert (r.status_code, code_of(r)) == (422, "VALIDATION_ERROR")
    assert w.db.rollbacks == 1 and nothing_written(w)


def test_an_unexpected_integrity_error_is_not_swallowed():
    w = GuestWorld(raise_server_exceptions=False)
    w.family.create_registration_errors = ["some_other_constraint"]
    r = w.register()
    assert (r.status_code, code_of(r)) == (500, "INTERNAL_ERROR")
    assert w.db.rollbacks == 1 and nothing_written(w)
    assert "some_other_constraint" not in r.text


def test_giving_up_after_three_tracking_code_collisions_is_a_500_and_leaves_nothing():
    w = GuestWorld(raise_server_exceptions=False)
    w.family.create_registration_errors = [HASH_KEY] * 3
    r = w.register()
    assert (r.status_code, code_of(r)) == (500, "INTERNAL_ERROR")
    assert w.db.rollbacks == 3 and w.db.commits == 0 and nothing_written(w)


# ------------------------------------------------------------------ tracking


TRACK_KEYS = {"clan_name", "status", "public_reason", "submitted_at", "updated_at"}


def test_tracking_returns_exactly_the_public_fields(w):
    created = w.register(**PERSONAL).json()
    r = w.track(created["tracking_code"])
    assert r.status_code == 200
    body = r.json()
    assert set(body) == TRACK_KEYS
    assert body["clan_name"] == "Ho Tran Zed" and body["status"] == "PENDING"
    assert body["public_reason"] is None
    assert body["submitted_at"].endswith("Z") and body["updated_at"].endswith("Z")
    assert r.headers["cache-control"] == "no-store"
    assert w.db.commits == 1  # tracking is read only: the registration's own commit and nothing else


def test_tracking_does_not_leak_the_hash_the_email_or_any_id(w):
    created = w.register(**PERSONAL).json()
    row = only_registration(w)
    text = w.track(created["tracking_code"]).text
    for secret in (
        row.tracking_code_hash, created["registration_id"], str(w.plan.plan_id),
        PERSONAL["representative_email"], PERSONAL["representative_name"],
        PERSONAL["representative_phone"], PERSONAL["origin_place"], "reviewed_by", "reviewed_at",
        "tracking_code", "registration_id", "requested_plan_id", "representative",
    ):
        assert secret not in text, secret


def test_a_rejection_reason_is_public_only_when_the_registration_is_rejected(w):
    code = w.register().json()["tracking_code"]
    row = only_registration(w)
    row.rejection_reason = "Incomplete documents"
    assert w.track(code).json()["public_reason"] is None  # a stray reason on a PENDING row stays private
    row.status = "APPROVED"
    assert w.track(code).json()["public_reason"] is None
    row.status = "REJECTED"
    body = w.track(code).json()
    assert body["status"] == "REJECTED" and body["public_reason"] == "Incomplete documents"


def test_tracking_follows_the_status_and_the_update_time(w):
    code = w.register().json()["tracking_code"]
    row = only_registration(w)
    row.status = "APPROVED"
    assert w.track(code).json()["status"] == "APPROVED"


@pytest.mark.parametrize(
    "wrong",
    ["x", " ", "not-the-code", "a" * 43, "A" * 8000, "../../etc", "0", "null", "đại"],
)
def test_every_wrong_code_gets_the_same_404(w, wrong):
    w.register()
    r = w.track(wrong)
    assert (r.status_code, code_of(r)) == (404, "NOT_FOUND")
    assert r.json()["error"]["message"] == w.track("something-else").json()["error"]["message"]
    message = r.json()["error"]["message"]
    assert wrong.strip() == "" or wrong.strip() not in message  # the guess is not echoed
    assert set(r.json()["error"]) == {"code", "message", "request_id"}


def test_the_code_is_not_trimmed_so_a_code_with_a_space_is_a_wrong_code(w):
    code = w.register().json()["tracking_code"]
    assert w.track(code).status_code == 200
    assert w.track(code + " ").status_code == 404
    assert w.track(" " + code).status_code == 404
    assert w.track(code.upper()).status_code == 404  # case matters: it is a random string


def test_a_code_with_unusual_characters_is_just_a_wrong_code_not_a_server_error(w):
    for odd in ("a\x00b", "a\nb", "‮evil", "a" * 1000):
        assert w.track(odd).status_code == 404


def test_invalid_track_bodies_are_422_and_do_not_echo_the_value(w):
    for body in ({}, {"tracking_code": ""}, {"tracking_code": 123}, {"tracking_code": None},
                 {"tracking_code": "x" * 9000}, {"tracking_code": "x", "extra": 1}):
        r = w.client.post(f"{PREFIX}/business-registrations/track", json=body)
        assert (r.status_code, code_of(r)) == (422, "VALIDATION_ERROR"), body
        message = r.json()["error"]["message"]
        assert "xxxx" not in message and "123" not in message


def test_a_registration_is_found_only_by_its_own_code(w):
    first = w.register(clan_name="First Clan").json()["tracking_code"]
    second = w.register(clan_name="Second Clan").json()["tracking_code"]
    assert w.track(first).json()["clan_name"] == "First Clan"
    assert w.track(second).json()["clan_name"] == "Second Clan"


# ------------------------------------------------------------------ rate limiting on the endpoints


def test_the_sixth_registration_in_an_hour_from_one_address_is_429_with_retry_after():
    w = GuestWorld()
    for _ in range(5):
        assert w.register().status_code == 201
    r = w.register()
    assert (r.status_code, code_of(r)) == (429, "RATE_LIMITED")
    assert r.headers["retry-after"] == "3600"
    assert r.json()["error"]["request_id"] == r.headers["x-request-id"]
    assert len(w.family.registrations) == 5  # the refused one wrote nothing
    w.clock.advance(1000)
    assert w.register().headers["retry-after"] == "2600"


def test_the_limit_frees_up_after_the_window():
    w = GuestWorld()
    for _ in range(5):
        w.register()
    assert w.register().status_code == 429
    w.clock.advance(3600)
    assert w.register().status_code == 201


def test_invalid_bodies_count_against_the_limit_too():
    w = GuestWorld()
    for _ in range(5):
        assert w.client.post(f"{PREFIX}/business-registrations", json={"nonsense": 1}).status_code == 422
    r = w.register()
    assert (r.status_code, code_of(r)) == (429, "RATE_LIMITED")


def test_rejected_and_duplicate_registrations_count_too():
    w = GuestWorld()
    same = dict(representative_email="a@example.test", clan_name="One")
    for _ in range(5):
        w.register(**same)  # one 201, then four 409
    assert w.register(**same).status_code == 429


def test_each_address_has_its_own_counter_and_registration_and_track_are_separate():
    w = GuestWorld()
    for _ in range(5):
        w.register()
    assert w.register().status_code == 429
    assert w.register(client=w.client_for("198.51.100.9")).status_code == 201  # another address
    assert w.track("anything").status_code == 404  # the track limiter is a different one


def test_the_track_limit_is_20_per_10_minutes():
    w = GuestWorld()
    for _ in range(20):
        assert w.track("wrong").status_code == 404
    r = w.track("wrong")
    assert (r.status_code, code_of(r)) == (429, "RATE_LIMITED") and r.headers["retry-after"] == "600"
    w.clock.advance(601)
    assert w.track("wrong").status_code == 404


def test_the_limiter_can_be_switched_off():
    w = GuestWorld(enabled=False)
    for _ in range(12):
        assert w.register().status_code == 201
    for _ in range(40):
        assert w.track("wrong").status_code == 404


def test_the_limits_are_configurable():
    w = GuestWorld(registration_max=2, registration_window=60, track_max=1, track_window=30)
    assert [w.register().status_code for _ in range(3)] == [201, 201, 429]
    assert [w.track("x").status_code for _ in range(2)] == [404, 429]
    assert w.track("x").headers["retry-after"] == "30"
