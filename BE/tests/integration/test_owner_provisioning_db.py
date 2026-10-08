"""Create the Owner of a clan on the real PostgreSQL branch (Mốc E6a), with a FAKE Firebase.

Rolled back per test. The real routers and the real statements run on a real session; the identity
provider is a fake with fault injection (nothing here can reach the real Firebase, and tests/conftest.py
makes the SDK's Admin functions fail the test if anything tried). The e-mail sender is the Noop one.
Every test makes its OWN rows (clans, registrations, SA, ITEST plans); the DEV-* plans are never touched.

Because the use case rolls back on any error, a test first COMMITS the rows its factory created (in this
fixture a commit only releases a SAVEPOINT) and takes ids BEFORE the request: after a rollback the ORM
objects are expired.

What only a real PostgreSQL can prove: the CHECK constraints of provisioning_jobs on every transition,
the live-per-clan and live-per-e-mail unique indexes, the users e-mail index in any letter case, the
lock order, that NO transaction is open while the identity provider is called, that the password is in
no column of any table, and the end to end path Owner created -> restricted login -> expired password.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

import app.controllers.family_management.owner_provisioning_use_cases as use_cases
from app.core.email_sender import NoopEmailSender, get_email_sender
from app.core.firebase import ProviderInvalidUser, ProviderUnavailable, get_identity_provider
from app.models.family.entities import (
    Clan,
    ClanMembership,
    ClanOwnershipHistory,
    IdempotencyKey,
    ProvisioningJob,
)
from app.models.family.provisioning_repository import ProvisioningRepository
from app.models.family.repository import FamilyRepository
from app.models.user_access.entities import AuditLog, CredentialMetadata, LoginHistory, Role, User, UserRole
from tests.fakes import FakeIdentityProvider
from tests.integration.factory import bearer, build_full_app

ENDPOINT = "POST /admin/clans/{clan_id}/owner"
OWNER_NAME, OWNER_PHONE = "Tran Thi Owner", "+84 912 345 678"
KNOWN = "Kq7Wm2Xp9Tr4Vz8N"


def tag() -> str:
    return uuid.uuid4().hex[:10]


def owner_email() -> str:
    return f"Itest.Owner.{tag()}@Example.TEST"  # mixed case on purpose


@pytest_asyncio.fixture(loop_scope="session")
async def env(session, monkeypatch):
    """(client, fake provider): the real routers on the rolled-back session, with Firebase faked."""
    provider = FakeIdentityProvider()
    provider.probe = session.in_transaction  # True while the session holds a transaction (uncommitted work)
    app = build_full_app(session)
    app.dependency_overrides[get_identity_provider] = lambda: provider
    app.dependency_overrides[get_email_sender] = lambda: NoopEmailSender()
    monkeypatch.setattr(use_cases, "_default_password", lambda: KNOWN)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, provider


async def sa_token(world):
    sa = await world.user()
    await world.grant(sa, "SYSTEM_ADMIN")
    return sa, await world.session_for(sa)


async def make_clan(world, session, *, status="PENDING", email=None, registration=True):
    """A clan (and the APPROVED registration it came from). Committed, so a rollback inside the use case keeps it."""
    clan = await world.clan(status)
    email = email or owner_email()
    if registration:
        plan = await world.plan()
        reg = await world.registration(plan, status="APPROVED", email=email, name=OWNER_NAME, phone=OWNER_PHONE, clan_name=f"Itest Clan {tag()}")
        clan.registration_id = reg.registration_id
        clan.name = reg.clan_name
        await session.flush()
    await session.commit()
    return clan.clan_id, email


async def post(client, token, clan_id, *, key=None, body="__none__"):
    key = key or f"key-{uuid.uuid4().hex}"
    kwargs = {} if body == "__none__" else {"json": body}
    r = await client.post(f"/api/v1/admin/clans/{clan_id}/owner", headers={**bearer(token), "Idempotency-Key": key}, **kwargs)
    r.sent_key = key
    return r


def code_of(r) -> str:
    return r.json()["error"]["code"]


async def jobs_of(session, clan_id):
    stmt = select(ProvisioningJob).where(ProvisioningJob.clan_id == clan_id).execution_options(populate_existing=True)
    return list((await session.execute(stmt)).scalars().all())


async def user_by_email(session, email):
    stmt = select(User).where(func.lower(User.email) == email.lower()).execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one_or_none()


async def idem_rows(session, actor_id):
    stmt = select(IdempotencyKey).where(IdempotencyKey.actor_id == actor_id).execution_options(populate_existing=True)
    return list((await session.execute(stmt)).scalars().all())


async def audit_of_job(session, job_id):
    stmt = select(AuditLog).where(AuditLog.entity_id == job_id).order_by(AuditLog.occurred_at, AuditLog.log_id)
    return list((await session.execute(stmt)).scalars().all())


async def text_of_every_table(session, secrets: tuple[str, ...]) -> list[str]:
    """Which tables hold any of the strings in a text, varchar or jsonb column? (A password in a column is a leak.)"""
    found = []
    columns = (await session.execute(text(
        "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' "
        "AND data_type IN ('character varying', 'text', 'jsonb', 'json')"))).all()
    for table, column, _ in columns:
        for secret in secrets:
            n = (await session.execute(text(
                f'SELECT count(*) FROM "{table}" WHERE "{column}"::text LIKE :p'), {"p": f"%{secret}%"})).scalar_one()
            if n:
                found.append(f"{table}.{column}")
    return found


# ------------------------------------------------------------------ who may call


async def test_only_a_system_admin_gets_in_on_the_real_database(env, session, world):
    client, provider = env
    clan_id, _ = await make_clan(world, session)
    clan, owner = await world.business_owner()
    member = await world.user()
    await world.member(clan, member)
    plain = await world.user()
    scoped_sa = await world.user()
    await world.grant(scoped_sa, "SYSTEM_ADMIN", clan)
    await session.commit()
    job_id = uuid.uuid4()
    for who in (owner, member, plain, scoped_sa):
        token = await world.session_for(who)
        for r in (
            await post(client, token, clan_id),
            await client.post(f"/api/v1/admin/clans/{clan_id}/owner", headers=bearer(token)),  # no header: still 403
            await post(client, token, uuid.uuid4()),
            await client.get(f"/api/v1/admin/provisioning-jobs/{job_id}", headers=bearer(token)),
        ):
            assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")
    anonymous = await client.post(f"/api/v1/admin/clans/{clan_id}/owner", headers={"Idempotency-Key": "key-0123456789"})
    assert anonymous.status_code == 401
    assert await jobs_of(session, clan_id) == [] and provider.provider_calls == []


# ------------------------------------------------------------------ success: the rows


async def test_a_success_writes_the_owner_and_every_check_constraint_holds(env, session, world):
    client, provider = env
    sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    sa_id = sa.user_id
    await session.commit()
    r = await post(client, token, clan_id, key="key-owner-success-1")
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert (body["status"], body["owner_email"], body["owner_display_name"], body["temporary_password"]) == ("SUCCEEDED", email, OWNER_NAME, KNOWN)
    assert body["email_delivery_status"] is None

    [job] = await jobs_of(session, clan_id)
    assert (str(job.job_id), job.status, str(job.user_id), job.attempt_count) == (body["job_id"], "SUCCEEDED", body["user_id"], 1)
    assert (job.firebase_uid, job.firebase_user_created, job.needs_cleanup, job.lease_expires_at, job.error_code) == (
        f"own-{job.job_id}", True, False, None, None)
    assert (job.requested_by, job.email, job.display_name, job.phone) == (sa_id, email, OWNER_NAME, OWNER_PHONE)
    assert job.completed_at is not None

    user = await user_by_email(session, email)
    assert (str(user.user_id), user.email, user.status, user.first_login_required, user.firebase_uid, user.phone) == (
        body["user_id"], email, "PENDING", True, f"own-{job.job_id}", OWNER_PHONE)  # the e-mail keeps its letter case
    cred = (await session.execute(select(CredentialMetadata).where(CredentialMetadata.user_id == user.user_id).execution_options(populate_existing=True))).scalar_one()
    assert cred.must_change_password is True and cred.password_changed_at is None
    assert cred.temporary_password_expires_at - cred.temporary_password_issued_at == timedelta(hours=72)
    assert cred.auth_provider == "FIREBASE"
    membership = (await session.execute(select(ClanMembership).where(ClanMembership.user_id == user.user_id))).scalar_one()
    assert (membership.clan_id, membership.status) == (clan_id, "ACTIVE")
    role = (await session.execute(select(Role).join(UserRole, UserRole.role_id == Role.role_id).where(UserRole.user_id == user.user_id))).scalar_one()
    grant = (await session.execute(select(UserRole).where(UserRole.user_id == user.user_id))).scalar_one()
    assert (role.code, grant.clan_id, grant.granted_by, grant.revoked_at) == ("BUSINESS_OWNER", clan_id, sa_id, None)
    ownership = (await session.execute(select(ClanOwnershipHistory).where(ClanOwnershipHistory.clan_id == clan_id))).scalar_one()
    assert (ownership.user_id, ownership.ended_at) == (user.user_id, None)
    clan = (await session.execute(select(Clan).where(Clan.clan_id == clan_id).execution_options(populate_existing=True))).scalar_one()
    assert clan.status == "PENDING"  # only clan.activate (E7) makes it ACTIVE

    [key] = await idem_rows(session, sa_id)
    assert (key.endpoint, key.status, key.response_status, key.resource_type, key.resource_id) == (ENDPOINT, "COMPLETED", 201, "provisioning_job", job.job_id)
    assert key.response_body == {"job_id": body["job_id"], "status": "SUCCEEDED", "clan_id": str(clan_id), "user_id": body["user_id"]}

    events = [(a.new_data["event"], a.new_data["status"], (a.old_data or {}).get("status")) for a in await audit_of_job(session, job.job_id)]
    assert events == [("created", "PENDING", None), ("started", "RUNNING", "PENDING"), ("succeeded", "SUCCEEDED", "RUNNING")]
    for a in await audit_of_job(session, job.job_id):
        assert (a.actor_id, a.clan_id, a.entity_type, a.reason) == (sa_id, clan_id, "provisioning_job", None)
        dump = repr((a.old_data, a.new_data))
        for secret in (email, email.lower(), OWNER_NAME, OWNER_PHONE, KNOWN, job.firebase_uid, "@"):
            assert secret not in dump, secret

    fb = provider.provider_users[f"own-{job.job_id}"]
    assert (fb.email, fb.display_name) == (email, OWNER_NAME)
    assert [op for op, _ in provider.provider_calls] == ["get_user", "create_user"]


async def test_no_transaction_is_open_when_the_identity_provider_is_called(env, session, world):
    client, provider = env
    _sa, token = await sa_token(world)
    clan_id, _ = await make_clan(world, session)
    await session.commit()
    assert (await post(client, token, clan_id)).status_code == 201
    assert provider.open_transaction_calls == [] and len(provider.provider_calls) == 2


async def test_the_password_is_in_no_column_of_any_table(env, session, world):
    client, _provider = env
    _sa, token = await sa_token(world)
    clan_id, _ = await make_clan(world, session)
    await session.commit()
    r = await post(client, token, clan_id)
    assert r.json()["temporary_password"] == KNOWN
    assert await text_of_every_table(session, (KNOWN,)) == []


async def test_the_owner_can_be_read_as_a_job_without_personal_data(env, session, world):
    client, _provider = env
    _sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    await session.commit()
    ok = (await post(client, token, clan_id)).json()
    r = await client.get(f"/api/v1/admin/provisioning-jobs/{ok['job_id']}", headers=bearer(token))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert (body["status"], body["needs_cleanup"], body["attempt_count"], body["user_id"]) == ("SUCCEEDED", False, 1, ok["user_id"])
    for hidden in (email, email.lower(), OWNER_PHONE, OWNER_NAME, f"own-{ok['job_id']}", KNOWN):
        assert hidden not in r.text, hidden
    assert (await client.get(f"/api/v1/admin/provisioning-jobs/{uuid.uuid4()}", headers=bearer(token))).status_code == 404


async def test_a_clan_without_a_registration_takes_the_owner_from_the_body(env, session, world):
    client, _provider = env
    _sa, token = await sa_token(world)
    clan_id, _ = await make_clan(world, session, registration=False)
    await session.commit()
    refused = await post(client, token, clan_id)
    assert (refused.status_code, code_of(refused)) == (422, "VALIDATION_ERROR")
    email = owner_email()
    ok = await post(client, token, clan_id, body={"email": email, "display_name": "Body Owner"})
    assert ok.status_code == 201 and (ok.json()["owner_email"], ok.json()["owner_display_name"]) == (email, "Body Owner")


# ------------------------------------------------------------------ the idempotency on the real database


async def test_a_replay_answers_with_nulls_and_writes_nothing_more(env, session, world):
    client, provider = env
    sa, token = await sa_token(world)
    clan_id, _ = await make_clan(world, session)
    sa_id = sa.user_id
    await session.commit()
    first = (await post(client, token, clan_id, key="key-owner-replay-01")).json()
    provider.provider_calls.clear()
    again = await post(client, token, clan_id, key="key-owner-replay-01")
    assert again.status_code == 201 and again.headers["idempotency-replayed"] == "true"
    body = again.json()
    assert (body["job_id"], body["status"], body["user_id"]) == (first["job_id"], "SUCCEEDED", first["user_id"])
    assert all(body[k] is None for k in ("temporary_password", "temporary_password_expires_at", "owner_email", "owner_display_name"))
    assert KNOWN not in again.text and provider.provider_calls == []
    assert len(await jobs_of(session, clan_id)) == 1 and len(await idem_rows(session, sa_id)) == 1


async def test_the_same_key_with_a_different_request_is_a_conflict(env, session, world):
    client, _provider = env
    _sa, token = await sa_token(world)
    clan_id, _ = await make_clan(world, session)
    await session.commit()
    await post(client, token, clan_id, key="key-owner-conflict-1")
    r = await post(client, token, clan_id, key="key-owner-conflict-1", body={"email": owner_email()})
    assert (r.status_code, code_of(r)) == (409, "IDEMPOTENCY_KEY_CONFLICT")


async def test_a_run_that_died_leaves_the_key_in_progress_and_a_new_request_with_it_is_409_with_the_job_id(env, session, world):
    client, provider = env
    sa, token = await sa_token(world)
    clan_id, _ = await make_clan(world, session)
    sa_id = sa.user_id
    await session.commit()

    class Crash(BaseException):
        pass

    async def die(uid):
        raise Crash()

    provider.hooks["get_user"] = die
    with pytest.raises(Crash):
        await post(client, token, clan_id, key="key-owner-died-0001")
    provider.hooks.clear()
    [job] = await jobs_of(session, clan_id)
    assert (job.status, job.attempt_count) == ("RUNNING", 1) and job.lease_expires_at is not None  # the real CHECK: RUNNING needs a lease
    job_id = job.job_id
    [key] = await idem_rows(session, sa_id)
    assert (key.status, key.resource_id) == ("IN_PROGRESS", job_id)
    again = await post(client, token, clan_id, key="key-owner-died-0001")
    assert (again.status_code, code_of(again)) == (409, "STATE_CONFLICT")
    assert str(job_id) in again.json()["error"]["message"] and again.headers["retry-after"] == "5"
    other_key = await post(client, token, clan_id)
    assert (other_key.status_code, code_of(other_key)) == (409, "STATE_CONFLICT") and str(job_id) in other_key.json()["error"]["message"]
    assert len(await jobs_of(session, clan_id)) == 1


# ------------------------------------------------------------------ the checks


@pytest.mark.parametrize("status", ["ACTIVE", "SUSPENDED", "EXPIRED", "LOCKED", "INACTIVE"])
async def test_only_a_pending_clan_gets_an_owner(env, session, world, status):
    client, provider = env
    _sa, token = await sa_token(world)
    clan_id, _ = await make_clan(world, session, status=status)
    r = await post(client, token, clan_id)
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and status in r.json()["error"]["message"]
    assert await jobs_of(session, clan_id) == [] and provider.provider_calls == []


async def test_an_email_that_is_already_an_account_is_409_in_any_letter_case(env, session, world):
    client, provider = env
    _sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    existing = await world.user(email=email.upper())
    existing_id = existing.user_id
    await session.commit()
    r = await post(client, token, clan_id)
    assert (r.status_code, code_of(r)) == (409, "DUPLICATE_RESOURCE")
    assert await jobs_of(session, clan_id) == [] and provider.provider_calls == [] and existing_id


async def test_a_clan_with_an_owner_is_409(env, session, world):
    client, _provider = env
    _sa, token = await sa_token(world)
    clan_id, _ = await make_clan(world, session)
    other = await world.user()
    await world.owner(await session.get(Clan, clan_id), other)
    await session.commit()
    r = await post(client, token, clan_id)
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and "already has an Owner" in r.json()["error"]["message"]


async def test_a_pending_cleanup_blocks_the_clan_and_the_email_but_a_plain_failed_job_does_not(env, session, world):
    client, provider = env
    _sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    other_clan, _ = await make_clan(world, session)
    repo = ProvisioningRepository(session)
    owed_id = uuid.uuid4()
    owed = await repo.insert_pending(job_id=owed_id, clan_id=other_clan, requested_by=None, email=email.lower(), display_name="X", phone=None, now=datetime.now(timezone.utc))
    await repo.mark_running(owed, now=datetime.now(timezone.utc), lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=90))
    await repo.finish_failed_needing_cleanup(owed, error_code="PROVIDER_EMAIL_TAKEN", now=datetime.now(timezone.utc))  # the REAL CHECK accepts it
    await session.commit()
    r = await post(client, token, clan_id)
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and "clean-up" in r.json()["error"]["message"] and str(owed_id) in r.json()["error"]["message"]
    assert provider.provider_calls == []
    owed = await repo.lock(owed_id)
    await repo.finish_cleanup(owed, now=datetime.now(timezone.utc))
    await session.commit()
    ok = await post(client, token, clan_id)  # the cleanup is done: a FAILED job blocks nothing
    assert ok.status_code == 201


async def test_the_unique_indexes_are_the_last_line_of_defence(env, session, world, monkeypatch):
    client, _provider = env
    _sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    other_clan, _ = await make_clan(world, session)
    repo = ProvisioningRepository(session)
    live = await repo.insert_pending(job_id=uuid.uuid4(), clan_id=clan_id, requested_by=None, email="someone.else@example.test", display_name="X", phone=None, now=datetime.now(timezone.utc))
    live_id = live.job_id  # (taken now: a rollback inside a request expires the object)
    await session.commit()

    async def blind(self, *, clan_id, email):
        return []

    monkeypatch.setattr(ProvisioningRepository, "list_blocking", blind)  # the pre-check sees nothing
    r = await post(client, token, clan_id)
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT")  # uq_provisioning_job_live_per_clan
    r = await post(client, token, other_clan, body={"email": "someone.else@example.test"})
    assert (r.status_code, code_of(r)) == (409, "DUPLICATE_RESOURCE")  # uq_provisioning_job_live_email
    assert live_id


# ------------------------------------------------------------------ failures, on the real constraints


async def test_a_temporary_failure_leaves_a_retryable_job_and_frees_the_key(env, session, world):
    client, provider = env
    sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    sa_id = sa.user_id
    await session.commit()
    provider.faults["create_user"] = [ProviderUnavailable("timeout")]
    r = await post(client, token, clan_id, key="key-owner-503-00001")
    assert (r.status_code, code_of(r)) == (503, "PROVIDER_UNAVAILABLE")
    [job] = await jobs_of(session, clan_id)
    job_id = job.job_id  # (taken now: the next request rolls back and expires the object)
    assert (job.status, job.error_code, job.lease_expires_at, job.needs_cleanup, job.attempt_count) == ("FAILED_RETRYABLE", "PROVIDER_UNAVAILABLE", None, False, 1)
    assert await idem_rows(session, sa_id) == [] and await user_by_email(session, email) is None
    assert str(job_id) in r.json()["error"]["message"] and KNOWN not in r.text
    assert [a.new_data["event"] for a in await audit_of_job(session, job_id)] == ["created", "started", "failed_retryable"]
    blocked = await post(client, token, clan_id)  # the retryable job is live: a new one is refused
    assert (blocked.status_code, code_of(blocked)) == (409, "STATE_CONFLICT") and str(job_id) in blocked.json()["error"]["message"]


async def test_a_final_failure_flags_first_then_deletes_then_lowers_the_flags(env, session, world):
    client, provider = env
    _sa, token = await sa_token(world)
    clan_id, _ = await make_clan(world, session)
    await session.commit()
    seen = {}

    async def spy(uid):
        job = (await session.execute(select(ProvisioningJob).where(ProvisioningJob.clan_id == clan_id).execution_options(populate_existing=True))).scalar_one()
        seen.update(status=job.status, needs_cleanup=job.needs_cleanup, created=job.firebase_user_created, in_transaction=session.in_transaction())
        await session.rollback()  # (leave no transaction behind; this read was ours)

    provider.hooks["delete_user"] = spy
    provider.faults["create_user"] = [ProviderInvalidUser()]
    r = await post(client, token, clan_id)
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT")
    # the REAL CHECK (needs_cleanup only when FAILED and firebase_user_created) accepted the flags BEFORE the delete
    assert seen == {"status": "FAILED", "needs_cleanup": True, "created": True, "in_transaction": True}  # (our own read opened it)
    [job] = await jobs_of(session, clan_id)
    assert (job.status, job.error_code, job.needs_cleanup, job.firebase_user_created) == ("FAILED", "PROVIDER_REJECTED_USER", False, False)
    events = [a.new_data["event"] for a in await audit_of_job(session, job.job_id)]
    assert events == ["created", "started", "failed", "cleanup_done"]
    assert provider.provider_users == {} and ("delete_user", f"own-{job.job_id}") in provider.provider_calls


async def test_a_uid_mismatch_is_failed_never_deleted_and_blocks_nothing(env, session, world):
    from app.core.firebase import ProviderUser

    client, provider = env
    _sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    await session.commit()

    async def plant(uid):  # a user under our uid, with ANOTHER e-mail
        provider.provider_users[uid] = ProviderUser(uid=uid, email="not.the.owner@example.test", display_name="Someone Else", disabled=False)

    provider.hooks["get_user"] = plant
    r = await post(client, token, clan_id)
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT")
    [job] = await jobs_of(session, clan_id)
    job_id = job.job_id
    assert (job.status, job.error_code, job.needs_cleanup, job.firebase_user_created) == ("FAILED", "UID_MISMATCH", False, False)
    assert [op for op, _ in provider.provider_calls] == ["get_user"] and f"own-{job_id}" in provider.provider_users  # never deleted
    events = [(a.new_data["event"], a.new_data["error_code"], a.new_data["needs_cleanup"]) for a in await audit_of_job(session, job_id)]
    assert events == [("created", None, None), ("started", None, None), ("failed", "UID_MISMATCH", False)]
    for a in await audit_of_job(session, job_id):
        dump = repr((a.old_data, a.new_data, a.reason))
        assert "not.the.owner" not in dump and email.lower() not in dump.lower() and "@" not in dump
    provider.hooks.clear()
    again = await post(client, token, clan_id)  # the real indexes do not count a FAILED job without needs_cleanup
    assert again.status_code == 201 and again.json()["job_id"] != str(job_id)


async def test_after_a_failure_the_password_is_in_no_column_and_not_in_the_error(env, session, world):
    client, provider = env
    _sa, token = await sa_token(world)
    clan_id, _ = await make_clan(world, session)
    await session.commit()
    provider.faults["create_user"] = [ProviderInvalidUser()]
    provider.faults["delete_user"] = [ProviderUnavailable("timeout")]  # the job keeps its clean-up flags
    r = await post(client, token, clan_id)
    assert r.status_code == 409 and KNOWN not in r.text
    assert await text_of_every_table(session, (KNOWN,)) == []


async def test_a_failed_delete_keeps_the_flags_and_blocks_the_clan_on_the_real_indexes(env, session, world):
    client, provider = env
    _sa, token = await sa_token(world)
    clan_id, _ = await make_clan(world, session)
    await session.commit()
    provider.faults["create_user"] = [ProviderInvalidUser()]
    provider.faults["delete_user"] = [ProviderUnavailable("timeout")]
    r = await post(client, token, clan_id)
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT")
    [job] = await jobs_of(session, clan_id)
    job_id = job.job_id
    assert (job.status, job.needs_cleanup, job.firebase_user_created) == ("FAILED", True, True)
    events = [a.new_data["event"] for a in await audit_of_job(session, job_id)]
    assert events[-2:] == ["failed", "cleanup_failed"]
    blocked = await post(client, token, clan_id)
    assert (blocked.status_code, code_of(blocked)) == (409, "STATE_CONFLICT") and "clean-up" in blocked.json()["error"]["message"]
    body = (await client.get(f"/api/v1/admin/provisioning-jobs/{job_id}", headers=bearer(token))).json()
    assert (body["status"], body["needs_cleanup"], body["error_code"]) == ("FAILED", True, "PROVIDER_REJECTED_USER")


async def test_an_email_taken_between_the_checks_and_the_rows_is_found_by_the_real_index_and_compensated(env, session, world):
    client, provider = env
    _sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    await session.commit()

    async def race(uid):  # another account takes the e-mail (in another letter case) while Firebase is being called
        await world.user(email=email.upper())
        await session.commit()

    provider.hooks["create_user"] = race
    r = await post(client, token, clan_id)
    assert (r.status_code, code_of(r)) == (409, "DUPLICATE_RESOURCE")
    [job] = await jobs_of(session, clan_id)
    assert (job.status, job.error_code, job.needs_cleanup, job.firebase_user_created) == ("FAILED", "OWNER_EMAIL_EXISTS", False, False)
    assert provider.provider_users == {}
    assert (await session.execute(select(func.count()).select_from(ClanOwnershipHistory).where(ClanOwnershipHistory.clan_id == clan_id))).scalar_one() == 0


async def test_a_database_failure_while_writing_the_rows_rolls_them_all_back(env, session, world, monkeypatch):
    client, provider = env
    _sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    await session.commit()
    original = FamilyRepository.create_ownership

    async def broken(self, **kw):
        from sqlalchemy.exc import OperationalError

        raise OperationalError("INSERT", {}, Exception("simulated"))

    monkeypatch.setattr(FamilyRepository, "create_ownership", broken)
    r = await post(client, token, clan_id)
    assert (r.status_code, code_of(r)) == (503, "DATABASE_UNAVAILABLE")
    [job] = await jobs_of(session, clan_id)
    assert (job.status, job.error_code) == ("FAILED_RETRYABLE", "DATABASE_UNAVAILABLE")
    assert await user_by_email(session, email) is None  # the user, credential, membership and role were rolled back
    assert (await session.execute(select(func.count()).select_from(ClanMembership).where(ClanMembership.clan_id == clan_id))).scalar_one() == 0
    assert list(provider.provider_users) == [f"own-{job.job_id}"] and original


async def test_a_run_that_was_replaced_writes_nothing_and_deletes_nothing(env, session, world):
    client, provider = env
    _sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    await session.commit()

    async def taken_over(uid):  # another run claims the job while this one is in Firebase
        await session.execute(text("UPDATE provisioning_jobs SET attempt_count = attempt_count + 1 WHERE clan_id = :c"), {"c": clan_id})
        await session.commit()

    provider.hooks["create_user"] = taken_over
    r = await post(client, token, clan_id)
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and "replaced" in r.json()["error"]["message"]
    [job] = await jobs_of(session, clan_id)
    assert (job.status, job.attempt_count) == ("RUNNING", 2)
    assert await user_by_email(session, email) is None and "delete_user" not in [op for op, _ in provider.provider_calls]


async def test_fencing_ignores_the_lease_clock_on_the_real_database(env, session, world):
    client, provider = env
    _sa, token = await sa_token(world)
    clan_id, _ = await make_clan(world, session)
    await session.commit()

    async def lease_over(uid):  # the lease ran out, but nobody replaced the run
        await session.execute(text("UPDATE provisioning_jobs SET lease_expires_at = now() - interval '5 hours' WHERE clan_id = :c"), {"c": clan_id})
        await session.commit()

    provider.hooks["create_user"] = lease_over
    r = await post(client, token, clan_id)
    assert r.status_code == 201 and (await jobs_of(session, clan_id))[0].status == "SUCCEEDED"


# ------------------------------------------------------------------ item 6 on the Owner a job created


async def test_the_owner_a_job_created_is_restricted_and_the_expired_temporary_password_is_refused(env, session, world):
    client, provider = env
    _sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    await session.commit()
    ok = (await post(client, token, clan_id)).json()
    user_id, uid = uuid.UUID(ok["user_id"]), f"own-{ok['job_id']}"
    session_response = await client.post("/api/v1/auth/session", json={"id_token": provider.issue(uid)})
    assert session_response.status_code == 201
    created = session_response.json()
    assert created["requires_password_change"] is True and created["user"]["status"] == "PENDING" and created["user"]["user_id"] == ok["user_id"]
    me = await client.get("/api/v1/auth/me", headers=bearer(created["access_token"]))
    assert me.status_code == 200
    # 72 hours later
    await session.execute(text("UPDATE credential_metadata SET temporary_password_expires_at = now() - interval '1 second' WHERE user_id = :u"), {"u": user_id})
    await session.commit()
    expired = await client.post("/api/v1/auth/session", json={"id_token": provider.issue(uid)})
    assert (expired.status_code, code_of(expired)) == (403, "TEMPORARY_PASSWORD_EXPIRED")
    reasons = [row[0] for row in (await session.execute(select(LoginHistory.failure_reason).where(LoginHistory.user_id == user_id).order_by(LoginHistory.occurred_at))).all()]
    assert reasons[-1] == "TEMPORARY_PASSWORD_EXPIRED"
    still = await client.get("/api/v1/auth/me", headers=bearer(created["access_token"]))
    assert (still.status_code, code_of(still)) == (403, "TEMPORARY_PASSWORD_EXPIRED")  # the restricted session dies with it


async def test_no_log_line_carries_the_password_or_the_owner(env, session, world, caplog):
    client, _provider = env
    caplog.set_level(logging.DEBUG)
    _sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    await session.commit()
    assert (await post(client, token, clan_id)).status_code == 201
    logged = " | ".join(r.getMessage() for r in caplog.records if not r.name.startswith(("httpx", "httpcore", "sqlalchemy")))
    for secret in (KNOWN, email, email.lower(), OWNER_NAME, OWNER_PHONE):
        assert secret not in logged, secret
