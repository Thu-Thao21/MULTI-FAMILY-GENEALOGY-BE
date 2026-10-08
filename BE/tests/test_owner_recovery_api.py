"""The four E6b routes over HTTP: GET /admin/provisioning-jobs, POST /admin/provisioning-jobs/{id}/retry,
POST /admin/provisioning-jobs/{id}/abandon and POST /admin/clans/{id}/owner/temporary-password.

Same harness as the E6a tests: the real routers and the real authorization on fake repositories, a fake
Firebase (never the real one) with fault injection and stop points, and a unit of work that really rolls back.
What is proven: which states a retry and an abandon accept (and that every other state is a 409 naming the
current one), a new password on every successful retry, the original Idempotency-Key completed or released
through the job, the order Firebase -> database for the reset, no transaction held across a Firebase call,
the gap where the Owner changes the password meanwhile, sessions revoked, and above all: no password in any
row, log, audit entry or error."""

from __future__ import annotations

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import app.controllers.family_management.owner_provisioning_use_cases as use_cases
from app.core.config import settings
from app.core.firebase import (
    PasswordRejected,
    ProviderInvalidUser,
    ProviderUnavailable,
    ProviderUser,
)
from tests.fakes import After, make_user
from tests.test_owner_provisioning_api import (
    FROZEN,
    OWNER_EMAIL,
    OWNER_NAME,
    OWNER_PHONE,
    Crash,
    OwnerWorld,
    app_logs,
    code,
    everything_stored,
    seed_job,
)

PASSWORDS = [f"Kq7Wm2Xp9Tr4Vz8{c}" for c in "NPQRSTUVWXYZ"]  # one per password the generator is asked for
LEASE = timedelta(seconds=settings.PROVISIONING_LEASE_SECONDS)


class World(OwnerWorld):
    def __init__(self, **kw) -> None:
        super().__init__(raise_server_exceptions=False, **kw)
        self.repo.calls = self.family.calls  # ONE list: the order of locks across the repositories

    @staticmethod
    def _headers(token):
        return {"Authorization": f"Bearer {token}"}

    def retry(self, token, job_id):
        self.tx.begin()
        return self.client.post(f"/api/v1/admin/provisioning-jobs/{job_id}/retry", headers=self._headers(token))

    def abandon(self, token, job_id):
        self.tx.begin()
        return self.client.post(f"/api/v1/admin/provisioning-jobs/{job_id}/abandon", headers=self._headers(token))

    def reset(self, token, clan_id):
        self.tx.begin()
        return self.client.post(f"/api/v1/admin/clans/{clan_id}/owner/temporary-password", headers=self._headers(token))

    def listing(self, token, query=""):
        return self.client.get(f"/api/v1/admin/provisioning-jobs{query}", headers=self._headers(token))

    def job_of(self, job_id):
        return self.jobs.jobs[uuid.UUID(str(job_id))]

    def events(self):
        return [a["new_data"].get("event") for a in self.repo.audit if a["action"] == "provisioning_job.transition"]


@pytest.fixture
def clock():
    return [FROZEN]


@pytest.fixture
def passwords():
    return itertools.count()


@pytest.fixture
def w(monkeypatch, clock, passwords) -> World:
    monkeypatch.setattr(use_cases, "utcnow", lambda: clock[0])
    monkeypatch.setattr(use_cases, "_default_password", lambda: PASSWORDS[next(passwords)])
    return World()


def retryable(w: World, *, fault=ProviderUnavailable("timeout"), operation="create_user"):
    """A clan, an SA and a job that failed once with a temporary failure (FAILED_RETRYABLE, attempt 1)."""
    sa, token = w.sa()
    clan, _ = w.clan()
    w.provider.faults[operation] = [fault]
    r = w.post(token, clan.clan_id)
    assert r.status_code == 503, r.text
    job = w.job()
    assert (job.status, job.attempt_count, job.error_code) == ("FAILED_RETRYABLE", 1, "PROVIDER_UNAVAILABLE")
    assert w.idem.rows == []  # the key was released
    return sa, token, clan, job


def second_sa(w: World):
    sa, token = w.sa()
    return sa, token


# ------------------------------------------------------------------ who may call


def test_nobody_but_a_system_admin_reaches_any_of_the_four_routes(w):
    sa, sa_token, clan, job = retryable(w)
    outsider = w.user()
    bo = w.user()
    w.repo.grant(bo, "BUSINESS_OWNER", clan.clan_id)
    calls_before = len(w.provider.provider_calls)
    for who in (outsider, bo):
        token = w.token(who)
        bad_id = "not-a-uuid"  # authorization runs BEFORE path validation: 403, never 422
        for r in (w.retry(token, bad_id), w.abandon(token, bad_id), w.reset(token, bad_id), w.listing(token, "?page_size=9999"),
                  w.retry(token, job.job_id), w.abandon(token, job.job_id), w.reset(token, clan.clan_id)):
            assert (r.status_code, code(r)) == (403, "FORBIDDEN")
    anonymous = [
        w.client.post(f"/api/v1/admin/provisioning-jobs/{job.job_id}/retry"),
        w.client.post(f"/api/v1/admin/provisioning-jobs/{job.job_id}/abandon"),
        w.client.post(f"/api/v1/admin/clans/{clan.clan_id}/owner/temporary-password"),
        w.client.get("/api/v1/admin/provisioning-jobs"),
    ]
    assert [r.status_code for r in anonymous] == [401, 401, 401, 401]
    assert len(w.provider.provider_calls) == calls_before and w.job().status == "FAILED_RETRYABLE"


def test_a_restricted_sa_who_must_still_change_the_password_is_403(w):
    sa = w.user("PENDING", first_login_required=True)
    w.repo.grant(sa, "SYSTEM_ADMIN")
    w.repo.set_cred(sa, must_change_password=True)
    token = w.token(sa)
    assert w.listing(token).status_code == 403
    assert w.retry(token, uuid.uuid4()).status_code == 403


def test_unknown_jobs_and_clans_are_404_and_bad_ids_are_422(w):
    _sa, token = w.sa()
    for r in (w.retry(token, uuid.uuid4()), w.abandon(token, uuid.uuid4()), w.reset(token, uuid.uuid4())):
        assert (r.status_code, code(r)) == (404, "NOT_FOUND")
    for r in (w.retry(token, "x"), w.abandon(token, "x"), w.reset(token, "x"), w.listing(token, "?clan_id=x"),
              w.listing(token, "?status=NOPE"), w.listing(token, "?page_size=101"), w.listing(token, "?page=0")):
        assert (r.status_code, code(r)) == (422, "VALIDATION_ERROR")
    assert w.provider.provider_calls == []


# ------------------------------------------------------------------ the list


def test_the_list_filters_pages_newest_first_and_never_shows_personal_data(w):
    sa, token = w.sa()
    clans = [w.clan(name=f"N{i}", email=f"o{i}@example.test")[0] for i in range(3)]
    jobs = []
    for i, clan in enumerate(clans):
        clock0 = FROZEN + timedelta(minutes=i)
        jobs.append(seed_job(w, clan.clan_id, f"o{i}@example.test", status="FAILED_RETRYABLE" if i < 2 else "SUCCEEDED", created=clock0))
    r = w.listing(token)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert (body["total"], body["page"], body["page_size"]) == (3, 1, 20)
    assert [i["job_id"] for i in body["items"]] == [str(j.job_id) for j in reversed(jobs)]  # newest first
    assert set(body["items"][0]) == {"job_id", "job_type", "clan_id", "status", "user_id", "email_delivery_status",
                                     "attempt_count", "needs_cleanup", "error_code", "created_at", "updated_at"}
    for hidden in ("example.test", "email", "phone", "firebase", "own-", "password", "display"):
        assert hidden not in r.text.lower().replace("email_delivery_status", ""), hidden
    only = w.listing(token, f"?clan_id={clans[1].clan_id}").json()
    assert (only["total"], [i["job_id"] for i in only["items"]]) == (1, [str(jobs[1].job_id)])
    failed = w.listing(token, "?status=FAILED_RETRYABLE").json()
    assert failed["total"] == 2 and {i["status"] for i in failed["items"]} == {"FAILED_RETRYABLE"}
    both = w.listing(token, f"?status=SUCCEEDED&clan_id={clans[0].clan_id}").json()
    assert both["total"] == 0 and both["items"] == []  # the filters are ANDed
    paged = w.listing(token, "?page_size=2&page=2").json()
    assert (paged["total"], paged["page"], paged["page_size"], len(paged["items"])) == (3, 2, 2, 1)
    assert w.listing(token, "?page_size=100").status_code == 200


# ------------------------------------------------------------------ retry: what it accepts


def test_a_retry_of_a_retryable_job_creates_the_owner_with_a_new_password_shown_once(w):
    sa, token, clan, job = retryable(w)
    other_sa, other_token = second_sa(w)
    w.provider.provider_calls.clear()
    r = w.retry(other_token, job.job_id)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert (body["job_id"], body["status"], body["clan_id"]) == (str(job.job_id), "SUCCEEDED", str(clan.clan_id))
    assert body["temporary_password"] == PASSWORDS[1]  # the first attempt used PASSWORDS[0]: always a new one
    assert body["owner_email"] == OWNER_EMAIL and body["owner_display_name"] == OWNER_NAME
    assert datetime.fromisoformat(body["temporary_password_expires_at"]) == FROZEN + timedelta(hours=72)
    job = w.job()
    assert (job.status, job.attempt_count, job.needs_cleanup, job.error_code) == ("SUCCEEDED", 2, False, None)
    [owner] = w.owner_users()
    assert (owner.status, owner.first_login_required, str(owner.user_id)) == ("PENDING", True, body["user_id"])
    assert w.repo.creds[owner.user_id].must_change_password is True
    assert [o.user_id for o in w.family.owners] == [owner.user_id]
    assert w.events() == ["created", "started", "failed_retryable", "retried", "succeeded"]
    retried = next(a for a in w.repo.audit if a["new_data"].get("event") == "retried")
    assert retried["actor_id"] == other_sa.user_id and retried["old_data"] == {"status": "FAILED_RETRYABLE"}
    assert [op for op, _ in w.provider.provider_calls] == ["get_user", "create_user"]
    assert w.provider.open_transaction_calls == []  # no transaction open during a Firebase call
    # the role was granted by the SA who retried
    assert w.sender.calls[-1][2] == PASSWORDS[1]


def test_a_retry_reuses_the_firebase_user_an_earlier_attempt_left_and_gives_it_a_new_password(w):
    sa, token, clan, job = retryable(w, fault=After(ProviderUnavailable("timeout")), operation="create_user")
    uid = f"own-{job.job_id}"
    assert uid in w.provider.provider_users  # the call worked, the answer was lost
    w.provider.provider_calls.clear()
    r = w.retry(token, job.job_id)
    assert r.status_code == 200 and r.json()["temporary_password"] == PASSWORDS[1]
    assert [op for op, _ in w.provider.provider_calls] == ["get_user", "set_owner_password"]
    assert w.provider.owner_password_sets == [uid] and w.provider.password_changes == []
    assert w.provider.password_shapes[-1][0] == "set_owner_password"


def test_each_successful_retry_path_never_uses_the_general_set_password(w):
    sa, token, clan, job = retryable(w, fault=After(ProviderUnavailable("timeout")))
    assert w.retry(token, job.job_id).status_code == 200
    assert w.provider.password_changes == []


@pytest.mark.parametrize("error_op, fault, status", [
    ("get_user", ProviderUnavailable("timeout"), 503),
    ("create_user", ProviderUnavailable("timeout"), 503),
    ("create_user", PasswordRejected(), 503),
])
def test_a_retry_that_fails_again_is_recorded_like_the_first_run_and_keeps_no_password(w, error_op, fault, status):
    sa, token, clan, job = retryable(w)
    w.provider.faults[error_op] = [fault]
    r = w.retry(token, job.job_id)
    assert r.status_code == status
    job = w.job()
    assert (job.status, job.attempt_count) == ("FAILED_RETRYABLE", 2) and w.owner_users() == []
    assert w.events()[-2:] == ["retried", "failed_retryable"]
    for secret in PASSWORDS[:3]:
        assert secret not in r.text and secret not in everything_stored(w)


def test_the_last_allowed_attempt_that_fails_is_final_and_compensates(w):
    sa, token, clan, job = retryable(w)
    job.attempt_count = settings.PROVISIONING_MAX_ATTEMPTS - 1  # the next run is the last one
    w.provider.faults["create_user"] = [ProviderUnavailable("timeout")]
    r = w.retry(token, job.job_id)
    assert r.status_code == 409 and "can no longer be retried" in r.json()["error"]["message"]
    job = w.job()
    assert (job.status, job.attempt_count, job.needs_cleanup) == ("FAILED", settings.PROVISIONING_MAX_ATTEMPTS, False)
    assert ("delete_user", f"own-{job.job_id}") in w.provider.provider_calls and job.firebase_user_created is False
    again = w.retry(token, job.job_id)
    assert (again.status_code, code(again)) == (409, "STATE_CONFLICT") and "FAILED" in again.json()["error"]["message"]


def test_a_stuck_pending_job_and_a_running_job_whose_lease_ran_out_are_retried(w):
    sa, token = w.sa()
    stuck_clan, _ = w.clan(email="stuck@example.test")
    expired_clan, _ = w.clan(email="expired@example.test")
    stuck = seed_job(w, stuck_clan.clan_id, "stuck@example.test", status="PENDING", created=FROZEN - LEASE - timedelta(seconds=1))
    expired = seed_job(w, expired_clan.clan_id, "expired@example.test", status="RUNNING")
    expired.attempt_count, expired.lease_expires_at = 1, FROZEN - timedelta(seconds=1)
    for job, clan in ((stuck, stuck_clan), (expired, expired_clan)):
        r = w.retry(token, job.job_id)
        assert r.status_code == 200 and r.json()["status"] == "SUCCEEDED", r.text
    assert (stuck.attempt_count, expired.attempt_count) == (1, 2)  # a takeover moved the attempt on
    assert "retried" in w.events()


@pytest.mark.parametrize("status, extra, headers", [
    ("SUCCEEDED", {}, False),
    ("PENDING", {}, True),  # created moments ago: its request may still be starting it
    ("RUNNING", {"attempt_count": 1, "lease": +30}, True),  # a live lease
])
def test_a_job_that_cannot_be_retried_is_409_naming_its_status_and_nothing_changes(w, status, extra, headers):
    sa, token = w.sa()
    clan, _ = w.clan()
    job = seed_job(w, clan.clan_id, OWNER_EMAIL, status=status, created=FROZEN - timedelta(seconds=5))
    if "attempt_count" in extra:
        job.attempt_count, job.lease_expires_at = extra["attempt_count"], FROZEN + timedelta(seconds=extra["lease"])
    snapshot, calls = (job.status, job.attempt_count, job.updated_at), len(w.provider.provider_calls)
    r = w.retry(token, job.job_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
    assert f"is {status}" in r.json()["error"]["message"] and str(job.job_id) in r.json()["error"]["message"]
    assert ("retry-after" in r.headers) is headers
    assert (job.status, job.attempt_count, job.updated_at) == snapshot and len(w.provider.provider_calls) == calls
    assert w.owner_users() == [] and [a for a in w.events() if a in ("retried", "started")] == []


def test_a_failed_job_without_a_cleanup_to_do_is_never_retried_including_uid_mismatch_and_used_up_jobs(w):
    sa, token, clan, job = retryable(w)
    uid = f"own-{job.job_id}"
    # UID_MISMATCH: a user with another e-mail under our uid
    w.provider.provider_users[uid] = ProviderUser(uid=uid, email="someone.else@example.test", display_name="X", disabled=False)
    first = w.retry(token, job.job_id)
    assert (first.status_code, code(first)) == (409, "STATE_CONFLICT")
    job = w.job()
    assert (job.status, job.error_code, job.needs_cleanup) == ("FAILED", "UID_MISMATCH", False)
    assert ("delete_user", uid) not in w.provider.provider_calls  # never deleted
    w.provider.provider_calls.clear()
    second = w.retry(token, job.job_id)
    assert (second.status_code, code(second)) == (409, "STATE_CONFLICT") and "is FAILED" in second.json()["error"]["message"]
    assert w.provider.provider_calls == [] and w.provider.provider_users[uid].email == "someone.else@example.test"


def test_a_job_that_used_all_its_attempts_is_409_and_points_to_abandon(w):
    sa, token, clan, job = retryable(w)
    job.attempt_count = settings.PROVISIONING_MAX_ATTEMPTS
    r = w.retry(token, job.job_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
    assert "abandon" in r.json()["error"]["message"] and job.status == "FAILED_RETRYABLE"
    assert w.abandon(token, job.job_id).status_code == 200  # ... and abandon takes it


def test_a_retry_is_refused_when_the_clan_or_the_email_no_longer_allow_an_owner_and_the_job_stays(w):
    sa, token, clan, job = retryable(w)
    calls_before = list(w.provider.provider_calls)
    other = w.user()
    w.family.add_owner(clan, other)
    r = w.retry(token, job.job_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "already has an Owner" in r.json()["error"]["message"]
    w.family.owners.clear()
    clan.status = "ACTIVE"
    r = w.retry(token, job.job_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "ACTIVE" in r.json()["error"]["message"]
    clan.status = "PENDING"
    taken = make_user("ACTIVE")
    taken.email = OWNER_EMAIL.lower()
    w.repo.add_user(taken)
    r = w.retry(token, job.job_id)
    assert (r.status_code, code(r)) == (409, "DUPLICATE_RESOURCE")
    assert (w.job().status, w.job().attempt_count) == ("FAILED_RETRYABLE", 1)  # untouched
    assert w.provider.provider_calls == calls_before  # the refused retries called Firebase not at all
    assert w.provider.owner_password_sets == []


def test_without_the_admin_api_a_retry_writes_nothing(w):
    sa, token, clan, job = retryable(w)
    w.provider.admin_api_enabled = False
    audit = len(w.repo.audit)
    r = w.retry(token, job.job_id)
    assert (r.status_code, code(r)) == (503, "PROVIDER_UNAVAILABLE")
    assert len(w.repo.audit) == audit and (w.job().status, w.job().attempt_count) == ("FAILED_RETRYABLE", 1)


def test_a_retry_whose_run_is_replaced_meanwhile_writes_nothing_and_deletes_nothing(w):
    sa, token, clan, job = retryable(w)

    async def taken_over(uid):  # another administrator's retry takes the job over while this one is in Firebase
        w.job().attempt_count += 1
        await w.tx.commit()

    w.provider.hooks["create_user"] = taken_over
    r = w.retry(token, job.job_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "replaced" in r.json()["error"]["message"]
    job = w.job()
    assert (job.status, job.attempt_count) == ("RUNNING", 3) and w.owner_users() == []
    assert "delete_user" not in [op for op, _ in w.provider.provider_calls]


def test_the_lock_order_of_a_retry_is_the_clan_then_the_job(w):
    sa, token, clan, job = retryable(w)
    w.family.calls.clear()
    assert w.retry(token, job.job_id).status_code == 200
    calls = w.family.calls
    first_clan, first_job = calls.index("lock_clan"), calls.index("job.lock")
    assert first_clan < first_job < calls.index("job.mark_running")
    assert "lock_user" not in calls and "lock_user" not in w.repo.calls


# ------------------------------------------------------------------ retry and the original Idempotency-Key


def test_a_retry_completes_the_original_key_that_a_dead_request_left_in_progress(monkeypatch, clock, passwords):
    monkeypatch.setattr(use_cases, "utcnow", lambda: clock[0])
    monkeypatch.setattr(use_cases, "_default_password", lambda: PASSWORDS[next(passwords)])
    w = OwnerWorld()  # a death is a BaseException: the client must raise it
    sa, token = w.sa()
    clan, _ = w.clan()

    async def die(uid):
        raise Crash()

    w.provider.hooks["get_user"] = die
    with pytest.raises(Crash):
        w.post(token, clan.clan_id, key="key-died-0001")
    w.provider.hooks.clear()
    job = w.job()
    [row] = w.idem.rows
    assert (row.status, row.resource_id, job.status) == ("IN_PROGRESS", job.job_id, "RUNNING")
    clock[0] = FROZEN + LEASE + timedelta(seconds=1)  # the lease ran out
    other_sa, other_token = w.sa()
    w.tx.begin()
    r = w.client.post(f"/api/v1/admin/provisioning-jobs/{job.job_id}/retry", headers={"Authorization": f"Bearer {other_token}"})
    assert r.status_code == 200 and r.json()["status"] == "SUCCEEDED"
    [row] = w.idem.rows
    assert row.status == "COMPLETED" and row.response_status == 201 and row.resource_id == job.job_id
    assert set(row.response_body) == {"job_id", "status", "clan_id", "user_id"}  # no password, nothing personal
    assert r.json()["temporary_password"] not in repr(row.response_body) and PASSWORDS[0] not in repr(row.response_body)
    # the original request, sent again with its key, is a replay with nulls
    replay = w.post(token, clan.clan_id, key="key-died-0001")
    assert replay.status_code == 201 and replay.headers["idempotency-replayed"] == "true"
    assert replay.json()["job_id"] == str(job.job_id) and replay.json()["temporary_password"] is None
    assert w.job().attempt_count == 2


def test_a_retry_that_fails_releases_the_original_key(monkeypatch, clock, passwords):
    monkeypatch.setattr(use_cases, "utcnow", lambda: clock[0])
    monkeypatch.setattr(use_cases, "_default_password", lambda: PASSWORDS[next(passwords)])
    w = OwnerWorld(raise_server_exceptions=False)
    sa, token = w.sa()
    clan, _ = w.clan()
    # a request that died after its job started: the key stays IN_PROGRESS
    job = seed_job(w, clan.clan_id, OWNER_EMAIL, status="RUNNING")
    job.attempt_count, job.lease_expires_at = 1, FROZEN - timedelta(seconds=1)
    from app.models.family.entities import IdempotencyKey

    w.idem.rows.append(IdempotencyKey(
        idempotency_id=uuid.uuid4(), actor_id=sa.user_id, endpoint=use_cases.ENDPOINT, idempotency_key="key-left-0001",
        request_hash="a" * 64, status="IN_PROGRESS", created_at=FROZEN, expires_at=FROZEN + timedelta(days=7),
        resource_type="provisioning_job", resource_id=job.job_id))
    w.tx.begin()
    w.provider.faults["create_user"] = [ProviderUnavailable("timeout")]
    r = w.client.post(f"/api/v1/admin/provisioning-jobs/{job.job_id}/retry", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 503 and w.idem.rows == []  # released: the key is free again
    assert w.job().status == "FAILED_RETRYABLE"


# ------------------------------------------------------------------ retry: only the clean-up


def owing_cleanup(w: World, *, delete_fault=None):
    sa, token = w.sa()
    clan, _ = w.clan()
    w.provider.faults["create_user"] = [ProviderInvalidUser()]
    if delete_fault is not None:
        w.provider.faults["delete_user"] = [delete_fault]
    assert w.post(token, clan.clan_id).status_code == 409
    job = w.job()
    return sa, token, clan, job


def test_a_retry_of_a_job_that_owes_a_cleanup_only_cleans_up_and_makes_no_password(w):
    sa, token, clan, job = owing_cleanup(w, delete_fault=ProviderUnavailable("timeout"))
    assert (job.status, job.needs_cleanup, job.firebase_user_created) == ("FAILED", True, True)
    blocked = w.post(token, clan.clan_id)
    assert blocked.status_code == 409 and "clean-up" in blocked.json()["error"]["message"]
    w.provider.provider_calls.clear()
    next_password = len(w.provider.password_shapes)
    r = w.retry(token, job.job_id)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert (body["job_id"], body["status"], body["clan_id"]) == (str(job.job_id), "FAILED", str(clan.clan_id))
    assert body["temporary_password"] is None and body["user_id"] is None and body["owner_email"] is None
    assert [op for op, _ in w.provider.provider_calls] == ["delete_user"]  # nothing else: no create, no password
    assert len(w.provider.password_shapes) == next_password
    job = w.job()
    assert (job.status, job.needs_cleanup, job.firebase_user_created, job.attempt_count) == ("FAILED", False, False, 1)
    assert w.events()[-1] == "cleanup_done"
    assert w.post(token, clan.clan_id).status_code == 201  # the clan is free again


def test_a_cleanup_retry_that_cannot_delete_is_503_and_the_flags_stay_up(w):
    sa, token, clan, job = owing_cleanup(w, delete_fault=ProviderUnavailable("timeout"))
    w.provider.faults["delete_user"] = [ProviderUnavailable("timeout")]
    r = w.retry(token, job.job_id)
    assert (r.status_code, code(r)) == (503, "PROVIDER_UNAVAILABLE")
    job = w.job()
    assert (job.status, job.needs_cleanup, job.firebase_user_created) == ("FAILED", True, True)
    assert w.post(token, clan.clan_id).status_code == 409  # still blocked


def test_two_cleanup_retries_in_a_row_the_second_finds_nothing_left_to_do(w):
    sa, token, clan, job = owing_cleanup(w, delete_fault=ProviderUnavailable("timeout"))
    assert w.retry(token, job.job_id).status_code == 200
    second = w.retry(token, job.job_id)
    assert (second.status_code, code(second)) == (409, "STATE_CONFLICT") and "is FAILED" in second.json()["error"]["message"]


# ------------------------------------------------------------------ abandon


def test_abandon_marks_the_job_failed_commits_the_flags_first_deletes_then_lowers_them(w):
    sa, token, clan, job = retryable(w, fault=After(ProviderUnavailable("timeout")))
    uid = f"own-{job.job_id}"
    seen = {}

    async def spy(u):
        j = w.job()
        seen.update(status=j.status, needs_cleanup=j.needs_cleanup, created=j.firebase_user_created,
                    uncommitted=w.tx.uncommitted(), uid=u, error=j.error_code)

    w.provider.hooks["delete_user"] = spy
    w.provider.provider_calls.clear()
    r = w.abandon(token, job.job_id)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert seen == {"status": "FAILED", "needs_cleanup": True, "created": True, "uncommitted": False, "uid": uid, "error": "ABANDONED"}
    body = r.json()
    assert (body["status"], body["error_code"], body["needs_cleanup"], body["job_id"]) == ("FAILED", "ABANDONED", False, str(job.job_id))
    assert [op for op, _ in w.provider.provider_calls] == ["delete_user"] and uid not in w.provider.provider_users
    job = w.job()
    assert (job.status, job.needs_cleanup, job.firebase_user_created, job.attempt_count) == ("FAILED", False, False, 1)
    assert w.events()[-3:] == ["failed_retryable", "abandoned", "cleanup_done"]
    assert w.provider.open_transaction_calls == []
    assert w.post(token, clan.clan_id).status_code == 201  # the clan is free again


def test_abandon_always_tries_the_delete_when_a_run_ever_started_even_if_we_are_not_sure(w):
    sa, token, clan, job = retryable(w)  # attempt 1, firebase_user_created false
    assert job.firebase_user_created is False
    w.provider.provider_calls.clear()
    assert w.abandon(token, job.job_id).status_code == 200
    assert w.provider.provider_calls == [("delete_user", f"own-{job.job_id}")]


def test_a_failed_delete_leaves_the_flags_up_and_blocks_the_clan_and_the_email(w):
    sa, token, clan, job = retryable(w)
    w.provider.faults["delete_user"] = [ProviderUnavailable("timeout")]
    r = w.abandon(token, job.job_id)
    assert r.status_code == 200 and r.json()["needs_cleanup"] is True and r.json()["error_code"] == "ABANDONED"
    job = w.job()
    assert (job.status, job.needs_cleanup, job.firebase_user_created) == ("FAILED", True, True)
    assert w.events()[-2:] == ["abandoned", "cleanup_failed"]
    blocked = w.post(token, clan.clan_id)
    assert blocked.status_code == 409 and "clean-up" in blocked.json()["error"]["message"]
    again = w.abandon(token, job.job_id)
    assert (again.status_code, code(again)) == (409, "STATE_CONFLICT") and "retry it" in again.json()["error"]["message"]


def test_abandoning_a_job_nobody_ever_ran_does_not_touch_firebase(w):
    sa, token = w.sa()
    clan, _ = w.clan()
    job = seed_job(w, clan.clan_id, OWNER_EMAIL, status="PENDING", created=FROZEN - LEASE - timedelta(seconds=1))
    r = w.abandon(token, job.job_id)
    assert r.status_code == 200 and r.json()["needs_cleanup"] is False
    assert w.provider.provider_calls == [] and (job.status, job.firebase_user_created, job.needs_cleanup) == ("FAILED", False, False)
    assert w.events() == ["abandoned"]


def test_abandon_takes_a_running_job_whose_lease_ran_out_and_the_old_run_then_writes_nothing(w):
    sa, token = w.sa()
    clan, _ = w.clan()
    job = seed_job(w, clan.clan_id, OWNER_EMAIL, status="RUNNING")
    job.attempt_count, job.lease_expires_at = 1, FROZEN - timedelta(seconds=1)
    assert w.abandon(token, job.job_id).status_code == 200
    assert job.status == "FAILED" and ("delete_user", job.firebase_uid) in w.provider.provider_calls


@pytest.mark.parametrize("status, attempts, lease, why", [
    ("RUNNING", 1, +30, "lease"),
    ("PENDING", 0, None, "moments ago"),
    ("SUCCEEDED", 1, None, "succeeded"),
])
def test_abandon_refuses_a_running_job_with_a_live_lease_and_the_other_states_and_changes_nothing(w, status, attempts, lease, why):
    sa, token = w.sa()
    clan, _ = w.clan()
    job = seed_job(w, clan.clan_id, OWNER_EMAIL, status=status, created=FROZEN - timedelta(seconds=5))
    job.attempt_count = attempts
    if lease is not None:
        job.lease_expires_at = FROZEN + timedelta(seconds=lease)
    snapshot = (job.status, job.attempt_count, job.updated_at, job.needs_cleanup)
    r = w.abandon(token, job.job_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT")
    assert f"is {status}" in r.json()["error"]["message"] and why in r.json()["error"]["message"]
    assert (job.status, job.attempt_count, job.updated_at, job.needs_cleanup) == snapshot
    assert w.provider.provider_calls == [] and w.events() == []
    if status == "RUNNING":
        assert "retry-after" in r.headers


def test_abandon_refuses_a_failed_job_final_or_owing_a_cleanup(w):
    sa, token, clan, job = owing_cleanup(w)  # cleaned at once: FAILED, nothing owed
    r = w.abandon(token, job.job_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "is FAILED" in r.json()["error"]["message"]


def test_abandon_releases_the_original_key_that_a_dead_request_left_in_progress(w):
    sa, token = w.sa()
    clan, _ = w.clan()
    job = seed_job(w, clan.clan_id, OWNER_EMAIL, status="RUNNING")
    job.attempt_count, job.lease_expires_at = 1, FROZEN - timedelta(seconds=1)
    from app.models.family.entities import IdempotencyKey

    w.idem.rows.append(IdempotencyKey(
        idempotency_id=uuid.uuid4(), actor_id=sa.user_id, endpoint=use_cases.ENDPOINT, idempotency_key="key-left-0002",
        request_hash="a" * 64, status="IN_PROGRESS", created_at=FROZEN, expires_at=FROZEN + timedelta(days=7),
        resource_type="provisioning_job", resource_id=job.job_id))
    assert w.abandon(token, job.job_id).status_code == 200
    assert w.idem.rows == []
    calls = w.family.calls
    assert calls.index("idem.lock_by_resource") < calls.index("job.lock")  # lock order: the key, then the job


def test_abandon_audit_holds_nothing_personal(w):
    sa, token, clan, job = retryable(w)
    assert w.abandon(token, job.job_id).status_code == 200
    audit = next(a for a in w.repo.audit if a["new_data"].get("event") == "abandoned")
    assert audit["actor_id"] == sa.user_id and audit["new_data"]["error_code"] == "ABANDONED"
    text = repr(w.repo.audit)
    for hidden in (OWNER_EMAIL, OWNER_EMAIL.lower(), OWNER_NAME, OWNER_PHONE, *PASSWORDS[:3]):
        assert hidden not in text


# ------------------------------------------------------------------ reset: the Owner exists


def with_owner(w: World):
    """An SA, a clan, and the Owner a job created (PENDING, must change the password), with one session."""
    sa, token = w.sa()
    clan, _ = w.clan()
    created = w.post(token, clan.clan_id)
    assert created.status_code == 201
    [owner] = w.owner_users()
    session = w.token(owner)
    return sa, token, clan, owner, session


def test_a_reset_gives_the_owner_a_new_temporary_password_revokes_the_sessions_and_audits_without_it(w, clock):
    sa, token, clan, owner, session = with_owner(w)
    first_password = PASSWORDS[0]
    cred = w.repo.creds[owner.user_id]
    clock[0] = FROZEN + timedelta(hours=100)  # the first temporary password expired long ago
    r = w.reset(token, clan.clan_id)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["temporary_password"] == PASSWORDS[1] != first_password
    assert (body["clan_id"], body["user_id"], body["owner_email"], body["owner_display_name"]) == (
        str(clan.clan_id), str(owner.user_id), OWNER_EMAIL, OWNER_NAME)
    assert datetime.fromisoformat(body["temporary_password_expires_at"]) == clock[0] + timedelta(hours=72)
    assert (cred.must_change_password, cred.temporary_password_issued_at, cred.temporary_password_expires_at, cred.updated_at) == (
        True, clock[0], clock[0] + timedelta(hours=72), clock[0])
    assert (owner.status, owner.first_login_required) == ("PENDING", True)  # nothing else changed
    assert all(s.revoked_at == clock[0] and s.revoke_reason == "TEMPORARY_PASSWORD_RESET" for s in w.repo.sessions.values()
               if s.user_id == owner.user_id)
    assert [(o.user_id, o.ended_at) for o in w.family.owners] == [(owner.user_id, None)]
    audit = [a for a in w.repo.audit if a["action"] == "clan.owner.temp_password_reset"]
    assert len(audit) == 1 and audit[0]["actor_id"] == sa.user_id and audit[0]["entity_id"] == owner.user_id
    assert audit[0]["clan_id"] == clan.clan_id and audit[0]["new_data"]["revoked_sessions"] == 1
    assert w.provider.owner_password_sets == [owner.firebase_uid] and w.provider.password_changes == []
    assert w.sender.calls[-1][2] == PASSWORDS[1]
    for secret in PASSWORDS[:2]:
        assert secret not in repr(audit) + repr(w.repo.audit)


def test_a_reset_checks_then_ends_the_transaction_then_calls_firebase_then_writes(w):
    sa, token, clan, owner, session = with_owner(w)
    cred = w.repo.creds[owner.user_id]
    before = (cred.temporary_password_issued_at, cred.temporary_password_expires_at, cred.updated_at)
    seen = {}

    async def spy(uid):
        seen.update(
            ended=w.tx.events[-1], open_work=w.tx.uncommitted(),
            cred=(cred.temporary_password_issued_at, cred.temporary_password_expires_at, cred.updated_at),
            sessions_revoked=[s.revoked_at for s in w.repo.sessions.values() if s.user_id == owner.user_id],
            audit=len([a for a in w.repo.audit if a["action"] == "clan.owner.temp_password_reset"]),
            locks=[c for c in w.family.calls if c in ("lock_clan", "lock_credential")])

    w.provider.hooks["set_owner_password"] = spy
    w.family.calls.clear()
    assert w.reset(token, clan.clan_id).status_code == 200
    assert seen["ended"] == "rollback" and seen["open_work"] is False  # the read transaction was ended first
    assert seen["cred"] == before and seen["sessions_revoked"] == [None] and seen["audit"] == 0  # Firebase FIRST
    assert seen["locks"] == [] and w.provider.open_transaction_calls == []  # no lock was held across the call
    # then the database: the clan, then the credential row; the users row is never locked
    calls = w.family.calls
    assert calls.count("lock_clan") == 1 and calls.count("lock_credential") == 1
    assert calls.index("lock_clan") < calls.index("lock_credential") < calls.index("get_user_fresh")
    assert "lock_user" not in calls


def test_after_a_reset_the_owner_can_sign_in_again_and_the_old_session_is_dead_and_expiry_is_enforced_anew():
    w = World()  # the real clock: /auth/session reads the real time
    sa, token = w.sa()
    clan, _ = w.clan()
    assert w.post(token, clan.clan_id).status_code == 201
    [owner] = w.owner_users()
    cred = w.repo.creds[owner.user_id]
    ok = w.client.post("/api/v1/auth/session", json={"id_token": w.provider.issue(owner.firebase_uid)})
    assert ok.status_code == 201 and ok.json()["requires_password_change"] is True
    old_access = ok.json()["access_token"]
    assert w.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access}"}).status_code == 200
    cred.temporary_password_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)  # 72 hours later
    expired = w.client.post("/api/v1/auth/session", json={"id_token": w.provider.issue(owner.firebase_uid)})
    assert (expired.status_code, code(expired)) == (403, "TEMPORARY_PASSWORD_EXPIRED")
    # the SA reissues the password
    r = w.reset(token, clan.clan_id)
    assert r.status_code == 200
    assert (cred.temporary_password_expires_at - datetime.now(timezone.utc)) > timedelta(hours=71)
    # the session from before the reset is revoked
    assert w.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access}"}).status_code == 401
    again = w.client.post("/api/v1/auth/session", json={"id_token": w.provider.issue(owner.firebase_uid)})
    assert again.status_code == 201 and again.json()["requires_password_change"] is True
    assert again.json()["user"]["status"] == "PENDING"
    # ... and the new 72 hours run out like the first ones
    cred.temporary_password_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    expired_again = w.client.post("/api/v1/auth/session", json={"id_token": w.provider.issue(owner.firebase_uid)})
    assert (expired_again.status_code, code(expired_again)) == (403, "TEMPORARY_PASSWORD_EXPIRED")


@pytest.mark.parametrize("status, phrase", [
    ("ACTIVE", "already set their own password"), ("LOCKED", "cannot be issued"), ("DISABLED", "cannot be issued"),
])
def test_a_reset_for_an_owner_who_is_not_pending_is_409_naming_the_status_and_changes_nothing(w, status, phrase):
    sa, token, clan, owner, session = with_owner(w)
    owner.status = status
    cred = w.repo.creds[owner.user_id]
    before = (cred.temporary_password_issued_at, cred.updated_at)
    r = w.reset(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and status in r.json()["error"]["message"]
    assert phrase in r.json()["error"]["message"]  # the reason differs: a blocked account vs one that is done with the temporary password
    assert w.provider.owner_password_sets == [] and (cred.temporary_password_issued_at, cred.updated_at) == before
    assert [s.revoked_at for s in w.repo.sessions.values() if s.user_id == owner.user_id] == [None]
    assert not [a for a in w.repo.audit if a["action"] == "clan.owner.temp_password_reset"]


def test_a_reset_for_an_owner_who_no_longer_has_to_change_the_password_is_409(w):
    sa, token, clan, owner, session = with_owner(w)
    w.repo.creds[owner.user_id].must_change_password = False
    r = w.reset(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and w.provider.owner_password_sets == []


def test_a_clan_without_an_owner_and_an_owner_not_made_by_a_job_are_409_and_firebase_is_not_called(w):
    sa, token = w.sa()
    clan, _ = w.clan()
    r = w.reset(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "no Owner" in r.json()["error"]["message"]
    foreign = w.user("PENDING", first_login_required=True)  # a uid that is not own-<uuid>
    w.repo.set_cred(foreign, must_change_password=True)
    w.family.add_owner(clan, foreign)
    r = w.reset(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "not created by provisioning" in r.json()["error"]["message"]
    assert w.provider.provider_calls == []


def test_without_the_admin_api_a_reset_changes_nothing(w):
    sa, token, clan, owner, session = with_owner(w)
    w.provider.admin_api_enabled = False
    r = w.reset(token, clan.clan_id)
    assert (r.status_code, code(r)) == (503, "PROVIDER_UNAVAILABLE")


@pytest.mark.parametrize("fault, http, name", [
    (ProviderUnavailable("timeout"), 503, "PROVIDER_UNAVAILABLE"),
    (PasswordRejected(), 503, "PROVIDER_UNAVAILABLE"),
])
def test_when_firebase_fails_nothing_changes_in_the_database_and_the_sessions_live(w, fault, http, name):
    sa, token, clan, owner, session = with_owner(w)
    cred = w.repo.creds[owner.user_id]
    before = (cred.temporary_password_issued_at, cred.temporary_password_expires_at, cred.updated_at)
    w.provider.faults["set_owner_password"] = [fault]
    r = w.reset(token, clan.clan_id)
    assert (r.status_code, code(r)) == (http, name)
    assert (cred.temporary_password_issued_at, cred.temporary_password_expires_at, cred.updated_at) == before
    assert [s.revoked_at for s in w.repo.sessions.values() if s.user_id == owner.user_id] == [None]
    assert not [a for a in w.repo.audit if a["action"] == "clan.owner.temp_password_reset"]
    assert PASSWORDS[1] not in r.text and PASSWORDS[1] not in everything_stored(w)


def test_an_owner_missing_at_firebase_is_409_and_nothing_changes(w):
    sa, token, clan, owner, session = with_owner(w)
    w.provider.provider_users.clear()
    r = w.reset(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "no account at the identity provider" in r.json()["error"]["message"]


def test_a_database_failure_after_firebase_changed_the_password_is_503_and_the_database_is_unchanged(w):
    sa, token, clan, owner, session = with_owner(w)
    cred = w.repo.creds[owner.user_id]
    before = (cred.temporary_password_issued_at, cred.updated_at)
    w.tx.fail_commit = True
    r = w.reset(token, clan.clan_id)
    assert (r.status_code, code(r)) == (503, "DATABASE_UNAVAILABLE")
    assert w.provider.owner_password_sets == [owner.firebase_uid]  # Firebase did change: a second reset repairs it
    assert (cred.temporary_password_issued_at, cred.updated_at) == before
    assert [s.revoked_at for s in w.repo.sessions.values() if s.user_id == owner.user_id] == [None]
    w.tx.fail_commit = False
    assert w.reset(token, clan.clan_id).status_code == 200


# ------------------------------------------------------------------ reset: the gaps


def test_the_owner_changes_the_password_during_the_firebase_call_so_nothing_is_overwritten_and_it_is_409(w, caplog):
    sa, token, clan, owner, session = with_owner(w)
    cred = w.repo.creds[owner.user_id]

    async def owner_changes_password(uid):  # committed by the Owner's own change-password while we are in Firebase
        owner.status, owner.first_login_required = "ACTIVE", False
        cred.must_change_password, cred.temporary_password_issued_at, cred.temporary_password_expires_at = False, None, None
        cred.password_changed_at, cred.updated_at = FROZEN + timedelta(seconds=1), FROZEN + timedelta(seconds=1)
        await w.tx.commit()

    w.provider.hooks["set_owner_password"] = owner_changes_password
    r = w.reset(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "ACTIVE" in r.json()["error"]["message"]
    # the database keeps what the Owner wrote: not overwritten by the reset
    assert (owner.status, cred.must_change_password, cred.temporary_password_issued_at, cred.temporary_password_expires_at) == (
        "ACTIVE", False, None, None)
    assert not [a for a in w.repo.audit if a["action"] == "clan.owner.temp_password_reset"]
    # ... but the temporary password WAS set at Firebase in that gap (KI-25)
    assert w.provider.owner_password_sets == [owner.firebase_uid]
    assert PASSWORDS[1] not in r.text and PASSWORDS[1] not in everything_stored(w) and PASSWORDS[1] not in app_logs(caplog)
    assert w.sender.calls == w.sender.calls[:1]  # nothing was sent for the reset


def test_another_reset_that_won_the_race_makes_this_one_409_and_writes_nothing(w, clock):
    sa, token, clan, owner, session = with_owner(w)
    cred = w.repo.creds[owner.user_id]
    won = FROZEN + timedelta(seconds=5)

    async def other_reset_commits(uid):
        cred.temporary_password_issued_at, cred.temporary_password_expires_at = won, won + timedelta(hours=72)
        cred.updated_at = won
        await w.tx.commit()

    w.provider.hooks["set_owner_password"] = other_reset_commits
    r = w.reset(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "Try again" in r.json()["error"]["message"]
    assert cred.temporary_password_issued_at == won  # the winner's values stand
    assert [s.revoked_at for s in w.repo.sessions.values() if s.user_id == owner.user_id] == [None]


def test_the_owner_is_locked_during_the_firebase_call_so_the_reset_does_not_write(w):
    sa, token, clan, owner, session = with_owner(w)

    async def locked(uid):
        owner.status = "LOCKED"
        await w.tx.commit()

    w.provider.hooks["set_owner_password"] = locked
    r = w.reset(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "LOCKED" in r.json()["error"]["message"]
    assert not [a for a in w.repo.audit if a["action"] == "clan.owner.temp_password_reset"]


def test_the_clan_owner_changes_during_the_firebase_call_so_nothing_is_written(w):
    sa, token, clan, owner, session = with_owner(w)

    async def owner_replaced(uid):
        w.family.owners[0].ended_at = FROZEN
        await w.tx.commit()

    w.provider.hooks["set_owner_password"] = owner_replaced
    r = w.reset(token, clan.clan_id)
    assert (r.status_code, code(r)) == (409, "STATE_CONFLICT") and "changed meanwhile" in r.json()["error"]["message"]


def test_an_email_sender_that_fails_never_undoes_the_reset(w):
    sa, token, clan, owner, session = with_owner(w)
    w.sender.error = RuntimeError("smtp down")
    r = w.reset(token, clan.clan_id)
    assert r.status_code == 200 and r.json()["email_delivery_status"] == "FAILED"
    assert w.repo.creds[owner.user_id].must_change_password is True


# ------------------------------------------------------------------ the password is nowhere but the one response


def test_no_password_reaches_a_row_a_log_or_an_audit_entry_in_any_e6b_flow(w, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    sa, token, clan, job = retryable(w, fault=After(ProviderUnavailable("timeout")))
    retried = w.retry(token, job.job_id)
    assert retried.status_code == 200
    reset = w.reset(token, clan.clan_id)
    assert reset.status_code == 200
    shown = {retried.json()["temporary_password"], reset.json()["temporary_password"]}
    assert len(shown) == 2  # a new one every time
    stored, logged = everything_stored(w), app_logs(caplog)
    for password in (PASSWORDS[0], *shown):
        assert password not in stored and password not in logged, password
        assert password not in repr(w.repo.audit) and password not in repr(w.idem.rows)
        assert password not in w.get_job(token, job.job_id).text and password not in w.listing(token).text
    for personal in (OWNER_EMAIL, OWNER_EMAIL.lower(), OWNER_NAME, OWNER_PHONE):
        assert personal not in logged and personal not in repr(w.repo.audit), personal
    assert not re.search(r"temporary_password\s*[:=]\s*['\"]?\w{8}", logged)


# ------------------------------------------------------------------ which action guards which route


def _actions_of(route) -> list:
    """The Action each require_action(...) dependency of a route was built with (read from its closure)."""
    found, todo = [], [route.dependant]
    while todo:
        dependant = todo.pop()
        todo.extend(dependant.dependencies)
        call = dependant.call
        if call is not None and getattr(call, "__qualname__", "").startswith("require_action."):
            cells = dict(zip(call.__code__.co_freevars, (c.cell_contents for c in call.__closure__)))
            found.append(cells["action"])
    return found


def test_every_owner_route_is_guarded_by_exactly_the_planned_action():
    from app.controllers.family_management.owner_admin_router import router
    from app.dependencies.permissions import Action

    wanted = {
        ("POST", "/admin/clans/{clan_id}/owner"): Action.CLAN_OWNER_PROVISION,
        ("GET", "/admin/provisioning-jobs/{job_id}"): Action.PROVISIONING_JOB_READ,
        ("GET", "/admin/provisioning-jobs"): Action.PROVISIONING_JOB_READ,
        ("POST", "/admin/provisioning-jobs/{job_id}/retry"): Action.CLAN_OWNER_PROVISION,
        ("POST", "/admin/provisioning-jobs/{job_id}/abandon"): Action.CLAN_OWNER_PROVISION,
        ("POST", "/admin/clans/{clan_id}/owner/temporary-password"): Action.CLAN_OWNER_TEMP_PASSWORD_RESET,
    }
    actual = {(m, r.path): _actions_of(r) for r in router.routes for m in r.methods}
    assert actual == {key: [action] for key, action in wanted.items()}
