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

    def _extra(self):
        return {
            "jobs": {k: copy.copy(v) for k, v in self.jobs.jobs.items()},
            "users": dict(self.users.users),
            "creds": dict(self.users.creds),
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
        self.users.users.clear()
        self.users.users.update(extra["users"])
        self.users.creds.clear()
        self.users.creds.update(extra["creds"])
        self.users.roles[:] = extra["roles"]
        self.family.memberships[:] = extra["memberships"]
        self.family.owners[:] = extra["owners"]
