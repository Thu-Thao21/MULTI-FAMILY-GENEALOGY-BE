"""The state machine of an Owner provisioning job (Mốc E6a): pure functions, no database."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.controllers.family_management import provisioning_state as st

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
LEASE, MAX = 90, 5


def job(status, *, attempt=1, lease=None, created=None, needs_cleanup=False):
    return SimpleNamespace(status=status, attempt_count=attempt, lease_expires_at=lease,
                           created_at=created or NOW - timedelta(hours=1), needs_cleanup=needs_cleanup)


def decide(j, **kw):
    return st.decide_claim(j, NOW, lease_seconds=LEASE, max_attempts=MAX, **kw)


def denied(j, **kw) -> st.ClaimDenied:
    with pytest.raises(st.ClaimDenied) as exc:
        decide(j, **kw)
    return exc.value


# ------------------------------------------------------------------ claim


def test_the_job_a_request_has_just_created_starts_even_though_it_is_fresh():
    assert decide(job("PENDING", attempt=0, created=NOW), fresh=True) == st.START


def test_a_pending_job_that_nobody_started_is_stuck_only_after_the_lease():
    assert decide(job("PENDING", attempt=0, created=NOW - timedelta(seconds=LEASE))) == st.START
    assert decide(job("PENDING", attempt=0, created=NOW - timedelta(hours=1))) == st.START
    young = denied(job("PENDING", attempt=0, created=NOW - timedelta(seconds=LEASE - 1)))
    assert young.reason == "PENDING_NOT_STUCK" and young.retry_after == 1


def test_a_fresh_pending_job_is_not_stuck_for_a_retry_but_is_for_its_own_request():
    j = job("PENDING", attempt=0, created=NOW - timedelta(seconds=10))
    assert denied(j).retry_after == LEASE - 10
    assert decide(j, fresh=True) == st.START


def test_a_temporarily_failed_job_runs_again_until_the_attempts_run_out():
    assert decide(job("FAILED_RETRYABLE", attempt=MAX - 1)) == st.RETRY
    assert denied(job("FAILED_RETRYABLE", attempt=MAX)).reason == "ATTEMPTS_EXHAUSTED"
    assert denied(job("FAILED_RETRYABLE", attempt=MAX + 3)).reason == "ATTEMPTS_EXHAUSTED"


def test_a_running_job_is_taken_over_only_when_its_lease_has_run_out():
    assert decide(job("RUNNING", lease=NOW)) == st.TAKEOVER  # the lease ends exactly now
    assert decide(job("RUNNING", lease=NOW - timedelta(seconds=1))) == st.TAKEOVER
    held = denied(job("RUNNING", lease=NOW + timedelta(seconds=30)))
    assert held.reason == "LEASE_HELD" and held.retry_after == 31
    assert denied(job("RUNNING", lease=NOW + timedelta(milliseconds=1))).retry_after == 1


def test_a_running_job_without_a_lease_can_be_taken_over_but_not_past_the_maximum_attempts():
    assert decide(job("RUNNING", lease=None)) == st.TAKEOVER
    assert denied(job("RUNNING", attempt=MAX, lease=NOW - timedelta(seconds=1))).reason == "ATTEMPTS_EXHAUSTED"


def test_a_succeeded_job_is_final():
    assert denied(job("SUCCEEDED")).reason == "ALREADY_SUCCEEDED"


def test_a_failed_job_only_allows_the_cleanup_when_one_is_owed():
    assert decide(job("FAILED", needs_cleanup=True)) == st.CLEANUP_ONLY
    assert denied(job("FAILED", needs_cleanup=False)).reason == "FAILED_FINAL"


def test_an_unknown_status_is_denied():
    assert denied(job("SOMETHING_ELSE")).reason == "UNKNOWN_STATUS"


def test_a_denial_carries_a_short_code_and_nothing_about_the_job():
    exc = denied(job("RUNNING", lease=NOW + timedelta(seconds=5)))
    assert str(exc) == "LEASE_HELD" and "RUNNING" not in str(exc)


# ------------------------------------------------------------------ fencing


def test_fencing_is_about_the_attempt_and_the_status_not_the_lease():
    assert st.holds_attempt(job("RUNNING", attempt=3, lease=NOW - timedelta(days=1)), 3) is True  # lease long over, nobody replaced it
    assert st.holds_attempt(job("RUNNING", attempt=3, lease=NOW + timedelta(hours=1)), 3) is True
    assert st.holds_attempt(job("RUNNING", attempt=4), 3) is False  # replaced by a newer attempt
    assert st.holds_attempt(job("RUNNING", attempt=2), 3) is False
    for status in ("PENDING", "SUCCEEDED", "FAILED_RETRYABLE", "FAILED"):
        assert st.holds_attempt(job(status, attempt=3), 3) is False, status
    assert st.holds_attempt(None, 3) is False


def test_the_module_never_reads_the_clock_in_holds_attempt():
    import ast
    import inspect
    import textwrap

    function = ast.parse(textwrap.dedent(inspect.getsource(st.holds_attempt))).body[0]
    code = ast.Module(body=function.body[1:], type_ignores=[])  # (the docstring talks about the lease; the code must not)
    names = {n.id for n in ast.walk(code) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(code) if isinstance(n, ast.Attribute)}
    assert not {"lease_expires_at", "now", "datetime", "utcnow"} & names
    assert {"status", "attempt_count"} <= names


# ------------------------------------------------------------------ exhausted


@pytest.mark.parametrize("attempt, expected", [(1, False), (4, False), (5, True), (6, True)])
def test_a_temporary_failure_of_the_last_attempt_is_final(attempt, expected):
    assert st.exhausted(attempt, 5) is expected


def test_with_one_allowed_attempt_the_first_failure_is_final():
    assert st.exhausted(1, 1) is True
