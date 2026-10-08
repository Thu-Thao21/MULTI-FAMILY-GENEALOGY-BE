"""POST /admin/clans/{id}/activate and GET /admin/clans/{id} on the real PostgreSQL branch (Mốc E7), with a
FAKE Firebase (never the real one) where an Owner has to be provisioned. Rolled back per test, like the E6
files: every test makes its OWN rows; the DEV-* plans are never touched. A test COMMITS the rows its
factory made first (in this fixture a commit only releases a SAVEPOINT) and takes ids BEFORE the request.

What only a real PostgreSQL can prove here: the CHECK constraints of clans and clan_subscriptions on the
activation (ends_at > starts_at, the status lists), the real locks and statements, the audit row, that a
failure half-way rolls BOTH tables back, and the road of a real Owner: provisioned through the API,
first login with the temporary password, password change, and the clan working only once it is activated."""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text

import app.controllers.family_management.owner_provisioning_use_cases as owner_cases
from app.core.dates import add_months
from app.core.email_sender import NoopEmailSender, get_email_sender
from app.core.firebase import get_identity_provider
from app.models.family.entities import Clan, ClanSubscription
from app.models.family.repository import FamilyRepository
from app.models.user_access.entities import AuditLog, User
from tests.fakes import FakeIdentityProvider
from tests.integration.factory import bearer, build_full_app
from tests.integration.test_owner_provisioning_db import (
    OWNER_NAME,
    OWNER_PHONE,
    code_of,
    make_clan,
    post,
    sa_token,
    user_by_email,
)

PASSWORDS = [f"Kq7Wm2Xp9Tr4Vz8{c}" for c in "NPQRSTUVWXYZ"]


@pytest_asyncio.fixture(loop_scope="session")
async def env(session, monkeypatch):
    provider = FakeIdentityProvider()
    app = build_full_app(session)
    app.dependency_overrides[get_identity_provider] = lambda: provider
    app.dependency_overrides[get_email_sender] = lambda: NoopEmailSender()
    counter = itertools.count()
    monkeypatch.setattr(owner_cases, "_default_password", lambda: PASSWORDS[next(counter)])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, provider


async def activate(client, token, clan_id):
    return await client.post(f"/api/v1/admin/clans/{clan_id}/activate", headers=bearer(token))


async def read(client, token, clan_id):
    return await client.get(f"/api/v1/admin/clans/{clan_id}", headers=bearer(token))


async def clan_row(session, clan_id) -> Clan:
    return (await session.execute(select(Clan).where(Clan.clan_id == clan_id).execution_options(populate_existing=True))).scalar_one()


async def sub_row(session, sub_id) -> ClanSubscription:
    stmt = select(ClanSubscription).where(ClanSubscription.subscription_id == sub_id).execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one()


async def ready(world, session, *, owner_status="ACTIVE", months=12, plan_status="ACTIVE", clan_status="PENDING"):
    """A clan with an Owner (member, role, ownership) and one PENDING subscription. Returns plain ids."""
    clan = await world.clan(clan_status)
    plan = await world.plan(plan_status)
    plan.billing_period_months = months
    owner = await world.user(owner_status)
    await world.grant(owner, "BUSINESS_OWNER", clan)
    await world.owner(clan, owner)
    await world.member(clan, owner)
    sub = await world.subscription(clan, plan)
    out = dict(clan=clan.clan_id, owner=owner.user_id, sub=sub.subscription_id, plan=plan.plan_id, plan_code=plan.code)
    await session.commit()
    return out


async def snapshot(session, ids):
    clan, sub = await clan_row(session, ids["clan"]), await sub_row(session, ids["sub"])
    return (clan.status, clan.activated_at, clan.updated_at, sub.status, sub.starts_at, sub.ends_at)


async def audit_rows(session, clan_id):
    stmt = select(AuditLog).where(AuditLog.action == "clan.activate", AuditLog.clan_id == clan_id)
    return list((await session.execute(stmt)).scalars().all())


# ------------------------------------------------------------------ who may call


async def test_only_a_system_admin_gets_in_on_the_real_database(env, session, world):
    client, _provider = env
    ids = await ready(world, session)
    _clan, owner = await world.business_owner()
    plain = await world.user()
    scoped_sa = await world.user()
    await world.grant(scoped_sa, "SYSTEM_ADMIN", await clan_row(session, ids["clan"]))
    await session.commit()
    before = await snapshot(session, ids)
    for who in (owner, plain, scoped_sa):
        token = await world.session_for(who)
        for r in (await activate(client, token, ids["clan"]), await activate(client, token, "not-a-uuid"),
                  await read(client, token, ids["clan"]), await read(client, token, "not-a-uuid")):
            assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")
    assert (await client.post(f"/api/v1/admin/clans/{ids['clan']}/activate")).status_code == 401
    assert await snapshot(session, ids) == before


# ------------------------------------------------------------------ success


@pytest.mark.parametrize("months, owner_status", [(12, "ACTIVE"), (1, "PENDING"), (6, "ACTIVE")])
async def test_an_activation_writes_the_clan_the_subscription_and_one_audit_row_and_every_check_holds(env, session, world, months, owner_status):
    client, _provider = env
    sa, token = await sa_token(world)
    ids = await ready(world, session, months=months, owner_status=owner_status)
    sa_id = sa.user_id
    old = (await sub_row(session, ids["sub"]))
    old_dates = (old.starts_at, old.ends_at)
    t0 = datetime.now(timezone.utc)
    r = await activate(client, token, ids["clan"])
    t1 = datetime.now(timezone.utc)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store", r.text
    body = r.json()
    clan, sub = await clan_row(session, ids["clan"]), await sub_row(session, ids["sub"])
    assert (clan.status, body["status"], body["clan_id"]) == ("ACTIVE", "ACTIVE", str(ids["clan"]))
    assert t0 <= clan.activated_at <= t1 and clan.updated_at == clan.activated_at and clan.suspended_at is None
    assert (sub.status, str(sub.subscription_id), body["subscription_status"]) == ("ACTIVE", body["subscription_id"], "ACTIVE")
    assert sub.starts_at == clan.activated_at and sub.ends_at == add_months(sub.starts_at, months) and sub.ends_at > sub.starts_at
    assert (sub.starts_at, sub.ends_at) != old_dates and sub.plan_id == ids["plan"] and sub.auto_renew is False
    assert datetime.fromisoformat(body["activated_at"]) == clan.activated_at
    assert (datetime.fromisoformat(body["starts_at"]), datetime.fromisoformat(body["ends_at"])) == (sub.starts_at, sub.ends_at)
    [row] = await audit_rows(session, ids["clan"])
    assert (row.actor_id, row.entity_type, row.entity_id, row.reason) == (sa_id, "clan", ids["clan"], None)
    assert row.old_data == {"status": "PENDING", "subscription_status": "PENDING"}
    assert (row.new_data["plan_code"], row.new_data["owner_user_id"], row.new_data["subscription_id"]) == (
        ids["plan_code"], str(ids["owner"]), str(ids["sub"]))
    owner = (await session.execute(select(User).where(User.user_id == ids["owner"]).execution_options(populate_existing=True))).scalar_one()
    dump = repr((row.old_data, row.new_data, r.text))
    for hidden in (owner.email, owner.email.lower(), owner.display_name, owner.firebase_uid):
        assert hidden not in dump, hidden


async def test_a_second_activation_is_409_active_and_writes_nothing_more(env, session, world):
    client, _provider = env
    _sa, token = await sa_token(world)
    ids = await ready(world, session)
    first = await activate(client, token, ids["clan"])
    assert first.status_code == 200
    state = await snapshot(session, ids)
    again = await activate(client, token, ids["clan"])
    assert (again.status_code, code_of(again)) == (409, "STATE_CONFLICT") and "The clan is ACTIVE (activated at" in again.json()["error"]["message"]
    assert await snapshot(session, ids) == state and len(await audit_rows(session, ids["clan"])) == 1


# ------------------------------------------------------------------ the 409s


@pytest.mark.parametrize("status", ["SUSPENDED", "LOCKED", "EXPIRED", "INACTIVE"])
async def test_only_a_pending_clan_is_activated(env, session, world, status):
    client, _provider = env
    _sa, token = await sa_token(world)
    ids = await ready(world, session, clan_status=status)
    before = await snapshot(session, ids)
    r = await activate(client, token, ids["clan"])
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and f"The clan is {status}" in r.json()["error"]["message"]
    assert await snapshot(session, ids) == before and await audit_rows(session, ids["clan"]) == []


# (One scenario per test: after a 409 the use case rolls back and the ORM objects of the factory are expired, so a
# second scenario in the same test would touch them. A fresh test has a fresh world.)

OWNER_CASES = {
    "no Owner": ("DELETE FROM clan_ownership_history WHERE clan_id = :c", "no Owner"),
    "membership revoked": ("UPDATE clan_memberships SET revoked_at = now() WHERE clan_id = :c", "active member"),
    "membership not ACTIVE": ("UPDATE clan_memberships SET status = 'INVITED' WHERE clan_id = :c", "active member"),
    "role revoked": ("UPDATE user_roles SET revoked_at = now() WHERE user_id = :u AND clan_id = :c", "Business Owner role"),
    "account LOCKED": ("UPDATE users SET status = 'LOCKED' WHERE user_id = :u", "Owner account is LOCKED"),
    "account DISABLED": ("UPDATE users SET status = 'DISABLED' WHERE user_id = :u", "Owner account is DISABLED"),
    "account SUSPENDED": ("UPDATE users SET status = 'SUSPENDED' WHERE user_id = :u", "Owner account is SUSPENDED"),
}


@pytest.mark.parametrize("case", list(OWNER_CASES))
async def test_the_owner_conditions_on_the_real_database(env, session, world, case):
    client, _provider = env
    _sa, token = await sa_token(world)
    ids = await ready(world, session)
    statement, phrase = OWNER_CASES[case]
    await session.execute(text(statement), {"c": ids["clan"], "u": ids["owner"]})
    await session.commit()
    before = await snapshot(session, ids)
    r = await activate(client, token, ids["clan"])
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and phrase in r.json()["error"]["message"]
    assert await snapshot(session, ids) == before and await audit_rows(session, ids["clan"]) == []


async def test_a_subscription_that_is_missing_or_already_active_is_409(env, session, world):
    client, _provider = env
    _sa, token = await sa_token(world)
    ids = await ready(world, session)
    await session.execute(text("UPDATE clan_subscriptions SET status = 'ACTIVE' WHERE clan_id = :c"), {"c": ids["clan"]})
    await session.commit()
    r = await activate(client, token, ids["clan"])
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and "already has an ACTIVE subscription" in r.json()["error"]["message"]
    assert (await clan_row(session, ids["clan"])).status == "PENDING"


async def test_a_clan_without_any_subscription_is_409(env, session, world):
    client, _provider = env
    _sa, token = await sa_token(world)
    ids = await ready(world, session)
    await session.execute(text("DELETE FROM clan_subscriptions WHERE clan_id = :c"), {"c": ids["clan"]})
    await session.commit()
    r = await activate(client, token, ids["clan"])
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and "no PENDING subscription" in r.json()["error"]["message"]


async def test_two_pending_subscriptions_are_409_and_neither_is_activated(env, session, world):
    client, _provider = env
    _sa, token = await sa_token(world)
    ids = await ready(world, session)
    clan = await clan_row(session, ids["clan"])
    extra = await world.subscription(clan, await world.plan())
    extra_id = extra.subscription_id
    await session.commit()
    r = await activate(client, token, ids["clan"])
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and "more than one PENDING" in r.json()["error"]["message"]
    assert (await sub_row(session, ids["sub"])).status == "PENDING" and (await sub_row(session, extra_id)).status == "PENDING"


async def test_a_plan_that_is_no_longer_active_is_409_and_the_documented_way_out_works(env, session, world):
    client, _provider = env
    _sa, token = await sa_token(world)
    ids = await ready(world, session, plan_status="INACTIVE")
    before = await snapshot(session, ids)
    r = await activate(client, token, ids["clan"])
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and "plan of the subscription is no longer available" in r.json()["error"]["message"]
    assert await snapshot(session, ids) == before
    # the way out of the jam (KI-32), as an operator would do it: the plan is ACTIVE again, then the SA asks again
    await session.execute(text("UPDATE subscription_plans SET status = 'ACTIVE' WHERE plan_id = :p"), {"p": ids["plan"]})
    await session.commit()
    assert (await activate(client, token, ids["clan"])).status_code == 200


async def test_the_other_documented_way_out_changes_the_plan_of_the_pending_subscription(env, session, world):
    client, _provider = env
    _sa, token = await sa_token(world)
    ids = await ready(world, session, plan_status="INACTIVE")
    newer = await world.plan()
    newer.billing_period_months = 3
    newer_id = newer.plan_id
    await session.commit()
    assert (await activate(client, token, ids["clan"])).status_code == 409
    await session.execute(text("UPDATE clan_subscriptions SET plan_id = :p WHERE subscription_id = :s AND status = 'PENDING'"), {"p": newer_id, "s": ids["sub"]})
    await session.commit()
    assert (await activate(client, token, ids["clan"])).status_code == 200
    sub = await sub_row(session, ids["sub"])
    assert (sub.status, sub.plan_id) == ("ACTIVE", newer_id) and sub.ends_at == add_months(sub.starts_at, 3)  # the NEW plan's period


async def test_a_failure_half_way_rolls_both_tables_back(env, session, world, monkeypatch):
    client, _provider = env
    _sa, token = await sa_token(world)
    ids = await ready(world, session)
    before = await snapshot(session, ids)

    async def broken(self, subscription, **kw):
        from sqlalchemy.exc import OperationalError

        raise OperationalError("UPDATE", {}, Exception("simulated"))

    monkeypatch.setattr(FamilyRepository, "activate_subscription", broken)  # the clan was already written
    r = await activate(client, token, ids["clan"])
    assert (r.status_code, code_of(r)) == (503, "DATABASE_UNAVAILABLE")
    assert await snapshot(session, ids) == before and await audit_rows(session, ids["clan"]) == []


# ------------------------------------------------------------------ the road of a real Owner


async def sign_in(client, provider, user_row, *, just_now=False):
    auth_time = datetime.now(timezone.utc) if just_now else None
    return await client.post("/api/v1/auth/session", json={"id_token": provider.issue(user_row.firebase_uid, auth_time=auth_time)})


@pytest.mark.parametrize("activate_first", [False, True])
async def test_provision_first_login_password_change_and_the_clan_works_only_once_it_is_activated(env, session, world, activate_first):
    client, provider = env
    _sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    clan = await clan_row(session, clan_id)
    plan = await world.plan()
    sub = await world.subscription(clan, plan)
    sub_id = sub.subscription_id
    await session.commit()
    created = await post(client, token, clan_id)
    assert created.status_code == 201, created.text
    owner = await user_by_email(session, email)
    owner_id = owner.user_id
    assert (await clan_row(session, clan_id)).status == "PENDING" and owner.status == "PENDING"

    if activate_first:
        assert (await activate(client, token, clan_id)).status_code == 200

    first = await sign_in(client, provider, owner)  # a PENDING clan does not stop the sign-in
    assert first.status_code == 201 and first.json()["requires_password_change"] is True
    restricted = first.json()["access_token"]
    assert (await client.get(f"/api/v1/clans/{clan_id}/users", headers=bearer(restricted))).status_code == 403
    changed = await client.post("/api/v1/auth/change-password", headers=bearer(restricted),
                                json={"new_password": "A-brand-new-pass-1", "recent_id_token": provider.issue(owner.firebase_uid)})
    assert changed.status_code == 204
    full = await sign_in(client, provider, owner, just_now=True)
    assert full.status_code == 201 and full.json()["requires_password_change"] is False
    access = full.json()["access_token"]

    if not activate_first:
        me = (await client.get("/api/v1/auth/me", headers=bearer(access))).json()
        assert (me["memberships"][0]["clan_status"], me["memberships"][0]["permissions"]) == ("PENDING", [])
        denied = await client.get(f"/api/v1/clans/{clan_id}/users", headers=bearer(access))
        assert (denied.status_code, code_of(denied)) == (403, "FORBIDDEN")
        assert (await activate(client, token, clan_id)).status_code == 200

    me = (await client.get("/api/v1/auth/me", headers=bearer(access))).json()
    assert me["memberships"][0]["clan_status"] == "ACTIVE" and "clan.users.list" in me["memberships"][0]["permissions"]
    assert (await client.get(f"/api/v1/clans/{clan_id}/users", headers=bearer(access))).status_code == 200
    assert (await sub_row(session, sub_id)).status == "ACTIVE" and owner_id is not None


# ------------------------------------------------------------------ GET /admin/clans/{id}


async def test_the_clan_is_read_on_the_real_database_without_personal_data(env, session, world):
    client, _provider = env
    _sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    clan = await clan_row(session, clan_id)
    reg_id, name = clan.registration_id, clan.name
    plan = await world.plan()
    sub = await world.subscription(clan, plan)
    sub_id, plan_id, plan_code = sub.subscription_id, plan.plan_id, plan.code
    await session.commit()
    created = (await post(client, token, clan_id)).json()
    owner = await user_by_email(session, email)
    owner_id, uid = owner.user_id, owner.firebase_uid
    r = await read(client, token, clan_id)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert set(body) == {"clan_id", "clan_code", "status", "registration_id", "created_at", "activated_at", "subscription", "owner_user_id", "last_owner_job"}
    assert (body["status"], body["registration_id"], body["activated_at"], body["owner_user_id"]) == ("PENDING", str(reg_id), None, str(owner_id))
    assert body["subscription"]["subscription_id"] == str(sub_id) and body["subscription"]["plan_id"] == str(plan_id)
    assert body["subscription"]["plan_code"] == plan_code and body["subscription"]["status"] == "PENDING"
    assert body["last_owner_job"] == {"job_id": created["job_id"], "status": "SUCCEEDED", "needs_cleanup": False}
    for hidden in (email, email.lower(), OWNER_NAME, OWNER_PHONE, uid, name):
        assert hidden not in r.text, hidden
    assert (await activate(client, token, clan_id)).status_code == 200
    after = (await read(client, token, clan_id)).json()
    assert after["status"] == "ACTIVE" and after["activated_at"] and after["subscription"]["status"] == "ACTIVE"
    assert (await read(client, token, uuid.uuid4())).status_code == 404


async def test_the_latest_owner_job_of_a_clan_is_the_newest_one(env, session, world):
    client, _provider = env
    _sa, token = await sa_token(world)
    clan = await world.clan("PENDING")
    clan_id = clan.clan_id
    old = await world.job(clan, status="FAILED")
    new = await world.job(clan, status="FAILED_RETRYABLE", email=f"itest-newer-{uuid.uuid4().hex[:8]}@example.test")
    old_id, new_id = old.job_id, new.job_id
    await session.execute(text("UPDATE provisioning_jobs SET created_at = now() - interval '2 days' WHERE job_id = :j"), {"j": old_id})
    await session.commit()
    job = (await read(client, token, clan_id)).json()["last_owner_job"]
    assert job == {"job_id": str(new_id), "status": "FAILED_RETRYABLE", "needs_cleanup": False} and old_id != new_id
