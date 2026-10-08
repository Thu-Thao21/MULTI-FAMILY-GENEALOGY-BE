"""The four E6b routes on the real PostgreSQL branch, with a FAKE Firebase (never the real one).

Rolled back per test, like the E6a file: the real routers and the real statements on a real session;
the identity provider is a fake with fault injection and stop points; the e-mail sender is the Noop one.
Every test makes its OWN rows; the DEV-* plans are never touched. A test first COMMITS the rows its factory
made (here a commit only releases a SAVEPOINT) and takes ids BEFORE the request.

What only a real PostgreSQL can prove here: the CHECK constraints of provisioning_jobs on every transition a
retry and an abandon make, the live-per-clan and live-per-e-mail indexes holding a clan while a clean-up is
owed, the original Idempotency-Key found through the job, the credential_metadata row and the sessions the
reset writes, the list's real filters and paging, and that the passwords are in no column of any table."""

from __future__ import annotations

import itertools
import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text

import app.controllers.family_management.owner_provisioning_use_cases as use_cases
from app.core.email_sender import NoopEmailSender, get_email_sender
from app.core.firebase import ProviderUnavailable, ProviderUser, get_identity_provider
from app.core.idempotency import compute_request_hash
from app.models.family.entities import IdempotencyKey, ProvisioningJob
from app.models.user_access.entities import AuditLog, CredentialMetadata, User, UserSession
from tests.fakes import After, FakeIdentityProvider
from tests.integration.factory import bearer, build_full_app
from tests.integration.test_owner_provisioning_db import (
    ENDPOINT,
    OWNER_NAME,
    OWNER_PHONE,
    audit_of_job,
    code_of,
    idem_rows,
    jobs_of,
    make_clan,
    post,
    sa_token,
    text_of_every_table,
    user_by_email,
)

PASSWORDS = [f"Kq7Wm2Xp9Tr4Vz8{c}" for c in "NPQRSTUVWXYZ"]


@pytest_asyncio.fixture(loop_scope="session")
async def env(session, monkeypatch):
    """(client, fake provider). Every password the generator makes is different, in order."""
    provider = FakeIdentityProvider()
    provider.probe = session.in_transaction  # True while the session holds a transaction (uncommitted work)
    app = build_full_app(session)
    app.dependency_overrides[get_identity_provider] = lambda: provider
    app.dependency_overrides[get_email_sender] = lambda: NoopEmailSender()
    counter = itertools.count()
    monkeypatch.setattr(use_cases, "_default_password", lambda: PASSWORDS[next(counter)])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, provider


async def retry(client, token, job_id):
    return await client.post(f"/api/v1/admin/provisioning-jobs/{job_id}/retry", headers=bearer(token))


async def abandon(client, token, job_id):
    return await client.post(f"/api/v1/admin/provisioning-jobs/{job_id}/abandon", headers=bearer(token))


async def reset(client, token, clan_id):
    return await client.post(f"/api/v1/admin/clans/{clan_id}/owner/temporary-password", headers=bearer(token))


async def failed_once(client, provider, session, world, *, fault=ProviderUnavailable("timeout"), operation="create_user"):
    """An SA token, a clan and its job after a first run that failed temporarily (FAILED_RETRYABLE, attempt 1)."""
    sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    sa_id = sa.user_id
    await session.commit()
    provider.faults[operation] = [fault]
    r = await post(client, token, clan_id)
    assert r.status_code == 503, r.text
    [job] = await jobs_of(session, clan_id)
    return sa_id, token, clan_id, email, job.job_id


async def job_row(session, job_id) -> ProvisioningJob:
    stmt = select(ProvisioningJob).where(ProvisioningJob.job_id == job_id).execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one()


async def cred_of(session, user_id) -> CredentialMetadata:
    stmt = select(CredentialMetadata).where(CredentialMetadata.user_id == user_id).execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one()


async def sessions_of(session, user_id) -> list[UserSession]:
    stmt = select(UserSession).where(UserSession.user_id == user_id).execution_options(populate_existing=True)
    return list((await session.execute(stmt)).scalars().all())


# ------------------------------------------------------------------ who may call


async def test_only_a_system_admin_gets_in_on_the_e6b_routes(env, session, world):
    client, provider = env
    sa_id, _token, clan_id, _email, job_id = await failed_once(client, provider, session, world)
    clan, owner = await world.business_owner()
    plain = await world.user()
    scoped_sa = await world.user()
    await world.grant(scoped_sa, "SYSTEM_ADMIN", clan)
    await session.commit()
    calls = len(provider.provider_calls)
    for who in (owner, plain, scoped_sa):
        t = await world.session_for(who)
        for r in (await retry(client, t, job_id), await abandon(client, t, job_id), await reset(client, t, clan_id),
                  await retry(client, t, "not-a-uuid"), await client.get("/api/v1/admin/provisioning-jobs?page_size=9999", headers=bearer(t))):
            assert (r.status_code, code_of(r)) == (403, "FORBIDDEN")
    assert (await client.post(f"/api/v1/admin/provisioning-jobs/{job_id}/retry")).status_code == 401
    assert len(provider.provider_calls) == calls and (await job_row(session, job_id)).status == "FAILED_RETRYABLE"


# ------------------------------------------------------------------ the list


async def test_the_list_filters_and_pages_on_the_real_database_without_personal_data(env, session, world):
    client, _provider = env
    sa, token = await sa_token(world)
    clans = [await world.clan("PENDING") for _ in range(3)]
    jobs = [
        await world.job(clans[0], status="FAILED_RETRYABLE", email=f"Itest.List.{uuid.uuid4().hex[:8]}@Example.TEST"),
        await world.job(clans[1], status="FAILED_RETRYABLE", email=f"Itest.List.{uuid.uuid4().hex[:8]}@Example.TEST"),
        await world.job(clans[2], status="SUCCEEDED", email=f"Itest.List.{uuid.uuid4().hex[:8]}@Example.TEST"),
    ]
    ids = [j.job_id for j in jobs]
    clan_ids = [c.clan_id for c in clans]
    await session.commit()

    def mine(body):  # the dev branch may hold other jobs: look only at ours
        return [i for i in body["items"] if i["job_id"] in {str(x) for x in ids}]

    r = await client.get(f"/api/v1/admin/provisioning-jobs?clan_id={clan_ids[1]}", headers=bearer(token))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert (body["total"], [i["job_id"] for i in body["items"]]) == (1, [str(ids[1])])
    assert set(body["items"][0]) == {"job_id", "job_type", "clan_id", "status", "user_id", "email_delivery_status",
                                     "attempt_count", "needs_cleanup", "error_code", "created_at", "updated_at"}
    assert "itest.list" not in r.text.lower() and "own-" not in r.text
    both = (await client.get(f"/api/v1/admin/provisioning-jobs?clan_id={clan_ids[2]}&status=FAILED_RETRYABLE", headers=bearer(token))).json()
    assert both["total"] == 0 and both["items"] == []  # the filters are ANDed
    succeeded = (await client.get(f"/api/v1/admin/provisioning-jobs?clan_id={clan_ids[2]}&status=SUCCEEDED", headers=bearer(token))).json()
    assert succeeded["total"] == 1
    page = (await client.get("/api/v1/admin/provisioning-jobs?page_size=100", headers=bearer(token))).json()
    assert page["page_size"] == 100 and len(page["items"]) <= 100 and page["total"] >= 3
    created = [i["created_at"] for i in page["items"]]
    assert created == sorted(created, reverse=True)  # newest first
    assert (await client.get("/api/v1/admin/provisioning-jobs?page_size=101", headers=bearer(token))).status_code == 422
    assert len(mine(page)) <= 3  # (the dev branch may hold other jobs: only ours are looked at)


# ------------------------------------------------------------------ retry


async def test_a_retry_creates_the_owner_with_a_new_password_and_every_check_constraint_holds(env, session, world):
    client, provider = env
    sa_id, token, clan_id, email, job_id = await failed_once(client, provider, session, world)
    job = await job_row(session, job_id)
    assert (job.status, job.attempt_count, job.error_code, job.lease_expires_at) == ("FAILED_RETRYABLE", 1, "PROVIDER_UNAVAILABLE", None)
    assert await idem_rows(session, sa_id) == []  # the failure released the key
    other, other_token = await sa_token(world)
    other_id = other.user_id
    await session.commit()
    r = await retry(client, other_token, job_id)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store", r.text
    body = r.json()
    assert (body["status"], body["owner_email"], body["owner_display_name"], body["temporary_password"]) == ("SUCCEEDED", email, OWNER_NAME, PASSWORDS[1])
    job = await job_row(session, job_id)
    assert (job.status, job.attempt_count, str(job.user_id), job.needs_cleanup, job.lease_expires_at, job.error_code) == (
        "SUCCEEDED", 2, body["user_id"], False, None, None)
    user = await user_by_email(session, email)
    assert (str(user.user_id), user.status, user.first_login_required, user.firebase_uid, user.phone) == (
        body["user_id"], "PENDING", True, f"own-{job_id}", OWNER_PHONE)
    cred = await cred_of(session, user.user_id)
    assert cred.must_change_password is True and cred.temporary_password_expires_at - cred.temporary_password_issued_at == timedelta(hours=72)
    events = [(a.new_data["event"], a.actor_id) for a in await audit_of_job(session, job_id)]
    assert [e for e, _ in events] == ["created", "started", "failed_retryable", "retried", "succeeded"]
    assert dict(events)["retried"] == other_id  # the SA who retried
    assert provider.open_transaction_calls == []


async def test_a_retry_completes_the_original_key_that_a_dead_request_left_in_progress(env, session, world):
    client, provider = env
    sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    sa_id = sa.user_id
    # a request that died after its job started: RUNNING, the lease over, the key IN_PROGRESS on the job
    job_id = uuid.uuid4()
    session.add(ProvisioningJob(
        job_id=job_id, clan_id=clan_id, status="RUNNING", requested_by=sa_id, email=email, display_name=OWNER_NAME,
        firebase_uid=f"own-{job_id}", firebase_user_created=False, needs_cleanup=False, attempt_count=1,
        lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=5)))
    request_hash = compute_request_hash(method="POST", endpoint=ENDPOINT, path_params={"clan_id": clan_id}, body={})
    session.add(IdempotencyKey(
        idempotency_id=uuid.uuid4(), actor_id=sa_id, endpoint=ENDPOINT, idempotency_key="key-left-in-progress-1",
        request_hash=request_hash, status="IN_PROGRESS", resource_type="provisioning_job", resource_id=job_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7)))
    await session.commit()
    r = await retry(client, token, job_id)
    assert r.status_code == 200 and r.json()["status"] == "SUCCEEDED", r.text
    [key] = await idem_rows(session, sa_id)
    assert (key.status, key.response_status, key.resource_id) == ("COMPLETED", 201, job_id)
    assert set(key.response_body) == {"job_id", "status", "clan_id", "user_id"} and PASSWORDS[0] not in repr(key.response_body)
    replay = await post(client, token, clan_id, key="key-left-in-progress-1")
    assert replay.status_code == 201 and replay.headers["idempotency-replayed"] == "true"
    assert replay.json()["job_id"] == str(job_id) and replay.json()["temporary_password"] is None


async def test_a_retry_of_a_job_that_owes_a_cleanup_cleans_up_and_makes_no_password(env, session, world):
    client, provider = env
    sa, token = await sa_token(world)
    clan = await world.clan("PENDING")
    job = await world.job(clan, status="FAILED", needs_cleanup=True)
    job.attempt_count, job.error_code = 1, "PROVIDER_REJECTED_USER"
    job_id, clan_id, uid = job.job_id, clan.clan_id, job.firebase_uid
    provider.provider_users[uid] = ProviderUser(uid=uid, email="whoever@example.test", display_name="X", disabled=False)
    await session.commit()
    r = await retry(client, token, job_id)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "FAILED" and r.json()["temporary_password"] is None and r.json()["user_id"] is None
    assert [op for op, _ in provider.provider_calls] == ["delete_user"] and uid not in provider.provider_users
    job = await job_row(session, job_id)
    assert (job.status, job.needs_cleanup, job.firebase_user_created, job.attempt_count) == ("FAILED", False, False, 1)
    assert (await retry(client, token, job_id)).status_code == 409  # nothing left to do


@pytest.mark.parametrize("status, attempts, lease_seconds, retry_after", [
    ("SUCCEEDED", 1, None, False),
    ("RUNNING", 1, 60, True),
    ("FAILED", 5, None, False),
])
async def test_a_job_that_cannot_be_retried_is_409_naming_its_status_and_the_row_is_unchanged(env, session, world, status, attempts, lease_seconds, retry_after):
    client, provider = env
    sa, token = await sa_token(world)
    clan = await world.clan("PENDING")
    job = await world.job(clan, status=status, lease_expires_in=timedelta(seconds=lease_seconds) if lease_seconds else None)
    job.attempt_count = attempts
    job_id = job.job_id
    await session.commit()
    before = await job_row(session, job_id)
    snapshot = (before.status, before.attempt_count, before.updated_at, before.lease_expires_at)
    r = await retry(client, token, job_id)
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and f"is {status}" in r.json()["error"]["message"]
    assert ("retry-after" in r.headers) is retry_after
    after = await job_row(session, job_id)
    assert (after.status, after.attempt_count, after.updated_at, after.lease_expires_at) == snapshot and provider.provider_calls == []


# ------------------------------------------------------------------ abandon


async def test_abandon_flags_first_deletes_then_lowers_the_flags_and_frees_the_clan(env, session, world):
    client, provider = env
    sa_id, token, clan_id, email, job_id = await failed_once(client, provider, session, world, fault=After(ProviderUnavailable("timeout")))
    uid = f"own-{job_id}"
    assert uid in provider.provider_users
    seen = {}

    async def spy(u):
        row = (await session.execute(text("SELECT status, needs_cleanup, firebase_user_created, error_code FROM provisioning_jobs WHERE job_id = :j"), {"j": job_id})).one()
        seen.update(row=tuple(row))

    provider.hooks["delete_user"] = spy
    r = await abandon(client, token, job_id)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert seen["row"] == ("FAILED", True, True, "ABANDONED")  # written BEFORE the delete (the concurrency file proves: committed)
    body = r.json()
    assert (body["status"], body["error_code"], body["needs_cleanup"]) == ("FAILED", "ABANDONED", False)
    job = await job_row(session, job_id)
    assert (job.status, job.needs_cleanup, job.firebase_user_created, job.lease_expires_at) == ("FAILED", False, False, None)
    assert uid not in provider.provider_users
    assert [a.new_data["event"] for a in await audit_of_job(session, job_id)][-3:] == ["failed_retryable", "abandoned", "cleanup_done"]
    assert (await post(client, token, clan_id)).status_code == 201  # the clan is free again


async def test_a_failed_delete_after_an_abandon_holds_the_clan_and_the_email_on_the_real_indexes_until_a_retry_cleans_up(env, session, world):
    client, provider = env
    sa_id, token, clan_id, email, job_id = await failed_once(client, provider, session, world)
    provider.faults["delete_user"] = [ProviderUnavailable("timeout")]
    r = await abandon(client, token, job_id)
    assert r.status_code == 200 and r.json()["needs_cleanup"] is True
    job = await job_row(session, job_id)
    assert (job.status, job.needs_cleanup, job.firebase_user_created) == ("FAILED", True, True)
    blocked = await post(client, token, clan_id)
    assert (blocked.status_code, code_of(blocked)) == (409, "STATE_CONFLICT") and "clean-up" in blocked.json()["error"]["message"]
    other_clan, _ = await make_clan(world, session, email=email)  # the same e-mail on another clan is blocked too
    await session.commit()
    elsewhere = await post(client, token, other_clan)
    assert (elsewhere.status_code, code_of(elsewhere)) == (409, "STATE_CONFLICT")
    done = await retry(client, token, job_id)
    assert done.status_code == 200 and done.json()["temporary_password"] is None
    assert (await post(client, token, clan_id)).status_code == 201


async def test_abandon_refuses_a_running_job_with_a_live_lease_and_changes_nothing(env, session, world):
    client, provider = env
    sa, token = await sa_token(world)
    clan = await world.clan("PENDING")
    job = await world.job(clan, status="RUNNING", lease_expires_in=timedelta(seconds=60))
    job.attempt_count = 1
    job_id = job.job_id
    await session.commit()
    r = await abandon(client, token, job_id)
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and "is RUNNING" in r.json()["error"]["message"] and "retry-after" in r.headers
    after = await job_row(session, job_id)
    assert (after.status, after.attempt_count, after.needs_cleanup) == ("RUNNING", 1, False) and provider.provider_calls == []


async def test_abandon_takes_a_pending_job_nobody_ran_without_touching_firebase_and_releases_its_key(env, session, world):
    client, provider = env
    sa, token = await sa_token(world)
    clan = await world.clan("PENDING")
    job = await world.job(clan, status="PENDING")
    job_id, sa_id = job.job_id, sa.user_id
    await session.execute(text("UPDATE provisioning_jobs SET created_at = now() - interval '10 minutes' WHERE job_id = :j"), {"j": job_id})
    session.add(IdempotencyKey(
        idempotency_id=uuid.uuid4(), actor_id=sa_id, endpoint=ENDPOINT, idempotency_key="key-abandon-release-1", request_hash="a" * 64,
        status="IN_PROGRESS", resource_type="provisioning_job", resource_id=job_id, expires_at=datetime.now(timezone.utc) + timedelta(days=7)))
    await session.commit()
    r = await abandon(client, token, job_id)
    assert r.status_code == 200 and r.json()["needs_cleanup"] is False
    assert provider.provider_calls == [] and await idem_rows(session, sa_id) == []
    job = await job_row(session, job_id)
    assert (job.status, job.error_code, job.firebase_user_created, job.needs_cleanup) == ("FAILED", "ABANDONED", False, False)


# ------------------------------------------------------------------ reset


async def with_owner(client, provider, session, world):
    sa, token = await sa_token(world)
    clan_id, email = await make_clan(world, session)
    sa_id = sa.user_id
    await session.commit()
    created = await post(client, token, clan_id)
    assert created.status_code == 201, created.text
    user = await user_by_email(session, email)
    user_id, uid = user.user_id, user.firebase_uid
    sessions = [await world.session_for(user) for _ in range(2)]
    await session.commit()
    return sa_id, token, clan_id, email, user_id, uid, sessions


async def test_a_reset_writes_the_credential_revokes_every_session_and_audits_without_the_password(env, session, world):
    client, provider = env
    sa_id, token, clan_id, email, user_id, uid, _sessions = await with_owner(client, provider, session, world)
    before = await cred_of(session, user_id)
    issued_before = before.temporary_password_issued_at
    r = await reset(client, token, clan_id)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store", r.text
    body = r.json()
    assert (body["clan_id"], body["user_id"], body["owner_email"], body["temporary_password"]) == (str(clan_id), str(user_id), email, PASSWORDS[1])
    cred = await cred_of(session, user_id)
    assert cred.must_change_password is True and cred.password_changed_at is None
    assert cred.temporary_password_issued_at > issued_before
    assert cred.temporary_password_expires_at - cred.temporary_password_issued_at == timedelta(hours=72)
    rows = await sessions_of(session, user_id)
    assert len(rows) == 2 and all(s.revoked_at is not None and s.revoke_reason == "TEMPORARY_PASSWORD_RESET" for s in rows)
    user = await user_by_email(session, email)
    assert (user.status, user.first_login_required) == ("PENDING", True)
    audit = (await session.execute(select(AuditLog).where(AuditLog.action == "clan.owner.temp_password_reset", AuditLog.entity_id == user_id))).scalars().all()
    assert len(audit) == 1 and (audit[0].actor_id, audit[0].clan_id, audit[0].new_data["revoked_sessions"]) == (sa_id, clan_id, 2)
    assert PASSWORDS[1] not in repr((audit[0].old_data, audit[0].new_data))
    assert provider.provider_calls[-1] == ("set_owner_password", uid) and provider.password_changes == []
    assert provider.open_transaction_calls == []


async def test_after_a_reset_the_expired_owner_signs_in_again_and_the_old_session_is_dead(env, session, world):
    client, provider = env
    _sa, token, clan_id, _email, user_id, uid, _s = await with_owner(client, provider, session, world)
    ok = await client.post("/api/v1/auth/session", json={"id_token": provider.issue(uid)})
    assert ok.status_code == 201 and ok.json()["requires_password_change"] is True
    old = ok.json()["access_token"]
    await session.execute(text("UPDATE credential_metadata SET temporary_password_expires_at = now() - interval '1 second' WHERE user_id = :u"), {"u": user_id})
    await session.commit()
    expired = await client.post("/api/v1/auth/session", json={"id_token": provider.issue(uid)})
    assert (expired.status_code, code_of(expired)) == (403, "TEMPORARY_PASSWORD_EXPIRED")
    assert (await reset(client, token, clan_id)).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=bearer(old))).status_code == 401
    again = await client.post("/api/v1/auth/session", json={"id_token": provider.issue(uid)})
    assert again.status_code == 201 and again.json()["requires_password_change"] is True and again.json()["user"]["status"] == "PENDING"
    await session.execute(text("UPDATE credential_metadata SET temporary_password_expires_at = now() - interval '1 second' WHERE user_id = :u"), {"u": user_id})
    await session.commit()
    again_expired = await client.post("/api/v1/auth/session", json={"id_token": provider.issue(uid)})
    assert (again_expired.status_code, code_of(again_expired)) == (403, "TEMPORARY_PASSWORD_EXPIRED")


@pytest.mark.parametrize("status", ["ACTIVE", "LOCKED", "DISABLED"])
async def test_a_reset_for_an_owner_who_is_not_pending_is_409_and_writes_nothing(env, session, world, status):
    client, provider = env
    _sa, token, clan_id, _email, user_id, uid, _s = await with_owner(client, provider, session, world)
    await session.execute(text("UPDATE users SET status = :s WHERE user_id = :u"), {"s": status, "u": user_id})
    await session.commit()
    before = await cred_of(session, user_id)
    snapshot = (before.temporary_password_issued_at, before.updated_at)
    r = await reset(client, token, clan_id)
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and status in r.json()["error"]["message"]
    after = await cred_of(session, user_id)
    assert (after.temporary_password_issued_at, after.updated_at) == snapshot
    assert all(s.revoked_at is None for s in await sessions_of(session, user_id))
    assert ("set_owner_password", uid) not in provider.provider_calls


async def test_the_owner_changes_the_password_during_the_firebase_call_so_the_database_is_not_overwritten(env, session, world):
    client, provider = env
    _sa, token, clan_id, _email, user_id, uid, _s = await with_owner(client, provider, session, world)

    async def owner_changes_password(u):  # the Owner's own change-password commits while the reset is in Firebase
        await session.execute(text("UPDATE users SET status = 'ACTIVE', first_login_required = false WHERE user_id = :u"), {"u": user_id})
        await session.execute(text(
            "UPDATE credential_metadata SET must_change_password = false, temporary_password_issued_at = NULL, "
            "temporary_password_expires_at = NULL, password_changed_at = now(), updated_at = now() WHERE user_id = :u"), {"u": user_id})
        await session.commit()

    provider.hooks["set_owner_password"] = owner_changes_password
    r = await reset(client, token, clan_id)
    assert (r.status_code, code_of(r)) == (409, "STATE_CONFLICT") and "ACTIVE" in r.json()["error"]["message"]
    cred = await cred_of(session, user_id)
    assert (cred.must_change_password, cred.temporary_password_issued_at, cred.temporary_password_expires_at) == (False, None, None)
    assert all(s.revoked_at is None for s in await sessions_of(session, user_id))
    audit = (await session.execute(select(AuditLog).where(AuditLog.action == "clan.owner.temp_password_reset"))).scalars().all()
    assert audit == [] and PASSWORDS[1] not in r.text
    assert ("set_owner_password", uid) in provider.provider_calls  # the Firebase password WAS overwritten in the gap (KI-25)


async def test_a_reset_for_a_clan_without_an_owner_or_with_an_owner_not_made_by_a_job_is_409(env, session, world):
    client, provider = env
    sa, token = await sa_token(world)
    clan_id, _ = await make_clan(world, session)
    other_clan, owner = await world.business_owner()
    other_id = other_clan.clan_id
    await session.commit()
    none = await reset(client, token, clan_id)
    assert (none.status_code, code_of(none)) == (409, "STATE_CONFLICT") and "no Owner" in none.json()["error"]["message"]
    foreign = await reset(client, token, other_id)  # an Owner whose Firebase uid is not own-<uuid>
    assert foreign.status_code == 409
    assert provider.provider_calls == []
    assert (await reset(client, token, uuid.uuid4())).status_code == 404


# ------------------------------------------------------------------ the passwords are nowhere


async def test_the_passwords_of_a_retry_and_a_reset_are_in_no_column_of_any_table(env, session, world):
    client, provider = env
    sa_id, token, clan_id, email, job_id = await failed_once(client, provider, session, world, fault=After(ProviderUnavailable("timeout")))
    retried = await retry(client, token, job_id)
    assert retried.status_code == 200
    [owner_user] = [await user_by_email(session, email)]
    owner_id = owner_user.user_id
    reset_response = await reset(client, token, clan_id)
    assert reset_response.status_code == 200
    shown = {retried.json()["temporary_password"], reset_response.json()["temporary_password"]}
    assert len(shown) == 2
    leaks = await text_of_every_table(session, (*PASSWORDS[:3], *shown))
    assert leaks == [], leaks
    assert owner_id == uuid.UUID(retried.json()["user_id"])


async def test_after_a_failed_retry_the_password_is_in_no_column_and_not_in_the_error(env, session, world):
    client, provider = env
    sa_id, token, clan_id, email, job_id = await failed_once(client, provider, session, world)
    provider.faults["create_user"] = [ProviderUnavailable("timeout")]
    r = await retry(client, token, job_id)
    assert r.status_code == 503
    for secret in PASSWORDS[:3]:
        assert secret not in r.text
    assert await text_of_every_table(session, PASSWORDS[:3]) == []
    job = await job_row(session, job_id)
    assert (job.status, job.attempt_count) == ("FAILED_RETRYABLE", 2)


async def test_no_e6b_log_line_carries_the_password_or_the_owner(env, session, world, caplog):
    client, provider = env
    caplog.set_level(logging.DEBUG)
    sa_id, token, clan_id, email, job_id = await failed_once(client, provider, session, world)
    assert (await retry(client, token, job_id)).status_code == 200
    assert (await reset(client, token, clan_id)).status_code == 200
    logged = " | ".join(r.getMessage() for r in caplog.records if not r.name.startswith(("httpx", "httpcore", "sqlalchemy")))
    for secret in (*PASSWORDS[:3], email, email.lower(), OWNER_NAME, OWNER_PHONE):
        assert secret not in logged, secret
