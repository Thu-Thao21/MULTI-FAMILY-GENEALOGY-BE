"""Database access for `provisioning_jobs` (migration 0003). Only flushes: never commits.

A job is the durable record of "create the Owner account": a Firebase user and a set of rows that
no single transaction can cover. It holds NO password. The state machine (who may claim a job,
which transitions exist) lives in app/controllers/family_management/provisioning_state.py; this
class only reads and writes rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.family.entities import ProvisioningJob

LIVE_STATUSES = ("PENDING", "RUNNING", "FAILED_RETRYABLE")


class ProvisioningRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_pending(
        self,
        *,
        job_id: uuid.UUID,
        clan_id: uuid.UUID,
        requested_by: uuid.UUID,
        email: str,
        display_name: str,
        phone: str | None,
        now: datetime,
    ) -> ProvisioningJob:
        """A new job in PENDING. firebase_uid is always own-<job_id> (a CHECK enforces it)."""
        job = ProvisioningJob(
            job_id=job_id,
            job_type="OWNER_PROVISIONING",
            clan_id=clan_id,
            status="PENDING",
            requested_by=requested_by,
            email=email,
            display_name=display_name,
            phone=phone,
            firebase_uid=f"own-{job_id}",
            firebase_user_created=False,
            needs_cleanup=False,
            attempt_count=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def get(self, job_id: uuid.UUID) -> ProvisioningJob | None:
        stmt = select(ProvisioningJob).where(ProvisioningJob.job_id == job_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def lock(self, job_id: uuid.UUID) -> ProvisioningJob | None:
        """The job row, locked FOR NO KEY UPDATE and re-read from the database."""
        stmt = (
            select(ProvisioningJob)
            .where(ProvisioningJob.job_id == job_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_blocking(self, *, clan_id: uuid.UUID, email: str) -> list[ProvisioningJob]:
        """Jobs that stand in the way of a new one: for this clan, or for this e-mail (any case),
        and still LIVE (PENDING, RUNNING, FAILED_RETRYABLE), SUCCEEDED (clan only), or waiting for a
        Firebase clean-up. Oldest first."""
        stmt = (
            select(ProvisioningJob)
            .where(
                or_(ProvisioningJob.clan_id == clan_id, func.lower(ProvisioningJob.email) == email.lower()),
                or_(
                    ProvisioningJob.status.in_(LIVE_STATUSES),
                    ProvisioningJob.needs_cleanup.is_(True),
                    (ProvisioningJob.status == "SUCCEEDED") & (ProvisioningJob.clan_id == clan_id),
                ),
            )
            .order_by(ProvisioningJob.created_at, ProvisioningJob.job_id)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # ----- transitions: they write the fields of ONE locked row and flush -----

    async def mark_running(self, job: ProvisioningJob, *, now: datetime, lease_expires_at: datetime) -> None:
        job.status = "RUNNING"
        job.attempt_count = job.attempt_count + 1
        job.lease_expires_at = lease_expires_at
        job.error_code = None
        job.updated_at = now
        await self._session.flush()

    async def mark_firebase_user_created(
        self, job: ProvisioningJob, *, now: datetime, lease_expires_at: datetime
    ) -> None:
        job.firebase_user_created = True
        job.lease_expires_at = lease_expires_at  # a heartbeat: the run is alive and past Firebase
        job.updated_at = now
        await self._session.flush()

    async def finish_succeeded(self, job: ProvisioningJob, *, user_id: uuid.UUID, now: datetime) -> None:
        job.status = "SUCCEEDED"
        job.user_id = user_id
        job.lease_expires_at = None
        job.error_code = None
        job.needs_cleanup = False
        job.completed_at = now
        job.updated_at = now
        await self._session.flush()

    async def finish_retryable(self, job: ProvisioningJob, *, error_code: str, now: datetime) -> None:
        job.status = "FAILED_RETRYABLE"
        job.lease_expires_at = None
        job.error_code = error_code
        job.updated_at = now
        await self._session.flush()

    async def finish_failed_needing_cleanup(
        self, job: ProvisioningJob, *, error_code: str, now: datetime
    ) -> None:
        """FAILED for good. needs_cleanup and firebase_user_created are set to TRUE first, before any
        delete is tried: we may not know whether the Firebase user exists, and the flags keep the clan
        and the e-mail blocked until the delete is confirmed (the CHECK ties the two flags together)."""
        job.status = "FAILED"
        job.firebase_user_created = True
        job.needs_cleanup = True
        job.lease_expires_at = None
        job.error_code = error_code
        job.completed_at = now
        job.updated_at = now
        await self._session.flush()

    async def finish_failed(self, job: ProvisioningJob, *, error_code: str, now: datetime) -> None:
        """FAILED for good WITHOUT a clean-up (UID_MISMATCH: the Firebase user is not ours to delete).
        firebase_user_created is left as it was; needs_cleanup stays false, so nothing is blocked."""
        job.status = "FAILED"
        job.needs_cleanup = False
        job.lease_expires_at = None
        job.error_code = error_code
        job.completed_at = now
        job.updated_at = now
        await self._session.flush()

    async def finish_cleanup(self, job: ProvisioningJob, *, now: datetime) -> None:
        """The Firebase delete is confirmed (deleted, or there was none): lower both flags."""
        job.needs_cleanup = False
        job.firebase_user_created = False
        job.updated_at = now
        await self._session.flush()
