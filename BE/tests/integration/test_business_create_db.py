"""Create the Business of an APPROVED registration on the real PostgreSQL branch (Mốc E, E5).

Rolled back per test. The real routers and the real idempotency statements run on a real session.
Every test makes its OWN plan (ITEST-...), registrations and SA; the DEV-* plans are never read as
an expectation, changed or deleted.

Because the use case rolls back on any error (that is how a failed request leaves no key behind),
a test first COMMITS the rows its factory created: in this fixture a commit only releases a
SAVEPOINT, so the rows stay in the outer transaction that is rolled back at the end, and a rollback
inside the use case undoes only the request. After a rollback ORM objects are expired, so ids are
taken BEFORE the request.

What only a real PostgreSQL can prove: ON CONFLICT DO NOTHING on the unique key, the row lock and
re-read, set_config(..., true) as SET LOCAL, the real unique indexes of the clan (code and
registration), the savepoint that lets a generated code be drawn again after a collision, the
foreign keys and CHECK constraints, and that a request that dies half-way leaves nothing.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import app.controllers.family_management.business_admin_use_cases as use_cases
from app.core.dates import add_months
from app.core.idempotency import IDEMPOTENCY_TTL, compute_request_hash
from app.models.family.entities import (
    BusinessRegistration,
    Clan,
    ClanMembership,
    ClanOwnershipHistory,
    ClanProfile,
    ClanSubscription,
    IdempotencyKey,
    RegistrationStatusHistory,
)
from app.models.family.idempotency_repository import IdempotencyRepository
from app.models.family.repository import FamilyRepository
from app.models.user_access.entities import AuditLog, UserRole
from tests.integration.factory import bearer, build_full_app

PREFIX = "/api/v1/admin/business-registrations"
ENDPOINT = "POST /admin/business-registrations/{registration_id}/business"
PERSONAL = {"name": "Tran Thi Zed", "phone": "+84 912 345 678", "clan_name": "Ho Tran Zed", "origin_place": "Zed Village"}


def tag() -> str:
    return uuid.uuid4().hex[:10]


async def sa_token(world):
    sa = await world.user()
    await world.grant(sa, "SYSTEM_ADMIN")
    return sa, await world.session_for(sa)


async def approved(world, plan, *, status="APPROVED", **kw):
    t = tag()
    kw.setdefault("email", f"itest-bc-{t}@example.test")
    kw.setdefault("clan_name", f"{PERSONAL['clan_name']} {t}")
    return await world.registration(plan, status=status, **kw)


async def post(client, token, registration_id, *, key=None, body="__none__"):
    key = key or f"key-{uuid.uuid4().hex}"
    kwargs = {} if body == "__none__" else {"json": body}
    r = await client.post(f"{PREFIX}/{registration_id}/business", headers={**bearer(token), "Idempotency-Key": key}, **kwargs)
    r.sent_key = key
    return r


def code_of(r) -> str:
    return r.json()["error"]["code"]


async def counts(session, registration_id) -> dict:
    """What exists for one registration (read with expired objects refreshed)."""
    clan_ids = select(Clan.clan_id).where(Clan.registration_id == registration_id)

    async def n(model, *where):
        return (await session.execute(select(func.count()).select_from(model).where(*where))).scalar_one()

    return {
        "clans": await n(Clan, Clan.registration_id == registration_id),
        "profiles": await n(ClanProfile, ClanProfile.clan_id.in_(clan_ids)),
        "subscriptions": await n(ClanSubscription, ClanSubscription.clan_id.in_(clan_ids)),
        "audit": await n(AuditLog, AuditLog.clan_id.in_(clan_ids)),
        "history": await n(RegistrationStatusHistory, RegistrationStatusHistory.registration_id == registration_id),
    }


async def idem_rows(session, actor_id, key=None):
    stmt = select(IdempotencyKey).where(IdempotencyKey.actor_id == actor_id).execution_options(populate_existing=True)
    if key is not None:
        stmt = stmt.where(IdempotencyKey.idempotency_key == key)
    return list((await session.execute(stmt)).scalars().all())


# ------------------------------------------------------------------ who may call


async def test_only_a_system_admin_gets_in_on_the_real_database(real_client, session, world):
    plan = await world.plan()
    reg = await approved(world, plan)
    clan, owner = await world.business_owner()
    member = await world.user()
    await world.member(clan, member)
    plain = await world.user()
    scoped_sa = await world.user()
    await world.grant(scoped_sa, "SYSTEM_ADMIN", clan)
    await session.commit()
    registration_id = reg.registration_id
    for who in (owner, member, plain, scoped_sa):
        token = await world.session_for(who)
        for r in (
            await post(real_client, token, registration_id),
            await real_client.post(f"{PREFIX}/{registration_id}/business", headers=bearer(token)),  # no header: still 403
            await post(real_client, token, uuid.uuid4()),  # unknown id: no 404 for them
        ):
            assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")
    anonymous = await real_client.post(f"{PREFIX}/{registration_id}/business", headers={"Idempotency-Key": "key-0123456789"})
    assert anonymous.status_code == 401
    assert (await counts(session, registration_id)) == {"clans": 0, "profiles": 0, "subscriptions": 0, "audit": 0, "history": 0}


# ------------------------------------------------------------------ success: the rows


async def test_a_success_writes_the_clan_the_profile_the_subscription_the_audit_and_the_key(real_client, session, world):
    sa, token = await sa_token(world)
    plan = await world.plan()
    plan.billing_period_months = 6
    reg = await approved(world, plan, name=PERSONAL["name"], phone=PERSONAL["phone"], origin_place=PERSONAL["origin_place"])
    await session.commit()
    registration_id, plan_id, sa_id, email, clan_name = reg.registration_id, plan.plan_id, sa.user_id, reg.representative_email, reg.clan_name

    r = await post(real_client, token, registration_id, key="key-success-0001")
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store" and "idempotency-replayed" not in r.headers
    body = r.json()
    assert set(body) == {"clan_id", "clan_code", "clan_status", "subscription_id", "plan_id", "subscription_status", "starts_at", "ends_at"}
    assert re.fullmatch(r"CLAN-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{8}", body["clan_code"])
    assert (body["clan_status"], body["subscription_status"], body["plan_id"]) == ("PENDING", "PENDING", str(plan_id))

    clan = (await session.execute(select(Clan).where(Clan.registration_id == registration_id).execution_options(populate_existing=True))).scalar_one()
    assert (str(clan.clan_id), clan.clan_code, clan.status, clan.name, clan.created_by) == (body["clan_id"], body["clan_code"], "PENDING", clan_name, sa_id)
    assert clan.activated_at is None and clan.suspended_at is None
    profile = (await session.execute(select(ClanProfile).where(ClanProfile.clan_id == clan.clan_id))).scalar_one()
    assert profile.origin_place == PERSONAL["origin_place"]
    sub = (await session.execute(select(ClanSubscription).where(ClanSubscription.clan_id == clan.clan_id))).scalar_one()
    assert (str(sub.subscription_id), sub.plan_id, sub.status, sub.auto_renew) == (body["subscription_id"], plan_id, "PENDING", False)
    assert sub.ends_at > sub.starts_at and sub.ends_at == add_months(sub.starts_at, 6)  # the real CHECK holds, calendar months
    assert body["starts_at"].endswith("Z") and datetime.fromisoformat(body["ends_at"].replace("Z", "+00:00")) == sub.ends_at

    [row] = await idem_rows(session, sa_id, "key-success-0001")
    assert (row.endpoint, row.status, row.response_status, row.response_body, row.resource_type, str(row.resource_id)) == (
        ENDPOINT, "COMPLETED", 201, body, "clan", body["clan_id"])
    assert row.request_hash == compute_request_hash(method="POST", endpoint=ENDPOINT, path_params={"registration_id": registration_id}, body={})
    assert row.expires_at - row.created_at == IDEMPOTENCY_TTL

    [audit] = (await session.execute(select(AuditLog).where(AuditLog.clan_id == clan.clan_id))).scalars().all()
    assert (audit.actor_id, audit.action, audit.entity_type, audit.entity_id) == (sa_id, "business.create", "clan", clan.clan_id)
    assert audit.old_data is None and audit.reason is None
    assert audit.new_data == {"registration_id": str(registration_id), "plan_id": str(plan_id), "plan_code": plan.code,
                              "subscription_id": body["subscription_id"], "clan_status": "PENDING", "subscription_status": "PENDING",
                              "request_id": r.headers["X-Request-ID"]}
    dump = repr((audit.old_data, audit.new_data, audit.reason))
    for secret in (email, clan_name, PERSONAL["name"], PERSONAL["phone"], PERSONAL["origin_place"], body["clan_code"], "@"):
        assert secret not in dump, secret

    # the registration is untouched, and no Owner, membership or role was created
    registration = (await session.execute(select(BusinessRegistration).where(BusinessRegistration.registration_id == registration_id).execution_options(populate_existing=True))).scalar_one()
    assert registration.status == "APPROVED"
    assert (await counts(session, registration_id))["history"] == 0
    for model in (ClanOwnershipHistory, ClanMembership, UserRole):
        assert (await session.execute(select(func.count()).select_from(model).where(model.clan_id == clan.clan_id))).scalar_one() == 0


async def test_a_registration_without_a_place_of_origin_gets_an_empty_profile_value(real_client, session, world):
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await approved(world, plan, origin_place=None)
    await session.commit()
    registration_id = reg.registration_id
    assert (await post(real_client, token, registration_id)).status_code == 201
    profile = (await session.execute(select(ClanProfile).join(Clan, Clan.clan_id == ClanProfile.clan_id).where(Clan.registration_id == registration_id))).scalar_one()
    assert profile.origin_place is None


async def test_a_clan_code_given_by_the_sa_is_used_as_it_is(real_client, session, world):
    _sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await approved(world, plan)
    await session.commit()
    code = f"ITEST-{tag().upper()}"
    r = await post(real_client, token, reg.registration_id, body={"clan_code": code})
    assert r.status_code == 201 and r.json()["clan_code"] == code


# ------------------------------------------------------------------ the idempotency on the real database


async def test_the_same_key_and_request_replays_the_stored_response_and_writes_nothing_more(real_client, session, world):
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await approved(world, plan)
    await session.commit()
    registration_id, sa_id = reg.registration_id, sa.user_id
    wanted = {"clan_code": f"ITEST-{tag().upper()}"}
    first = await post(real_client, token, registration_id, key="key-replay-0001", body=wanted)
    assert first.status_code == 201
    state = await counts(session, registration_id)
    again = await post(real_client, token, registration_id, key="key-replay-0001", body=wanted)
    assert again.status_code == 201 and again.json() == first.json() and again.headers["idempotency-replayed"] == "true"
    assert await counts(session, registration_id) == state == {"clans": 1, "profiles": 1, "subscriptions": 1, "audit": 1, "history": 0}
    assert len(await idem_rows(session, sa_id)) == 1


async def test_absent_empty_and_null_bodies_are_the_same_request(real_client, session, world):
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await approved(world, plan)
    await session.commit()
    registration_id = reg.registration_id
    first = await post(real_client, token, registration_id, key="key-same-req-01")
    for body in ({}, {"clan_code": None}, None):
        again = await post(real_client, token, registration_id, key="key-same-req-01", body=body)
        assert again.status_code == 201 and again.json() == first.json() and again.headers["idempotency-replayed"] == "true"
    assert (await counts(session, registration_id))["clans"] == 1


async def test_the_same_key_with_a_different_request_is_409_and_changes_nothing(real_client, session, world):
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg, other = await approved(world, plan), await approved(world, plan)
    await session.commit()
    registration_id, other_id, sa_id = reg.registration_id, other.registration_id, sa.user_id
    first = await post(real_client, token, registration_id, key="key-conflict-001", body={"clan_code": f"ITEST-{tag().upper()}"})
    state = await counts(session, registration_id)
    for r in (
        await post(real_client, token, registration_id, key="key-conflict-001", body={"clan_code": f"ITEST-{tag().upper()}"}),
        await post(real_client, token, registration_id, key="key-conflict-001"),
        await post(real_client, token, other_id, key="key-conflict-001", body={"clan_code": first.json()["clan_code"]}),
    ):
        assert (r.status_code, code_of(r)) == (409, "IDEMPOTENCY_KEY_CONFLICT")
    assert await counts(session, registration_id) == state and (await counts(session, other_id))["clans"] == 0
    [row] = await idem_rows(session, sa_id)
    assert row.response_body == first.json()


async def test_a_key_belongs_to_one_caller(real_client, session, world):
    sa, token = await sa_token(world)
    sa2, token2 = await sa_token(world)
    plan = await world.plan()
    reg, other = await approved(world, plan), await approved(world, plan)
    await session.commit()
    registration_id, other_id, sa_id, sa2_id = reg.registration_id, other.registration_id, sa.user_id, sa2.user_id
    first = await post(real_client, token, registration_id, key="key-common-0001")
    same_request_other_caller = await post(real_client, token2, registration_id, key="key-common-0001")
    assert (same_request_other_caller.status_code, code_of(same_request_other_caller)) == (409, "DUPLICATE_RESOURCE")  # evaluated for real
    third = await post(real_client, token2, other_id, key="key-common-0001")
    assert third.status_code == 201 and third.json()["clan_id"] != first.json()["clan_id"]
    assert len(await idem_rows(session, sa_id)) == 1 and len(await idem_rows(session, sa2_id)) == 1


async def test_an_error_is_not_stored_so_a_retry_checks_again(real_client, session, world):
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await approved(world, plan, status="PENDING")
    await session.commit()
    registration_id, sa_id = reg.registration_id, sa.user_id
    first = await post(real_client, token, registration_id, key="key-retry-409-01")
    assert (first.status_code, code_of(first)) == (409, "STATE_CONFLICT") and await idem_rows(session, sa_id) == []
    await session.execute(text("UPDATE business_registrations SET status = 'APPROVED' WHERE registration_id = :i"), {"i": registration_id})
    await session.commit()
    again = await post(real_client, token, registration_id, key="key-retry-409-01")
    assert again.status_code == 201 and "idempotency-replayed" not in again.headers


async def test_an_expired_key_is_reused_in_place(real_client, session, world):
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await approved(world, plan)
    old_id = uuid.uuid4()
    session.add(IdempotencyKey(
        idempotency_id=old_id, actor_id=sa.user_id, endpoint=ENDPOINT, idempotency_key="key-expired-001", request_hash="f" * 64,
        status="COMPLETED", response_status=201, response_body={"stale": True}, resource_type="clan", resource_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc) - timedelta(days=8), expires_at=datetime.now(timezone.utc) - timedelta(days=1)))
    await session.commit()
    registration_id, sa_id = reg.registration_id, sa.user_id
    r = await post(real_client, token, registration_id, key="key-expired-001")  # another hash than the stale row: no conflict
    assert r.status_code == 201 and "idempotency-replayed" not in r.headers
    [row] = await idem_rows(session, sa_id)
    assert row.idempotency_id == old_id and row.response_body == r.json() and row.status == "COMPLETED"
    assert row.request_hash != "f" * 64 and row.expires_at > datetime.now(timezone.utc) + timedelta(days=6)


async def test_a_key_that_is_still_valid_is_never_reused_even_with_another_request(real_client, session, world):
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await approved(world, plan)
    session.add(IdempotencyKey(
        idempotency_id=uuid.uuid4(), actor_id=sa.user_id, endpoint=ENDPOINT, idempotency_key="key-valid-0001", request_hash="e" * 64,
        status="COMPLETED", response_status=201, response_body={"first": True}, created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    await session.commit()
    registration_id = reg.registration_id
    r = await post(real_client, token, registration_id, key="key-valid-0001")
    assert (r.status_code, code_of(r)) == (409, "IDEMPOTENCY_KEY_CONFLICT") and (await counts(session, registration_id))["clans"] == 0


# ------------------------------------------------------------------ the conditions


async def test_an_unknown_registration_is_404_and_leaves_no_key(real_client, session, world):
    sa, token = await sa_token(world)
    await session.commit()
    sa_id = sa.user_id
    r = await post(real_client, token, uuid.uuid4())
    assert (r.status_code, code_of(r)) == (404, "NOT_FOUND") and await idem_rows(session, sa_id) == []


@pytest.mark.parametrize("status", ["DRAFT", "PENDING", "NEED_SUPPLEMENT", "REJECTED", "CANCELLED"])
async def test_only_an_approved_registration_gets_a_business(real_client, session, world, status):
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await approved(world, plan, status=status)
    await session.commit()
    registration_id, sa_id = reg.registration_id, sa.user_id
    r = await post(real_client, token, registration_id)
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and status in r.json()["error"]["message"]
    assert (await counts(session, registration_id))["clans"] == 0 and await idem_rows(session, sa_id) == []


@pytest.mark.parametrize("plan_status", ["INACTIVE", "RETIRED"])
async def test_the_plan_must_still_be_active(real_client, session, world, plan_status):
    sa, token = await sa_token(world)
    plan = await world.plan(plan_status)
    reg = await approved(world, plan)
    await session.commit()
    registration_id, sa_id = reg.registration_id, sa.user_id
    r = await post(real_client, token, registration_id)
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and "plan" in r.json()["error"]["message"].lower()
    assert (await counts(session, registration_id))["clans"] == 0 and await idem_rows(session, sa_id) == []


async def test_a_registration_with_a_business_is_409_duplicate_resource_and_the_losers_key_is_not_kept(real_client, session, world):
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await approved(world, plan)
    await session.commit()
    registration_id, sa_id = reg.registration_id, sa.user_id
    assert (await post(real_client, token, registration_id, key="key-winner-0001")).status_code == 201
    loser = await post(real_client, token, registration_id, key="key-loser-00001")
    assert (loser.status_code, code_of(loser)) == (409, "DUPLICATE_RESOURCE")
    assert [r.idempotency_key for r in await idem_rows(session, sa_id)] == ["key-winner-0001"]
    assert (await counts(session, registration_id))["clans"] == 1


async def test_a_clan_code_that_is_taken_is_409_duplicate_resource(real_client, session, world):
    sa, token = await sa_token(world)
    plan = await world.plan()
    first, second = await approved(world, plan), await approved(world, plan)
    await session.commit()
    first_id, second_id = first.registration_id, second.registration_id
    code = f"ITEST-{tag().upper()}"
    assert (await post(real_client, token, first_id, body={"clan_code": code})).status_code == 201
    r = await post(real_client, token, second_id, body={"clan_code": code})
    assert (r.status_code, code_of(r)) == (409, "DUPLICATE_RESOURCE") and "code" in r.json()["error"]["message"].lower()
    assert (await counts(session, second_id))["clans"] == 0


async def test_the_plan_of_the_request_body_is_refused_and_the_registrations_plan_is_used(real_client, session, world):
    _sa, token = await sa_token(world)
    chosen, other = await world.plan(), await world.plan()
    reg = await approved(world, chosen)
    await session.commit()
    registration_id, chosen_id, other_id = reg.registration_id, chosen.plan_id, other.plan_id
    refused = await post(real_client, token, registration_id, body={"plan_id": str(other_id)})
    assert (refused.status_code, code_of(refused)) == (422, "VALIDATION_ERROR")
    ok = await post(real_client, token, registration_id)
    assert ok.status_code == 201 and ok.json()["plan_id"] == str(chosen_id) != str(other_id)


# ------------------------------------------------------------------ the unique indexes are the last line of defence


async def test_the_registration_index_stops_a_second_business_and_gives_the_same_409(session, world, monkeypatch):
    """The pre-check is blinded, so only clans_registration_id_key can answer (a lost race)."""
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await approved(world, plan)
    existing = await world.clan("PENDING")
    existing.registration_id = reg.registration_id
    await session.commit()
    registration_id, sa_id = reg.registration_id, sa.user_id

    async def blind(self, registration_id):
        return None

    monkeypatch.setattr(FamilyRepository, "get_clan_by_registration_id", blind)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_full_app(session)), base_url="http://test") as client:
        r = await post(client, token, registration_id)
    assert (r.status_code, code_of(r)) == (409, "DUPLICATE_RESOURCE") and "Business" in r.json()["error"]["message"]
    assert await idem_rows(session, sa_id) == []
    assert (await counts(session, registration_id))["clans"] == 1  # only the one that was already there


async def test_the_code_index_stops_a_taken_code_the_precheck_did_not_see_and_gives_the_same_409(session, world, monkeypatch):
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await approved(world, plan)
    taken = await world.clan("PENDING")
    code = f"ITEST-{tag().upper()}"
    taken.clan_code = code
    await session.commit()
    registration_id = reg.registration_id

    async def blind(self, clan_code):
        return None

    monkeypatch.setattr(FamilyRepository, "get_clan_by_code", blind)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_full_app(session)), base_url="http://test") as client:
        r = await post(client, token, registration_id, body={"clan_code": code})
    assert (r.status_code, code_of(r)) == (409, "DUPLICATE_RESOURCE")
    assert (await counts(session, registration_id))["clans"] == 0


async def test_a_generated_code_that_collides_is_drawn_again_inside_the_same_transaction(real_client, session, world, monkeypatch):
    """The savepoint is what makes this possible: after the unique violation the transaction is still usable."""
    _sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await approved(world, plan)
    taken = await world.clan("PENDING")
    taken.clan_code = f"CLAN-COLL{tag()[:4].upper()}"
    await session.commit()
    registration_id, taken_code = reg.registration_id, taken.clan_code
    fresh = f"CLAN-FRESH{tag()[:3].upper()}"
    draws = iter([taken_code, taken_code, fresh])
    monkeypatch.setattr(use_cases, "generate_clan_code", lambda: next(draws))
    r = await post(real_client, token, registration_id)
    assert r.status_code == 201 and r.json()["clan_code"] == fresh
    assert (await counts(session, registration_id)) == {"clans": 1, "profiles": 1, "subscriptions": 1, "audit": 1, "history": 0}


async def test_three_collisions_in_a_row_are_a_500_and_leave_nothing(real_client, session, world, monkeypatch):
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await approved(world, plan)
    taken = await world.clan("PENDING")
    taken.clan_code = f"CLAN-FULL{tag()[:4].upper()}"
    await session.commit()
    registration_id, taken_code, sa_id = reg.registration_id, taken.clan_code, sa.user_id
    monkeypatch.setattr(use_cases, "generate_clan_code", lambda: taken_code)
    r = await post(real_client, token, registration_id)
    assert (r.status_code, code_of(r)) == (500, "INTERNAL_ERROR")
    assert (await counts(session, registration_id))["clans"] == 0 and await idem_rows(session, sa_id) == []


async def test_any_other_database_error_is_not_a_409_it_rolls_everything_back_and_the_key_is_free(session, world, monkeypatch):
    """A REAL CHECK violation (clan_subscriptions_status_check) half-way through: nothing stays, the key works again."""
    sa, token = await sa_token(world)
    plan = await world.plan()
    reg = await approved(world, plan)
    await session.commit()
    registration_id, sa_id = reg.registration_id, sa.user_id
    original = FamilyRepository.create_subscription

    async def bad_status(self, **kw):
        return await original(self, **{**kw, "status": "BOGUS"})

    monkeypatch.setattr(FamilyRepository, "create_subscription", bad_status)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_full_app(session), raise_app_exceptions=False), base_url="http://test") as client:
        r = await post(client, token, registration_id, key="key-dies-halfway1")
    assert r.status_code == 500  # an unexpected IntegrityError is a bug: never mapped to a 409
    assert (await counts(session, registration_id)) == {"clans": 0, "profiles": 0, "subscriptions": 0, "audit": 0, "history": 0}
    assert await idem_rows(session, sa_id) == []  # no key left behind
    monkeypatch.setattr(FamilyRepository, "create_subscription", original)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_full_app(session)), base_url="http://test") as client:
        ok = await post(client, token, registration_id, key="key-dies-halfway1")  # the SAME key
    assert ok.status_code == 201 and "idempotency-replayed" not in ok.headers
    assert (await counts(session, registration_id))["clans"] == 1


# ------------------------------------------------------------------ the statements themselves, on PostgreSQL


async def test_the_claim_inserts_once_and_reports_an_existing_key_without_a_second_row(session, world):
    sa = await world.user()
    other = await world.user()
    await session.commit()
    repo = IdempotencyRepository(session)
    now = datetime.now(timezone.utc)
    args = dict(endpoint=ENDPOINT, idempotency_key="key-claim-0001", request_hash="a" * 64, created_at=now, expires_at=now + IDEMPOTENCY_TTL)
    first = await repo.insert_in_progress(actor_id=sa.user_id, **args)
    assert first is not None and first.status == "IN_PROGRESS"
    assert await repo.insert_in_progress(actor_id=sa.user_id, **args) is None  # ON CONFLICT DO NOTHING
    assert await repo.insert_in_progress(actor_id=other.user_id, **args) is not None  # another caller: its own row
    assert await repo.insert_in_progress(actor_id=sa.user_id, **{**args, "idempotency_key": "key-claim-0002"}) is not None
    assert await repo.insert_in_progress(actor_id=sa.user_id, **{**args, "endpoint": "POST /other"}) is not None
    assert len(await idem_rows(session, sa.user_id)) == 3


async def test_lock_existing_rereads_the_row_from_the_database(session, world):
    sa = await world.user()
    await session.commit()
    repo = IdempotencyRepository(session)
    now = datetime.now(timezone.utc)
    row = await repo.insert_in_progress(actor_id=sa.user_id, endpoint=ENDPOINT, idempotency_key="key-reread-001", request_hash="a" * 64, created_at=now, expires_at=now + IDEMPOTENCY_TTL)
    await session.execute(text("UPDATE idempotency_keys SET request_hash = :h WHERE idempotency_id = :i"), {"h": "b" * 64, "i": row.idempotency_id})
    locked = await repo.lock_existing(actor_id=sa.user_id, endpoint=ENDPOINT, idempotency_key="key-reread-001")
    assert locked is row and locked.request_hash == "b" * 64  # populate_existing: the session's copy was refreshed
    assert await repo.lock_existing(actor_id=sa.user_id, endpoint=ENDPOINT, idempotency_key="key-nothing-01") is None


async def test_the_database_enforces_the_key_and_hash_lengths_the_code_relies_on(session, world):
    sa = await world.user()
    await session.commit()
    repo = IdempotencyRepository(session)
    now = datetime.now(timezone.utc)
    from sqlalchemy.exc import IntegrityError

    for key, hash_ in (("short", "a" * 64), ("key-long-enough", "a" * 63)):
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await repo.insert_in_progress(actor_id=sa.user_id, endpoint=ENDPOINT, idempotency_key=key, request_hash=hash_, created_at=now, expires_at=now)


async def test_set_lock_timeout_is_local_to_the_transaction(engine):
    """SET LOCAL semantics on the real server: it holds inside the transaction and is gone after it."""
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await IdempotencyRepository(s).set_lock_timeout(10)
        assert (await s.execute(text("SHOW lock_timeout"))).scalar_one() == "10s"
        await s.commit()
        assert (await s.execute(text("SHOW lock_timeout"))).scalar_one() in ("0", "0ms")  # back to the default
        await s.rollback()
