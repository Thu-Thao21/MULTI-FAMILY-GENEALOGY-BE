"""Public registration and the service-plan catalog on the real PostgreSQL branch (Mốc E, E3).

Rolled back per test. The real routers run on a real session. Every test makes its OWN plans
(code ITEST-<tag>-...) and only ever looks at those: the DEV-* plans seeded on the dev branch
are neither read as expectations, nor modified, nor deleted. A test that lists or counts plans
filters by the prefix of its own plans.
"""

from __future__ import annotations

import hashlib
import unicodedata
import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select, text

from app.core.rate_limit import RateLimiters, SlidingWindowLimiter
from app.models.family.entities import (
    BusinessRegistration,
    PlanFeatureLimit,
    RegistrationStatusHistory,
)
from app.models.family.repository import FamilyRepository
from app.models.user_access.entities import AuditLog
from tests.guest_harness import FakeClock
from tests.integration.factory import build_full_app

PREFIX = "/api/v1"


def tag() -> str:
    return uuid.uuid4().hex[:10]


async def make_plan(world, session, name: str, *, price="0.00", status="ACTIVE", features=()):
    plan = await world.plan(status)
    plan.code = name
    plan.price = Decimal(price)
    for feature_code, enabled, limit in features:
        session.add(
            PlanFeatureLimit(
                plan_feature_id=uuid.uuid4(), plan_id=plan.plan_id, feature_code=feature_code,
                enabled=enabled, limit_value=None if limit is None else Decimal(limit), feature_metadata={},
            )
        )
    await session.flush()
    return plan


async def register(client, plan, **overrides):
    t = tag()
    body = {
        "representative_name": "Tran Thi Itest",
        "representative_email": f"itest-reg-{t}@example.test",
        "clan_name": f"Itest Clan {t}",
        "requested_plan_id": str(plan.plan_id),
    }
    body.update(overrides)
    return body, await client.post(f"{PREFIX}/business-registrations", json=body)


def code_of(response) -> str:
    return response.json()["error"]["code"]


async def registrations_of(session, email: str) -> list[BusinessRegistration]:
    rows = await session.execute(
        select(BusinessRegistration).where(BusinessRegistration.representative_email == email)
    )
    return list(rows.scalars().all())


async def all_listed(client, page_size: int = 100) -> list[dict]:
    items, page = [], 1
    while True:
        body = (await client.get(f"{PREFIX}/service-plans?page={page}&page_size={page_size}")).json()
        items += body["items"]
        if len(items) >= body["total"] or not body["items"]:
            return items
        page += 1


# ------------------------------------------------------------------ GET /service-plans


async def test_only_active_plans_are_listed_cheapest_first_with_their_features(real_client, session, world):
    t = tag()
    expensive = await make_plan(world, session, f"ITEST-{t}-B", price="500000.00",
                                features=[("TREE_VIEW_3D", True, None), ("MAX_PERSONS", True, 5000), ("AI", False, None)])
    cheap = await make_plan(world, session, f"ITEST-{t}-A", price="1.50")
    await make_plan(world, session, f"ITEST-{t}-X", price="0.10", status="INACTIVE")
    await make_plan(world, session, f"ITEST-{t}-Y", price="0.20", status="RETIRED")
    ours = [p for p in await all_listed(real_client) if p["code"].startswith(f"ITEST-{t}-")]
    assert [p["code"] for p in ours] == [f"ITEST-{t}-A", f"ITEST-{t}-B"]
    assert ours[0]["price"] == "1.50" and ours[1]["price"] == "500000.00"  # decimal strings
    assert ours[0]["features"] == []
    features = {f["feature_code"]: f for f in ours[1]["features"]}
    assert set(features) == {"TREE_VIEW_3D", "MAX_PERSONS", "AI"}
    assert features["MAX_PERSONS"]["limit_value"] == "5000" and features["AI"]["enabled"] is False
    assert {p["plan_id"] for p in ours} == {str(cheap.plan_id), str(expensive.plan_id)}
    for plan in ours:
        assert set(plan) == {"plan_id", "code", "name", "description", "price", "billing_period_months",
                             "max_members", "max_family_admins", "storage_mb", "features"}


async def test_paging_visits_every_active_plan_once_in_the_order_of_the_database(real_client, session, world):
    t = tag()
    for i, price in enumerate(("3.00", "1.00", "2.00")):
        await make_plan(world, session, f"ITEST-{t}-{i}", price=price)
    expected = [
        r[0] for r in (await session.execute(text(
            "SELECT code FROM subscription_plans WHERE status = 'ACTIVE' ORDER BY price ASC, code ASC"))).all()
    ]
    walked, total, page = [], None, 1
    while True:
        body = (await real_client.get(f"{PREFIX}/service-plans?page={page}&page_size=1")).json()
        total = body["total"]
        if not body["items"]:
            break
        assert len(body["items"]) == 1 and body["page"] == page and body["page_size"] == 1
        walked.append(body["items"][0]["code"])
        page += 1
    assert total == len(expected) and walked == expected  # none missed, none twice, same order as the SQL


async def test_a_page_beyond_the_end_is_empty_and_the_total_is_the_number_of_active_plans(real_client, session, world):
    await make_plan(world, session, f"ITEST-{tag()}-A")
    active = (await session.execute(text("SELECT count(*) FROM subscription_plans WHERE status = 'ACTIVE'"))).scalar_one()
    body = (await real_client.get(f"{PREFIX}/service-plans?page=9999&page_size=100")).json()
    assert body["items"] == [] and body["total"] == active


async def test_the_catalog_needs_no_account(real_client, session, world):
    await make_plan(world, session, f"ITEST-{tag()}-A")
    r = await real_client.get(f"{PREFIX}/service-plans", headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 200 and r.headers["x-request-id"]


# ------------------------------------------------------------------ POST /business-registrations


async def test_a_registration_is_stored_with_only_the_hash_of_the_code(real_client, session, world):
    plan = await make_plan(world, session, f"ITEST-{tag()}-A")
    body, r = await register(real_client, plan, representative_phone="+84 912 345 678", origin_place="Itest Village")
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    created = r.json()
    assert set(created) == {"registration_id", "tracking_code", "status", "created_at"}
    assert created["status"] == "PENDING" and created["created_at"].endswith("Z")
    [row] = await registrations_of(session, body["representative_email"])
    assert str(row.registration_id) == created["registration_id"] and row.status == "PENDING"
    assert row.tracking_code_hash == hashlib.sha256(created["tracking_code"].encode()).hexdigest()
    assert row.representative_phone == "+84 912 345 678" and row.origin_place == "Itest Village"
    assert row.requested_plan_id == plan.plan_id and row.reviewed_by is None and row.rejection_reason is None


async def test_the_status_history_and_the_audit_row_are_written_for_a_guest(real_client, session, world):
    plan = await make_plan(world, session, f"ITEST-{tag()}-A")
    _body, r = await register(real_client, plan)
    rid = uuid.UUID(r.json()["registration_id"])
    [history] = (await session.execute(
        select(RegistrationStatusHistory).where(RegistrationStatusHistory.registration_id == rid))).scalars().all()
    assert (history.from_status, history.to_status) == (None, "PENDING")
    assert history.changed_by is None and history.reason is None and history.changed_at is not None
    [audit] = (await session.execute(select(AuditLog).where(AuditLog.entity_id == rid))).scalars().all()
    assert audit.actor_id is None and audit.clan_id is None  # the schema allows a Guest audit row
    assert (audit.action, audit.entity_type) == ("registration.create", "business_registration")
    assert audit.old_data is None
    assert set(audit.new_data) == {"plan_id", "status", "request_id"}
    assert audit.new_data["plan_id"] == str(plan.plan_id) and audit.new_data["request_id"]
    assert audit.ip_address is not None and audit.reason is None


async def test_the_tracking_code_and_the_applicant_are_nowhere_in_what_is_stored_besides_their_own_columns(real_client, session, world):
    plan = await make_plan(world, session, f"ITEST-{tag()}-A")
    body, r = await register(real_client, plan)
    code, rid = r.json()["tracking_code"], uuid.UUID(r.json()["registration_id"])
    [row] = await registrations_of(session, body["representative_email"])
    stored = repr({c.name: getattr(row, c.name) for c in row.__table__.columns if c.name != "tracking_code_hash"})
    history = (await session.execute(select(RegistrationStatusHistory).where(
        RegistrationStatusHistory.registration_id == rid))).scalars().all()
    audit = (await session.execute(select(AuditLog).where(AuditLog.entity_id == rid))).scalars().all()
    elsewhere = stored + repr([(h.reason, h.from_status, h.to_status) for h in history]) + repr(
        [(a.old_data, a.new_data, a.reason, a.action) for a in audit])
    assert code not in elsewhere and row.tracking_code_hash not in elsewhere
    audit_text = repr([(a.old_data, a.new_data, a.reason) for a in audit])
    for personal in (body["representative_email"], body["representative_name"], body["clan_name"]):
        assert personal not in audit_text


async def test_the_email_keeps_its_case_and_the_text_is_cleaned_before_it_is_stored(real_client, session, world):
    plan = await make_plan(world, session, f"ITEST-{tag()}-A")
    t = tag()
    email = f"  Itest.Mixed-{t}@Example.TEST "
    nfd_name = unicodedata.normalize("NFD", "  Nguyễn   Thị  Itest ")
    _body, r = await register(real_client, plan, representative_email=email, representative_name=nfd_name,
                              clan_name=f"  Họ   Itest {t}  ")
    assert r.status_code == 201
    [row] = await registrations_of(session, f"Itest.Mixed-{t}@Example.TEST")
    assert row.representative_email == f"Itest.Mixed-{t}@Example.TEST"
    assert row.representative_name == unicodedata.normalize("NFC", "Nguyễn Thị Itest")
    assert row.clan_name == f"Họ Itest {t}"


@pytest.mark.parametrize("field, value", [
    ("representative_name", "bad\x00name"), ("clan_name", "bad\x00clan"), ("origin_place", "bad\x00place"),
    ("representative_email", "a\x00@example.test"), ("clan_name", "two\nlines"), ("representative_name", "bell\x07"),
])
async def test_a_nul_or_control_character_is_422_and_never_reaches_the_database(real_client, session, world, field, value):
    """The database driver raises on NUL: that used to be a 500 from a public endpoint."""
    plan = await make_plan(world, session, f"ITEST-{tag()}-A")
    before = (await session.execute(select(func.count()).select_from(BusinessRegistration))).scalar_one()
    _body, r = await register(real_client, plan, **{field: value})
    assert (r.status_code, code_of(r)) == (422, "VALIDATION_ERROR")
    after = (await session.execute(select(func.count()).select_from(BusinessRegistration))).scalar_one()
    assert after == before


async def test_an_unknown_and_an_inactive_plan_get_the_same_422_and_write_nothing(real_client, session, world):
    inactive = await make_plan(world, session, f"ITEST-{tag()}-OLD", status="INACTIVE")
    retired = await make_plan(world, session, f"ITEST-{tag()}-GONE", status="RETIRED")
    t = tag()
    email = f"itest-plan-{t}@example.test"
    base = {"representative_name": "Itest", "representative_email": email, "clan_name": f"Itest {t}"}
    answers = {}
    for label, plan_id in (("unknown", uuid.uuid4()), ("inactive", inactive.plan_id), ("retired", retired.plan_id)):
        answers[label] = await real_client.post(
            f"{PREFIX}/business-registrations", json={**base, "requested_plan_id": str(plan_id)})
    for label, r in answers.items():
        assert (r.status_code, code_of(r)) == (422, "VALIDATION_ERROR"), label
        assert r.json()["error"]["message"] == answers["unknown"].json()["error"]["message"], label
        assert "requested_plan_id" in r.json()["error"]["message"]
    assert await registrations_of(session, email) == []


# ------------------------------------------------------------------ duplicates (check and index)


async def test_a_pending_duplicate_is_409_whatever_the_case_even_for_vietnamese_letters(real_client, session, world):
    plan = await make_plan(world, session, f"ITEST-{tag()}-A")
    t = tag()
    first_body, first = await register(real_client, plan, representative_email=f"Itest.Dup-{t}@Example.TEST",
                                       clan_name=f"Họ Nguyễn Văn {t}")
    assert first.status_code == 201
    same, r = await register(real_client, plan, representative_email=f"ITEST.DUP-{t}@example.test",
                             clan_name=f"HỌ NGUYỄN VĂN {t}".upper())
    assert (r.status_code, code_of(r)) == (409, "DUPLICATE_RESOURCE")
    assert len(await registrations_of(session, first_body["representative_email"])) == 1
    assert await registrations_of(session, same["representative_email"]) == []


async def test_the_composed_and_the_decomposed_spelling_of_a_clan_name_are_the_same_applicant(real_client, session, world):
    plan = await make_plan(world, session, f"ITEST-{tag()}-A")
    t = tag()
    email = f"itest-nfc-{t}@example.test"
    composed = unicodedata.normalize("NFC", f"Họ Nguyễn {t}")
    _b, first = await register(real_client, plan, representative_email=email, clan_name=composed)
    assert first.status_code == 201
    _b, second = await register(real_client, plan, representative_email=email,
                                clan_name=unicodedata.normalize("NFD", f"Họ  Nguyễn {t}"))
    assert (second.status_code, code_of(second)) == (409, "DUPLICATE_RESOURCE")


async def test_the_unique_index_is_the_last_line_of_defence_and_gives_the_same_409(real_client, session, world, monkeypatch):
    plan = await make_plan(world, session, f"ITEST-{tag()}-A")
    plan_id = str(plan.plan_id)  # read it now: a rollback (the loser's) expires every ORM object
    body, first = await register(real_client, plan)
    assert first.status_code == 201
    by_check = await real_client.post(f"{PREFIX}/business-registrations", json=body)

    async def blind(self, *, email, clan_name):
        return False  # as in a race: the check saw nothing

    monkeypatch.setattr(FamilyRepository, "exists_pending_registration", blind)
    by_index = await real_client.post(f"{PREFIX}/business-registrations", json=body)
    assert by_check.status_code == by_index.status_code == 409
    assert code_of(by_check) == code_of(by_index) == "DUPLICATE_RESOURCE"
    assert by_check.json()["error"]["message"] == by_index.json()["error"]["message"]
    [row] = await registrations_of(session, body["representative_email"])  # still exactly one
    rows = (await session.execute(select(RegistrationStatusHistory).where(
        RegistrationStatusHistory.registration_id == row.registration_id))).scalars().all()
    assert len(rows) == 1  # the loser left no history, no audit
    audits = (await session.execute(select(AuditLog).where(AuditLog.action == "registration.create",
                                                           AuditLog.new_data["plan_id"].astext == plan_id))).scalars().all()
    assert len(audits) == 1


async def test_a_different_clan_name_or_a_different_email_is_not_a_duplicate(real_client, session, world):
    plan = await make_plan(world, session, f"ITEST-{tag()}-A")
    t = tag()
    email = f"itest-multi-{t}@example.test"
    for clan in (f"One {t}", f"Two {t}"):
        assert (await register(real_client, plan, representative_email=email, clan_name=clan))[1].status_code == 201
    assert (await register(real_client, plan, representative_email=f"itest-other-{t}@example.test",
                           clan_name=f"One {t}"))[1].status_code == 201


async def test_a_reviewed_registration_no_longer_blocks_a_new_one(real_client, session, world):
    plan = await make_plan(world, session, f"ITEST-{tag()}-A")
    body, first = await register(real_client, plan)
    await session.execute(text("UPDATE business_registrations SET status = 'REJECTED' WHERE registration_id = :i"),
                          {"i": uuid.UUID(first.json()["registration_id"])})
    _b, again = await register(real_client, plan, representative_email=body["representative_email"],
                               clan_name=body["clan_name"])
    assert again.status_code == 201
    assert len(await registrations_of(session, body["representative_email"])) == 2


# ------------------------------------------------------------------ POST /business-registrations/track


async def track(client, code):
    return await client.post(f"{PREFIX}/business-registrations/track", json={"tracking_code": code})


async def test_the_code_from_the_201_finds_the_registration_and_shows_only_the_public_fields(real_client, session, world):
    plan = await make_plan(world, session, f"ITEST-{tag()}-A")
    body, r = await register(real_client, plan)
    created = r.json()
    found = await track(real_client, created["tracking_code"])
    assert found.status_code == 200 and found.headers["cache-control"] == "no-store"
    data = found.json()
    assert set(data) == {"clan_name", "status", "public_reason", "submitted_at", "updated_at"}
    assert data["clan_name"] == body["clan_name"] and data["status"] == "PENDING" and data["public_reason"] is None
    [row] = await registrations_of(session, body["representative_email"])
    for secret in (row.tracking_code_hash, created["registration_id"], str(plan.plan_id), body["representative_email"],
                   body["representative_name"], "representative", "reviewed_by"):
        assert secret not in found.text, secret


async def test_a_wrong_code_is_404_and_the_code_is_matched_exactly(real_client, session, world):
    plan = await make_plan(world, session, f"ITEST-{tag()}-A")
    _b, r = await register(real_client, plan)
    code = r.json()["tracking_code"]
    for wrong in (code + " ", " " + code, code.upper(), code[:-1], "x", "a" * 500, "đại", "a\x00b", "a\nb"):
        got = await track(real_client, wrong)
        assert (got.status_code, code_of(got)) == (404, "NOT_FOUND"), repr(wrong)
    assert (await track(real_client, code)).status_code == 200


async def test_a_rejection_reason_is_public_only_for_a_rejected_registration(real_client, session, world):
    plan = await make_plan(world, session, f"ITEST-{tag()}-A")
    body, r = await register(real_client, plan)
    code, rid = r.json()["tracking_code"], uuid.UUID(r.json()["registration_id"])
    await session.execute(text("UPDATE business_registrations SET rejection_reason = 'Thiếu giấy tờ' WHERE registration_id = :i"), {"i": rid})
    assert (await track(real_client, code)).json()["public_reason"] is None  # still PENDING
    await session.execute(text("UPDATE business_registrations SET status = 'APPROVED' WHERE registration_id = :i"), {"i": rid})
    assert (await track(real_client, code)).json()["public_reason"] is None
    await session.execute(text("UPDATE business_registrations SET status = 'REJECTED' WHERE registration_id = :i"), {"i": rid})
    shown = (await track(real_client, code)).json()
    assert shown["status"] == "REJECTED" and shown["public_reason"] == "Thiếu giấy tờ"


async def test_tracking_writes_nothing(real_client, session, world):
    plan = await make_plan(world, session, f"ITEST-{tag()}-A")
    _b, r = await register(real_client, plan)
    before = (await session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    await track(real_client, r.json()["tracking_code"])
    await track(real_client, "wrong")
    assert (await session.execute(select(func.count()).select_from(AuditLog))).scalar_one() == before


# ------------------------------------------------------------------ the rate limiter on the real app


async def test_the_sixth_registration_in_the_hour_is_429_and_writes_nothing(session, world):
    clock = FakeClock()
    limiters = RateLimiters(
        enabled=True,
        registration=SlidingWindowLimiter(5, 3600, clock=clock),
        track=SlidingWindowLimiter(20, 600, clock=clock),
    )
    app = build_full_app(session, rate_limiters=limiters)
    plan = await make_plan(world, session, f"ITEST-{tag()}-A")
    t = tag()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("203.0.113.9", 4444)),
                                 base_url="http://test") as client:
        statuses = []
        for i in range(6):
            r = await client.post(f"{PREFIX}/business-registrations", json={
                "representative_name": "Itest", "representative_email": f"itest-rl-{t}-{i}@example.test",
                "clan_name": f"Itest RL {t} {i}", "requested_plan_id": str(plan.plan_id)})
            statuses.append(r.status_code)
        assert statuses == [201] * 5 + [429]
        assert r.headers["retry-after"] == "3600" and code_of(r) == "RATE_LIMITED"
        count = (await session.execute(select(func.count()).select_from(BusinessRegistration).where(
            BusinessRegistration.representative_email.like(f"itest-rl-{t}-%")))).scalar_one()
        assert count == 5
        clock.advance(3600)
        again = await client.post(f"{PREFIX}/business-registrations", json={
            "representative_name": "Itest", "representative_email": f"itest-rl-{t}-9@example.test",
            "clan_name": f"Itest RL {t} 9", "requested_plan_id": str(plan.plan_id)})
        assert again.status_code == 201
