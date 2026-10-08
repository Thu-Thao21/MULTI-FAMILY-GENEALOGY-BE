"""Fakes for Owner provisioning (Mốc E6a): an in-memory provisioning_jobs table that enforces the same
CHECKs and unique indexes as migration 0003 (so a use case that breaks one fails in a unit test), and a
unit of work that rolls back everything the E6 fakes write."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field

from sqlalchemy.exc import IntegrityError

from app.models.family.entities import ProvisioningJob
from tests.fakes import FakeTx, _DbError

LIVE = ("PENDING", "RUNNING", "FAILED_RETRYABLE")


@dataclass
class FakeProvisioningRepo:
    calls: list[str] = field(default_factory=list)
    jobs: dict[uuid.UUID, ProvisioningJob] = field(default_factory=dict)
    blind_blocking: bool = False  # list_blocking answers "nothing": only the unique indexes can stop a job

    def _check(self, job: ProvisioningJob) -> None:
        """The CHECK constraints of provisioning_jobs (0003)."""
        assert job.firebase_uid == f"own-{job.job_id}", "provisioning_jobs_firebase_uid_check"
        assert job.status in ("PENDING", "RUNNING", "SUCCEEDED", "FAILED_RETRYABLE", "FAILED"), "status_check"
        assert job.attempt_count >= 0, "attempt_count_check"
        assert (not job.needs_cleanup) or (job.status == "FAILED" and job.firebase_user_created), (
            "provisioning_jobs_needs_cleanup_check"
        )
        assert job.status != "RUNNING" or job.lease_expires_at is not None, "provisioning_jobs_running_lease_check"

    def _unique(self, candidate: ProvisioningJob) -> None:
        for other in self.jobs.values():
            if other.job_id == candidate.job_id:
                continue
            if other.clan_id == candidate.clan_id and (other.status in LIVE + ("SUCCEEDED",) or other.needs_cleanup):
                if candidate.status in LIVE + ("SUCCEEDED",) or candidate.needs_cleanup:
                    raise IntegrityError("INSERT provisioning_jobs", {}, _DbError("uq_provisioning_job_live_per_clan"))
            if other.email.lower() == candidate.email.lower() and (other.status in LIVE or other.needs_cleanup):
                if candidate.status in LIVE or candidate.needs_cleanup:
                    raise IntegrityError("INSERT provisioning_jobs", {}, _DbError("uq_provisioning_job_live_email"))

    async def insert_pending(self, *, job_id, clan_id, requested_by, email, display_name, phone, now):
        self.calls.append("job.insert_pending")
        job = ProvisioningJob(
            job_id=job_id, job_type="OWNER_PROVISIONING", clan_id=clan_id, status="PENDING",
            requested_by=requested_by, email=email, display_name=display_name, phone=phone,
            firebase_uid=f"own-{job_id}", firebase_user_created=False, needs_cleanup=False, attempt_count=0,
            created_at=now, updated_at=now,
        )
        self._unique(job)
        self._check(job)
        self.jobs[job_id] = job
        return job

    async def get(self, job_id):
        self.calls.append("job.get")
        return self.jobs.get(job_id)

    async def lock(self, job_id):
        self.calls.append("job.lock")
        return self.jobs.get(job_id)

    @staticmethod
    def _filtered(rows, clan_id, status):
        return [j for j in rows if (clan_id is None or j.clan_id == clan_id) and (status is None or j.status == status)]

    async def list_page(self, *, clan_id, status, limit, offset):
        self.calls.append("job.list_page")
        rows = self._filtered(self.jobs.values(), clan_id, status)
        rows.sort(key=lambda j: (j.created_at, str(j.job_id)), reverse=True)  # newest first
        return rows[offset: offset + limit]

    async def count(self, *, clan_id, status):
        self.calls.append("job.count")
        return len(self._filtered(self.jobs.values(), clan_id, status))

    async def latest_for_clan(self, clan_id):
        self.calls.append("job.latest_for_clan")
        mine = [j for j in self.jobs.values() if j.clan_id == clan_id]
        return max(mine, key=lambda j: (j.created_at, str(j.job_id)), default=None)

    async def list_blocking(self, *, clan_id, email):
        self.calls.append("job.list_blocking")
        if self.blind_blocking:
            return []
        out = []
        for j in self.jobs.values():
            related = j.clan_id == clan_id or j.email.lower() == email.lower()
            blocking = j.status in LIVE or j.needs_cleanup or (j.status == "SUCCEEDED" and j.clan_id == clan_id)
            if related and blocking:
                out.append(j)
        return sorted(out, key=lambda j: (j.created_at, str(j.job_id)))

    async def mark_running(self, job, *, now, lease_expires_at):
        self.calls.append("job.mark_running")
        job.status, job.attempt_count, job.lease_expires_at = "RUNNING", job.attempt_count + 1, lease_expires_at
        job.error_code, job.updated_at = None, now
        self._check(job)

    async def mark_firebase_user_created(self, job, *, now, lease_expires_at):
        self.calls.append("job.mark_created")
        job.firebase_user_created, job.lease_expires_at, job.updated_at = True, lease_expires_at, now
        self._check(job)

    async def finish_succeeded(self, job, *, user_id, now):
        self.calls.append("job.finish_succeeded")
        job.status, job.user_id, job.lease_expires_at, job.error_code = "SUCCEEDED", user_id, None, None
        job.needs_cleanup, job.completed_at, job.updated_at = False, now, now
        self._check(job)

    async def finish_retryable(self, job, *, error_code, now):
        self.calls.append("job.finish_retryable")
        job.status, job.lease_expires_at, job.error_code, job.updated_at = "FAILED_RETRYABLE", None, error_code, now
        self._check(job)

    async def finish_failed_needing_cleanup(self, job, *, error_code, now):
        self.calls.append("job.finish_failed")
        job.status, job.firebase_user_created, job.needs_cleanup = "FAILED", True, True
        job.lease_expires_at, job.error_code, job.completed_at, job.updated_at = None, error_code, now, now
        self._check(job)

    async def finish_failed(self, job, *, error_code, now):
        self.calls.append("job.finish_failed_untouched")
        job.status, job.needs_cleanup, job.lease_expires_at = "FAILED", False, None
        job.error_code, job.completed_at, job.updated_at = error_code, now, now
        self._check(job)

    async def finish_cleanup(self, job, *, now):
        self.calls.append("job.finish_cleanup")
        job.needs_cleanup, job.firebase_user_created, job.updated_at = False, False, now
        self._check(job)


class OwnerTx(FakeTx):
    """FakeTx that also rolls back jobs, users, credentials, roles, memberships and ownership, and can say
    whether UNCOMMITTED work is open (used to prove no transaction is held while Firebase is called)."""

    def __init__(self, *, idem=None, family=None, users=None, jobs=None) -> None:
        super().__init__(idem=idem, family=family, users=users)
        self.jobs = jobs
        self._baseline_fp = None

    @staticmethod
    def _state(objects):
        """{id: (object, its column values)}: restored into the SAME object on rollback."""
        return {
            k: (v, {a: getattr(v, a) for a in v.__mapper__.column_attrs.keys()}) for k, v in objects.items()
        }

    @staticmethod
    def _restore(objects, saved) -> None:
        objects.clear()
        for k, (obj, values) in saved.items():
            for name, value in values.items():
                setattr(obj, name, value)
            objects[k] = obj

    def _extra(self):
        return {
            "jobs": {k: copy.copy(v) for k, v in self.jobs.jobs.items()},
            "users": self._state(self.users.users),
            "creds": self._state(self.users.creds),
            "sessions": self._state(self.users.sessions),
            "clan_state": self._state(self.family.clans),
            "sub_state": self._state({s.subscription_id: s for s in self.family.subscriptions}),
            "roles": list(self.users.roles),
            "memberships": list(self.family.memberships),
            "owners": list(self.family.owners),
        }

    def _fp(self):
        jobs = tuple(sorted(
            (str(j.job_id), j.status, j.attempt_count, j.firebase_user_created, j.needs_cleanup, j.error_code)
            for j in self.jobs.jobs.values()
        ))
        return (
            jobs, tuple((r.status, r.resource_id) for r in self.idem.rows), len(self.family.clans),
            len(self.users.users), len(self.users.creds), len(self.users.audit), len(self.users.roles),
            len(self.family.owners), len(self.family.memberships),
            tuple((str(k), c.must_change_password, c.temporary_password_issued_at, c.temporary_password_expires_at, c.updated_at)
                  for k, c in sorted(self.users.creds.items(), key=lambda kv: str(kv[0]))),
            tuple(sorted((s.revoked_at is not None) for s in self.users.sessions.values())),
            tuple(sorted((str(c.clan_id), c.status, c.activated_at) for c in self.family.clans.values())),
            tuple(sorted((str(s.subscription_id), s.status, s.starts_at, s.ends_at) for s in self.family.subscriptions)),
        )

    def uncommitted(self) -> bool:
        return self._fp() != self._baseline_fp

    def begin(self) -> None:
        super().begin()
        self._baseline["extra"] = self._extra()
        self._baseline_fp = self._fp()

    async def commit(self) -> None:
        await super().commit()
        self._baseline["extra"] = self._extra()
        self._baseline_fp = self._fp()

    async def rollback(self) -> None:
        await super().rollback()
        extra = (self._baseline or {}).get("extra")
        if extra is None:
            return
        self.jobs.jobs.clear()
        self.jobs.jobs.update({k: copy.copy(v) for k, v in extra["jobs"].items()})
        self._restore(self.users.users, extra["users"])
        self._restore(self.users.creds, extra["creds"])
        self._restore(self.users.sessions, extra["sessions"])
        self._restore(dict(self.family.clans), extra["clan_state"])  # same objects, their columns put back
        self._restore({s.subscription_id: s for s in self.family.subscriptions}, extra["sub_state"])
        self.users.roles[:] = extra["roles"]
        self.family.memberships[:] = extra["memberships"]
        self.family.owners[:] = extra["owners"]
