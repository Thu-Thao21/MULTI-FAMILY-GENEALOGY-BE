"""System Admin registration administration on the real PostgreSQL branch (Mốc E, E4).

Rolled back per test. The real routers run on a real session. Every test makes its OWN plan
(ITEST-...) and its OWN registrations, all carrying a per-test tag in the e-mail, and only ever
looks at those through the `q` filter: whatever else is in the database is neither read as an
expectation nor modified. The DEV-* plans are never touched.

What only a real PostgreSQL can prove: the ILIKE with ESCAPE, the case-insensitive match on
Vietnamese text, the date bounds on real timestamps, the ordering with the id tie breaker, the
total against a SQL count, the row lock statement, the foreign keys of history and audit, and the
end-to-end path Guest registers -> SA reviews -> Guest tracks.
"""

from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from app.models.family.entities import (
    BusinessRegistration,
    RegistrationAttachment,
    RegistrationStatusHistory,
)
from app.models.family.repository import FamilyRepository
from app.models.user_access.entities import AuditLog
from tests.integration.factory import bearer

PREFIX = "/api/v1/admin/business-registrations"
REASON = "Missing the founding documents of the clan"
T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


def tag() -> str:
    return uuid.uuid4().hex[:10]


async def sa_token(world):
    sa = await world.user()
    await world.grant(sa, "SYSTEM_ADMIN")
    return sa, await world.session_for(sa)


async def make(world, plan, t: str, n: int = 0, **kw):
    kw.setdefault("email", f"itest-{t}-{n}@example.test")
    return await world.registration(plan, **kw)


async def listed(client, token, t: str, **params) -> dict:
    r = await client.get(PREFIX, headers=bearer(token), params={"q": t, "page_size": 100, **params})
    assert r.status_code == 200, r.text
    return r.json()


def ids(body) -> list[str]:
    return [i["registration_id"] for i in body["items"]]


async def history_of(session, registration_id):
    rows = await session.execute(
        select(RegistrationStatusHistory)
        .where(RegistrationStatusHistory.registration_id == registration_id)
        .order_by(RegistrationStatusHistory.changed_at)
    )
    return list(rows.scalars().all())


async def audit_of(session, registration_id):
    rows = await session.execute(select(AuditLog).where(AuditLog.entity_id == registration_id))
    return list(rows.scalars().all())


# ------------------------------------------------------------------ who may call


async def test_only_a_system_admin_gets_in_on_the_real_database(real_client, session, world):
    plan = await world.plan()
    reg = await make(world, plan, tag())
    clan, owner = await world.business_owner()
    member = await world.user()
    await world.member(clan, member)
    plain = await world.user()
    scoped_sa = await world.user()
    await world.grant(scoped_sa, "SYSTEM_ADMIN", clan)  # an SA grant tied to a clan is not system scope
    for who in (owner, member, plain, scoped_sa):
        token = await world.session_for(who)
        for call in (
            real_client.get(PREFIX, headers=bearer(token)),
            real_client.get(f"{PREFIX}/{reg.registration_id}", headers=bearer(token)),
            real_client.post(f"{PREFIX}/{reg.registration_id}/review", headers=bearer(token), json={"decision": "APPROVED"}),
        ):
            r = await call
            assert (r.status_code, r.json()["error"]["code"]) == (403, "FORBIDDEN")
    assert (await session.get(BusinessRegistration, reg.registration_id)).status == "PENDING"
    assert await history_of(session, reg.registration_id) == [] and await audit_of(session, reg.registration_id) == []
    anonymous = await real_client.get(PREFIX)
    assert anonymous.status_code == 401


# ------------------------------------------------------------------ list


async def test_the_list_shows_only_the_planned_fields(real_client, world):
    t = tag()
    _sa, token = await sa_token(world)
    plan = await world.plan()
    await make(world, plan, t, name="Tran Thi Zed", phone="+84 912 345 678", origin_place="Zed Village")
    body = await listed(real_client, token, t)
    [item] = body["items"]
    assert set(item) == {"registration_id", "clan_name", "representative_name", "requested_plan_id",
                         "requested_plan_code", "status", "created_at", "reviewed_at"}
    assert item["requested_plan_code"] == plan.code and item["requested_plan_id"] == str(plan.plan_id)
    assert item["reviewed_at"] is None and body["total"] == 1
    for hidden in ("@example.test", "+84 912", "Zed Village", "representative_email", "representative_phone"):
        assert hidden not in str(body), hidden


async def test_the_list_is_newest_first_with_the_id_as_the_tie_breaker(real_client, world):
    t = tag()
    _sa, token = await sa_token(world)
    plan = await world.plan()
    old = await make(world, plan, t, 0, created_at=T0 - timedelta(days=2))
    new = await make(world, plan, t, 1, created_at=T0)
    tie_a = await make(world, plan, t, 2, created_at=T0 - timedelta(days=1))
    tie_b = await make(world, plan, t, 3, created_at=T0 - timedelta(days=1))
    tied = sorted([str(tie_a.registration_id), str(tie_b.registration_id)], reverse=True)
    assert ids(await listed(real_client, token, t)) == [str(new.registration_id)] + tied + [str(old.registration_id)]


async def test_status_filter_and_total_match_a_sql_count(real_client, session, world):
    t = tag()
    _sa, token = await sa_token(world)
    plan = await world.plan()
    plan_of = {}
    for n, status in enumerate(["PENDING", "PENDING", "APPROVED", "REJECTED", "DRAFT", "NEED_SUPPLEMENT", "CANCELLED", "PENDING"]):
        plan_of[(await make(world, plan, t, n, status=status)).registration_id] = status
    for status in {"PENDING", "APPROVED", "REJECTED", "DRAFT", "NEED_SUPPLEMENT", "CANCELLED"}:
        body = await listed(real_client, token, t, status=status)
        counted = (await session.execute(
            select(func.count()).select_from(BusinessRegistration).where(
                BusinessRegistration.representative_email.like(f"itest-{t}-%"), BusinessRegistration.status == status))).scalar_one()
        assert body["total"] == counted == sum(1 for s in plan_of.values() if s == status)
        assert {i["status"] for i in body["items"]} == {status}
    assert (await listed(real_client, token, t))["total"] == 8


async def test_paging_visits_every_row_once_and_total_is_stable(real_client, world):
    t = tag()
    _sa, token = await sa_token(world)
    plan = await world.plan()
    made = [str((await make(world, plan, t, n, created_at=T0 + timedelta(minutes=n))).registration_id) for n in range(7)]
    seen = []
    for page in (1, 2, 3, 4):
        body = (await real_client.get(PREFIX, headers=bearer(token), params={"q": t, "page": page, "page_size": 3})).json()
        assert body["total"] == 7 and body["page"] == page
        seen += ids(body)
    assert len(seen) == 7 and set(seen) == set(made) and seen == list(reversed(made))
    beyond = (await real_client.get(PREFIX, headers=bearer(token), params={"q": t, "page": 9, "page_size": 3})).json()
    assert beyond["items"] == [] and beyond["total"] == 7


async def test_the_search_matches_three_columns_ignoring_case_and_vietnamese_accents_as_typed(real_client, world):
    t = tag()
    _sa, token = await sa_token(world)
    plan = await world.plan()
    by_clan = await make(world, plan, t, 0, clan_name=f"Dòng họ Nguyễn Văn {t}")
    by_name = await make(world, plan, t, 1, name=f"Trần Quốc Bảo {t}", clan_name=f"Clan Beta {t}")
    by_mail = await make(world, plan, t, 2, email=f"Zed.Mail.{t}@Example.TEST", clan_name=f"Clan Gamma {t}")

    async def found(q):
        r = await real_client.get(PREFIX, headers=bearer(token), params={"q": q, "page_size": 100})
        assert r.status_code == 200, (q, r.text)
        return set(ids(r.json()))

    assert await found(f"nguyễn văn {t}") == {str(by_clan.registration_id)}
    assert await found(f"NGUYỄN VĂN {t}") == {str(by_clan.registration_id)}  # lower() handles Vietnamese (C.UTF-8)
    assert await found(f"trần quốc bảo {t}") == {str(by_name.registration_id)}
    assert await found(f"TRẦN QUỐC BẢO {t.upper()}") == {str(by_name.registration_id)}
    assert await found(f"zed.mail.{t}@example") == {str(by_mail.registration_id)}
    assert await found(f"clan gamma {t}") == {str(by_mail.registration_id)}
    assert await found(t) == {str(by_clan.registration_id), str(by_name.registration_id), str(by_mail.registration_id)}
    assert await found(unicodedata.normalize("NFD", f"nguyễn văn {t}")) == {str(by_clan.registration_id)}  # cleaned to NFC
    assert await found(f"no such text {t}") == set()


async def test_wildcards_and_backslash_in_the_search_are_ordinary_characters(real_client, world):
    t = tag()
    _sa, token = await sa_token(world)
    plan = await world.plan()
    percent = await make(world, plan, t, 0, clan_name=f"Fifty 50% {t}")
    other = await make(world, plan, t, 1, clan_name=f"Fifty 500 {t}")
    under = await make(world, plan, t, 2, clan_name=f"Under_score {t}")
    plain = await make(world, plan, t, 3, clan_name=f"UnderXscore {t}")
    back = await make(world, plan, t, 4, clan_name=f"Back\\slash {t}")

    async def found(q):
        r = await real_client.get(PREFIX, headers=bearer(token), params={"q": q, "page_size": 100})
        assert r.status_code == 200, (q, r.text)
        return set(ids(r.json()))

    assert await found(f"50% {t}") == {str(percent.registration_id)}  # not "50" followed by anything
    assert await found(f"under_score {t}") == {str(under.registration_id)}  # "_" is not "any one character"
    assert await found(f"back\\slash {t}") == {str(back.registration_id)}
    assert str(other.registration_id) not in await found(f"50% {t}") and str(plain.registration_id) not in await found(f"under_score {t}")
    # a pure wildcard text matches only rows that really contain it, never "everything"
    everything = await found("%" * 3)
    assert str(plain.registration_id) not in everything and str(other.registration_id) not in everything


async def test_an_injection_shaped_search_is_just_text(real_client, world):
    t = tag()
    _sa, token = await sa_token(world)
    plan = await world.plan()
    await make(world, plan, t)
    for q in ("x'; DROP TABLE business_registrations; --", "' OR '1'='1", "\" OR 1=1 --"):
        r = await real_client.get(PREFIX, headers=bearer(token), params={"q": q})
        assert r.status_code == 200 and r.json()["total"] == 0, q
    assert (await listed(real_client, token, t))["total"] == 1  # the table is still there


async def test_the_date_bounds_on_real_timestamps_are_inclusive_below_exclusive_above(real_client, world):
    t = tag()
    _sa, token = await sa_token(world)
    plan = await world.plan()
    rows = {}
    for n, delta in enumerate((-1, 0, 1, 2)):
        rows[delta] = str((await make(world, plan, t, n, created_at=T0 + timedelta(seconds=delta))).registration_id)

    async def found(**params):
        return set(ids(await listed(real_client, token, t, **params)))

    assert await found(created_from="2026-09-01T12:00:00Z") == {rows[0], rows[1], rows[2]}
    assert await found(created_to="2026-09-01T12:00:02Z") == {rows[-1], rows[0], rows[1]}
    assert await found(created_from="2026-09-01T12:00:00Z", created_to="2026-09-01T12:00:01Z") == {rows[0]}
    assert await found(created_from="2026-09-01T19:00:00+07:00", created_to="2026-09-01T19:00:01+07:00") == {rows[0]}
    assert await found(created_from="2026-09-01T12:00:01Z", created_to="2026-09-01T12:00:01Z") == set()
    r = await real_client.get(PREFIX, headers=bearer(token), params={"created_from": "2026-09-02T00:00:00Z", "created_to": "2026-09-01T00:00:00Z"})
    assert (r.status_code, r.json()["error"]["code"]) == (422, "VALIDATION_ERROR")


async def test_every_filter_together_on_the_real_database(real_client, world):
    t = tag()
    _sa, token = await sa_token(world)
    plan = await world.plan()
    keep = await make(world, plan, t, 0, status="PENDING", clan_name=f"Alpha {t}", created_at=T0)
    await make(world, plan, t, 1, status="APPROVED", clan_name=f"Alpha {t}", created_at=T0)
    await make(world, plan, t, 2, status="PENDING", clan_name=f"Beta {t}", created_at=T0)
    await make(world, plan, t, 3, status="PENDING", clan_name=f"Alpha {t}", created_at=T0 + timedelta(days=5))
    body = await listed(real_client, token, f"alpha {t}", status="PENDING", created_from="2026-09-01T00:00:00Z", created_to="2026-09-02T00:00:00Z")
    assert ids(body) == [str(keep.registration_id)] and body["total"] == 1


async def test_a_control_character_in_the_search_is_422_never_a_500(real_client, world):
    _sa, token = await sa_token(world)
    for q in ("%00", "a%00b", "a%07b", "a%0Ab", "a%09b", "%7F"):
        r = await real_client.get(f"{PREFIX}?q={q}", headers=bearer(token))
        assert (r.status_code, r.json()["error"]["code"]) == (422, "VALIDATION_ERROR"), q
        r = await real_client.get(f"/api/v1/admin/users?q={q}", headers=bearer(token))  # the same hole, closed on the user list
        assert (r.status_code, r.json()["error"]["code"]) == (422, "VALIDATION_ERROR"), q
    assert (await real_client.get("/api/v1/admin/users?q=", headers=bearer(token))).status_code == 200


# ------------------------------------------------------------------ detail


async def test_the_detail_shows_everything_the_list_hides_and_never_the_secrets(real_client, session, world):
    t = tag()
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await make(world, plan, t, name="Tran Thi Zed", phone="+84 912 345 678", origin_place="Zed Village")
    session.add_all([
        RegistrationStatusHistory(history_id=uuid.uuid4(), registration_id=reg.registration_id, from_status="PENDING",
                                  to_status="APPROVED", changed_by=sa.user_id, reason="note", changed_at=T0 + timedelta(hours=1)),
        RegistrationStatusHistory(history_id=uuid.uuid4(), registration_id=reg.registration_id, from_status=None,
                                  to_status="PENDING", changed_by=None, reason=None, changed_at=T0),
        RegistrationAttachment(attachment_id=uuid.uuid4(), registration_id=reg.registration_id, file_name="founding-act.pdf",
                               storage_key="itest/secret/storage/key", mime_type="application/pdf"),
    ])
    await session.flush()
    clan = await world.clan("PENDING")
    clan.registration_id = reg.registration_id
    await session.flush()
    r = await real_client.get(f"{PREFIX}/{reg.registration_id}", headers=bearer(token))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["representative_email"] == reg.representative_email and body["representative_phone"] == "+84 912 345 678"
    assert body["origin_place"] == "Zed Village" and body["requested_plan_code"] == plan.code
    assert body["clan_id"] == str(clan.clan_id)
    assert [(h["from_status"], h["to_status"]) for h in body["status_history"]] == [(None, "PENDING"), ("PENDING", "APPROVED")]
    assert body["status_history"][1]["changed_by"] == str(sa.user_id)
    [attachment] = body["attachments"]
    assert set(attachment) == {"attachment_id", "file_name", "mime_type", "uploaded_at"}
    assert "storage_key" not in r.text and "itest/secret" not in r.text
    assert reg.tracking_code_hash not in r.text and "tracking_code" not in r.text


async def test_an_unknown_registration_is_404_and_a_bad_id_is_422(real_client, world):
    _sa, token = await sa_token(world)
    r = await real_client.get(f"{PREFIX}/{uuid.uuid4()}", headers=bearer(token))
    assert (r.status_code, r.json()["error"]["code"]) == (404, "NOT_FOUND")
    r = await real_client.post(f"{PREFIX}/{uuid.uuid4()}/review", headers=bearer(token), json={"decision": "APPROVED"})
    assert (r.status_code, r.json()["error"]["code"]) == (404, "NOT_FOUND")
    r = await real_client.get(f"{PREFIX}/not-a-uuid", headers=bearer(token))
    assert (r.status_code, r.json()["error"]["code"]) == (422, "VALIDATION_ERROR")


# ------------------------------------------------------------------ review


async def review(client, token, registration_id, decision, reason=None):
    body = {"decision": decision}
    if reason is not None:
        body["reason"] = reason
    return await client.post(f"{PREFIX}/{registration_id}/review", headers=bearer(token), json=body)


async def test_approving_writes_the_registration_one_history_row_and_one_audit_row(real_client, session, world):
    t = tag()
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await make(world, plan, t, name="Tran Thi Zed", clan_name=f"Ho Tran {t}")
    registration_id, sa_id = reg.registration_id, sa.user_id
    r = await review(real_client, token, registration_id, "APPROVED", "Checked by phone, internal")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert set(body) == {"registration_id", "status", "reviewed_by", "reviewed_at", "reason_visible_to_applicant"}
    assert (body["status"], body["reviewed_by"], body["reason_visible_to_applicant"]) == ("APPROVED", str(sa_id), False)
    row = (await session.execute(select(BusinessRegistration).where(BusinessRegistration.registration_id == registration_id)
                                 .execution_options(populate_existing=True))).scalar_one()
    assert (row.status, row.reviewed_by, row.rejection_reason) == ("APPROVED", sa_id, None)
    assert row.reviewed_at is not None and row.updated_at == row.reviewed_at
    [history] = await history_of(session, registration_id)
    assert (history.from_status, history.to_status, history.changed_by, history.reason) == ("PENDING", "APPROVED", sa_id, "Checked by phone, internal")
    [audit] = await audit_of(session, registration_id)
    assert (audit.action, audit.entity_type, audit.actor_id, audit.clan_id) == ("registration.review", "business_registration", sa_id, None)
    assert audit.old_data == {"status": "PENDING"} and audit.reason is None
    assert set(audit.new_data) == {"status", "reason_length", "request_id"}
    assert audit.new_data["status"] == "APPROVED" and audit.new_data["reason_length"] == len("Checked by phone, internal")
    dump = repr((audit.old_data, audit.new_data, audit.reason))
    for secret in (reg.representative_email, "Tran Thi Zed", f"Ho Tran {t}", "Checked by phone", "@"):
        assert secret not in dump, secret


async def test_rejecting_stores_the_public_reason_and_the_audit_never_holds_it(real_client, session, world):
    t = tag()
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await make(world, plan, t)
    registration_id, sa_id = reg.registration_id, sa.user_id
    r = await review(real_client, token, registration_id, "REJECTED", REASON)
    assert r.status_code == 200 and r.json()["status"] == "REJECTED" and r.json()["reason_visible_to_applicant"] is True
    row = (await session.execute(select(BusinessRegistration).where(BusinessRegistration.registration_id == registration_id)
                                 .execution_options(populate_existing=True))).scalar_one()
    assert (row.status, row.rejection_reason, row.reviewed_by) == ("REJECTED", REASON, sa_id)
    [history] = await history_of(session, registration_id)
    assert (history.from_status, history.to_status, history.reason) == ("PENDING", "REJECTED", REASON)
    [audit] = await audit_of(session, registration_id)
    assert audit.reason is None and audit.new_data["reason_length"] == len(REASON)
    assert REASON not in repr((audit.old_data, audit.new_data)) and "founding" not in repr(audit.new_data)


async def test_a_multi_line_reason_round_trips_through_postgres(real_client, session, world):
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await make(world, plan, tag())
    registration_id = reg.registration_id
    r = await review(real_client, token, registration_id, "REJECTED", "  first line\r\n\tsecond line\nthird  ")
    assert r.status_code == 200
    row = (await session.execute(select(BusinessRegistration).where(BusinessRegistration.registration_id == registration_id)
                                 .execution_options(populate_existing=True))).scalar_one()
    assert row.rejection_reason == "first line\n\tsecond line\nthird"


async def test_a_bad_reason_is_422_and_nothing_is_written(real_client, session, world):
    _sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await make(world, plan, tag())
    registration_id = reg.registration_id
    for body in ({"decision": "REJECTED"}, {"decision": "REJECTED", "reason": "   "}, {"decision": "REJECTED", "reason": "a\x00b"},
                 {"decision": "APPROVED", "reason": "a\x00b"}, {"decision": "REJECTED", "reason": "x" * 2001}):
        r = await real_client.post(f"{PREFIX}/{registration_id}/review", headers=bearer(token), json=body)
        assert (r.status_code, r.json()["error"]["code"]) == (422, "VALIDATION_ERROR"), body
    assert (await session.get(BusinessRegistration, registration_id)).status == "PENDING"
    assert await history_of(session, registration_id) == [] and await audit_of(session, registration_id) == []


@pytest.mark.parametrize("current", ["APPROVED", "REJECTED", "DRAFT", "NEED_SUPPLEMENT", "CANCELLED"])
async def test_a_registration_that_is_not_pending_is_409_naming_its_status(real_client, session, world, current):
    _sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await make(world, plan, tag(), status=current)
    registration_id = reg.registration_id
    for decision in ("APPROVED", "REJECTED"):
        r = await review(real_client, token, registration_id, decision, REASON)
        assert (r.status_code, r.json()["error"]["code"]) == (409, "STATE_CONFLICT")
        assert current in r.json()["error"]["message"]
    assert (await session.get(BusinessRegistration, registration_id)).status == current
    assert await history_of(session, registration_id) == [] and await audit_of(session, registration_id) == []


async def test_both_decisions_are_final_on_the_real_database(real_client, session, world):
    _sa, token = await sa_token(world)
    plan = await world.plan()
    for first, second in (("APPROVED", "REJECTED"), ("REJECTED", "APPROVED"), ("APPROVED", "APPROVED"), ("REJECTED", "REJECTED")):
        reg = await make(world, plan, tag())
        registration_id = reg.registration_id
        assert (await review(real_client, token, registration_id, first, REASON)).status_code == 200
        again = await review(real_client, token, registration_id, second, "another")
        assert (again.status_code, again.json()["error"]["code"]) == (409, "STATE_CONFLICT") and first in again.json()["error"]["message"]
        assert len(await history_of(session, registration_id)) == 1 and len(await audit_of(session, registration_id)) == 1


@pytest.mark.parametrize("plan_status", ["INACTIVE", "RETIRED"])
async def test_approving_needs_an_active_plan_but_rejecting_does_not(real_client, session, world, plan_status):
    _sa, token = await sa_token(world)
    plan = await world.plan(plan_status)
    approve, reject = await make(world, plan, tag()), await make(world, plan, tag())
    approve_id, reject_id = approve.registration_id, reject.registration_id
    r = await review(real_client, token, approve_id, "APPROVED")
    assert (r.status_code, r.json()["error"]["code"]) == (409, "STATE_CONFLICT") and "plan" in r.json()["error"]["message"].lower()
    assert (await session.get(BusinessRegistration, approve_id)).status == "PENDING"
    assert await history_of(session, approve_id) == [] and await audit_of(session, approve_id) == []
    assert (await review(real_client, token, reject_id, "REJECTED", REASON)).status_code == 200
    assert (await session.get(BusinessRegistration, reject_id)).status == "REJECTED"


async def test_the_review_lock_statement_runs_on_postgres_and_rereads_the_row(session, world):
    plan = await world.plan()
    reg = await make(world, plan, tag())
    registration_id = reg.registration_id
    await session.execute(text("UPDATE business_registrations SET clan_name = 'changed under the session' WHERE registration_id = :i"),
                          {"i": registration_id})
    locked = await FamilyRepository(session).lock_registration(registration_id)
    assert locked is not None and locked.clan_name == "changed under the session"  # populate_existing re-read it
    assert await FamilyRepository(session).lock_registration(uuid.uuid4()) is None


async def test_the_reviewer_foreign_key_and_the_history_audit_foreign_keys_are_satisfied(real_client, session, world):
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await make(world, plan, tag())
    registration_id, sa_id = reg.registration_id, sa.user_id
    assert (await review(real_client, token, registration_id, "APPROVED")).status_code == 200
    await session.flush()
    joined = (await session.execute(text(
        "SELECT count(*) FROM business_registrations r JOIN users u ON u.user_id = r.reviewed_by "
        "JOIN registration_status_history h ON h.registration_id = r.registration_id AND h.changed_by = u.user_id "
        "JOIN audit_logs a ON a.entity_id = r.registration_id AND a.actor_id = u.user_id "
        "WHERE r.registration_id = :i"), {"i": registration_id})).scalar_one()
    assert joined == 1 and sa_id


# ------------------------------------------------------------------ end to end with the Guest endpoints


async def test_guest_registers_sa_rejects_and_the_guest_sees_the_reason_on_tracking(real_client, world):
    t = tag()
    _sa, token = await sa_token(world)
    plan = await world.plan()
    body = {"representative_name": "Tran Thi E2E", "representative_email": f"itest-{t}@example.test",
            "clan_name": f"E2E Clan {t}", "requested_plan_id": str(plan.plan_id)}
    created = await real_client.post("/api/v1/business-registrations", json=body)
    assert created.status_code == 201
    code, registration_id = created.json()["tracking_code"], created.json()["registration_id"]
    track = lambda: real_client.post("/api/v1/business-registrations/track", json={"tracking_code": code})  # noqa: E731
    assert (await track()).json()["public_reason"] is None and (await track()).json()["status"] == "PENDING"

    listed_body = await listed(real_client, token, t)
    assert ids(listed_body) == [registration_id] and listed_body["items"][0]["status"] == "PENDING"

    r = await review(real_client, token, registration_id, "REJECTED", REASON)
    assert r.status_code == 200
    tracked = (await track()).json()
    assert (tracked["status"], tracked["public_reason"]) == ("REJECTED", REASON)

    detail = (await real_client.get(f"{PREFIX}/{registration_id}", headers=bearer(token))).json()
    assert [(h["from_status"], h["to_status"]) for h in detail["status_history"]] == [(None, "PENDING"), ("PENDING", "REJECTED")]
    assert detail["rejection_reason"] == REASON and detail["representative_email"] == body["representative_email"]


async def test_an_approval_note_never_reaches_the_applicant(real_client, world):
    t = tag()
    _sa, token = await sa_token(world)
    plan = await world.plan()
    created = await real_client.post("/api/v1/business-registrations", json={
        "representative_name": "Tran Thi Note", "representative_email": f"itest-{t}@example.test",
        "clan_name": f"Note Clan {t}", "requested_plan_id": str(plan.plan_id)})
    code, registration_id = created.json()["tracking_code"], created.json()["registration_id"]
    note = "Internal: verified the founding act"
    assert (await review(real_client, token, registration_id, "APPROVED", note)).status_code == 200
    tracked = await real_client.post("/api/v1/business-registrations/track", json={"tracking_code": code})
    assert tracked.json()["status"] == "APPROVED" and tracked.json()["public_reason"] is None
    assert note not in tracked.text
    detail = (await real_client.get(f"{PREFIX}/{registration_id}", headers=bearer(token))).json()
    assert detail["status_history"][-1]["reason"] == note and detail["rejection_reason"] is None
