"""The state machine of an Owner provisioning job (Mốc E6): pure functions, no database.

    PENDING --claim--> RUNNING --ok--> SUCCEEDED (final)
    RUNNING --temporary failure--> FAILED_RETRYABLE --claim--> RUNNING
    RUNNING --final failure--> FAILED (needs_cleanup until the Firebase delete is confirmed)
    PENDING that nobody started (older than the lease) --claim--> RUNNING
    RUNNING whose lease ran out --claim--> RUNNING (a takeover)
    FAILED + needs_cleanup --clean-up--> FAILED, needs_cleanup lowered

Fencing: a run may write its result only while the job is RUNNING and its attempt_count is still the
number the run was started with. Whether the lease has expired does NOT matter: a slow run that
nobody replaced may still finish, and a run that was replaced always finds a larger attempt_count.
"""

from __future__ import annotations

from datetime import datetime

PENDING = "PENDING"
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED_RETRYABLE = "FAILED_RETRYABLE"
FAILED = "FAILED"

START = "START"  # a PENDING job begins (a new job, or one left PENDING)
RETRY = "RETRY"  # FAILED_RETRYABLE runs again
TAKEOVER = "TAKEOVER"  # a RUNNING job whose lease ran out runs again
CLEANUP_ONLY = "CLEANUP_ONLY"  # FAILED with needs_cleanup: only the Firebase delete is done


class ClaimDenied(Exception):
    """The job cannot be claimed now. `reason` is a short code; retry_after is in seconds (or None)."""

    def __init__(self, reason: str, retry_after: int | None = None) -> None:
        super().__init__(reason)  # str(exc) stays free of job data
        self.reason = reason
        self.retry_after = retry_after


def decide_claim(
    job,
    now: datetime,
    *,
    lease_seconds: int,
    max_attempts: int,
    fresh: bool = False,
) -> str:
    """What claiming `job` means now, or ClaimDenied.

    fresh=True is the request that has just created the job: its PENDING is not "stuck".
    """
    status = job.status
    if status == SUCCEEDED:
        raise ClaimDenied("ALREADY_SUCCEEDED")
    if status == FAILED:
        if job.needs_cleanup:
            return CLEANUP_ONLY
        raise ClaimDenied("FAILED_FINAL")
    if status == PENDING:
        if not fresh and (now - job.created_at).total_seconds() < lease_seconds:
            remaining = lease_seconds - int((now - job.created_at).total_seconds())
            raise ClaimDenied("PENDING_NOT_STUCK", retry_after=max(1, remaining))
        return START
    if status == FAILED_RETRYABLE:
        if job.attempt_count >= max_attempts:
            raise ClaimDenied("ATTEMPTS_EXHAUSTED")
        return RETRY
    if status == RUNNING:
        if job.lease_expires_at is not None and job.lease_expires_at > now:
            remaining = int((job.lease_expires_at - now).total_seconds()) + 1
            raise ClaimDenied("LEASE_HELD", retry_after=max(1, remaining))
        if job.attempt_count >= max_attempts:
            raise ClaimDenied("ATTEMPTS_EXHAUSTED")
        return TAKEOVER
    raise ClaimDenied("UNKNOWN_STATUS")  # default deny


def decide_abandon(job, now: datetime, *, lease_seconds: int) -> None:
    """May an administrator give `job` up? Returns nothing, or raises ClaimDenied.

    Allowed: FAILED_RETRYABLE (even after the last attempt), PENDING that nobody started (older than
    the lease), RUNNING whose lease has run out. Never a RUNNING job with a live lease (a run may still
    be writing), never SUCCEEDED, never a FAILED job (it is final; one that still owes a clean-up is
    cleaned up by a retry)."""
    status = job.status
    if status == SUCCEEDED:
        raise ClaimDenied("ALREADY_SUCCEEDED")
    if status == FAILED:
        raise ClaimDenied("CLEANUP_PENDING" if job.needs_cleanup else "FAILED_FINAL")
    if status == PENDING:
        age = (now - job.created_at).total_seconds()
        if age < lease_seconds:
            raise ClaimDenied("PENDING_NOT_STUCK", retry_after=max(1, lease_seconds - int(age)))
        return
    if status == FAILED_RETRYABLE:
        return
    if status == RUNNING:
        if job.lease_expires_at is not None and job.lease_expires_at > now:
            raise ClaimDenied("LEASE_HELD", retry_after=max(1, int((job.lease_expires_at - now).total_seconds()) + 1))
        return
    raise ClaimDenied("UNKNOWN_STATUS")  # default deny


def holds_attempt(job, attempt: int) -> bool:
    """Fencing: still the run that was started as `attempt`. NOT about the lease."""
    return job is not None and job.status == RUNNING and job.attempt_count == attempt


def exhausted(attempt: int, max_attempts: int) -> bool:
    """A temporary failure of attempt N >= max_attempts is final: the job becomes FAILED."""
    return attempt >= max_attempts
