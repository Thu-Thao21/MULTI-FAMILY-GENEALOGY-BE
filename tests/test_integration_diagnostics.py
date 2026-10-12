"""How a concurrency test reports a non-application error (E4b): 'ERROR:<type>:<sqlstate or
no-sqlstate>:<first 60 characters of the scrubbed message>'. No database needed."""

from __future__ import annotations

import re

import psycopg.errors
import pytest
from sqlalchemy.exc import OperationalError

from tests.integration.diagnostics import (
    MESSAGE_LIMIT,
    describe_error,
    is_error,
    is_infrastructure_error,
    scrubbed_message,
    sqlstate_of,
)

FORMAT = re.compile(r"^ERROR:[A-Za-z]+:(no-sqlstate|[0-9A-Z]{5}):.{0,60}$")


def wrapped(inner: Exception) -> OperationalError:
    return OperationalError("SELECT 1", {}, inner)  # what SQLAlchemy raises around a driver error


def test_a_deadlock_carries_its_sqlstate_even_through_sqlalchemy():
    inner = psycopg.errors.DeadlockDetected("deadlock detected")
    for exc in (inner, wrapped(inner)):
        assert describe_error(exc).startswith("ERROR:DeadlockDetected:40P01:deadlock detected")
        assert sqlstate_of(exc) == "40P01"


@pytest.mark.parametrize("error, state", [
    (psycopg.errors.UniqueViolation("duplicate key"), "23505"),
    (psycopg.errors.ForeignKeyViolation("fk"), "23503"),
    (psycopg.errors.LockNotAvailable("lock timeout"), "55P03"),
    (psycopg.errors.SerializationFailure("could not serialize"), "40001"),
])
def test_real_bugs_show_their_own_sqlstate(error, state):
    assert sqlstate_of(error) == sqlstate_of(wrapped(error)) == state
    assert not is_infrastructure_error(describe_error(wrapped(error)))


def test_a_dropped_connection_has_no_sqlstate_and_is_recognised_as_infrastructure():
    inner = psycopg.OperationalError("consuming input failed: server closed the connection unexpectedly")
    text = describe_error(wrapped(inner))
    assert text.startswith("ERROR:OperationalError:no-sqlstate:consuming input failed")
    assert is_infrastructure_error(text) and is_error(text)


def test_an_error_that_is_not_a_database_error_has_no_sqlstate():
    assert describe_error(KeyError("x")).startswith("ERROR:KeyError:no-sqlstate:")
    assert describe_error(RuntimeError("boom")) == "ERROR:RuntimeError:no-sqlstate:boom"


@pytest.mark.parametrize("message", [
    'connection failed: postgresql://app_user:S3cretPass@ep-cool-123-pooler.us-east-2.aws.neon.tech/db?sslmode=require',
    'connection to server at "ep-cool-123-pooler.us-east-2.aws.neon.tech" (10.1.2.3), port 5432 failed',
    "host=ep-cool-123.neon.tech user=app_user password=S3cretPass dbname=mfgms_ai sslmode=require",
    "token abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGH leaked",
])
def test_the_message_never_carries_connection_details_or_secrets(message):
    out = describe_error(wrapped(psycopg.OperationalError(message)))
    for secret in ("S3cretPass", "app_user", "neon.tech", "ep-cool", "mfgms_ai", "abcdefghijklmnopqrstuvwxyz", "postgresql://"):
        assert secret not in out, (secret, out)
    assert FORMAT.match(out), out


def test_the_message_is_one_line_and_at_most_60_characters():
    long = "first line\nsecond line " + "word " * 60  # (a long unbroken run would be scrubbed as a token)
    out = scrubbed_message(psycopg.OperationalError(long))
    assert "\n" not in out and len(out) == MESSAGE_LIMIT
    assert FORMAT.match(describe_error(psycopg.OperationalError(long)))


def test_application_codes_are_not_errors():
    for result in ("ok", "STATE_CONFLICT", "DUPLICATE_RESOURCE", "IDEMPOTENCY_KEY_CONFLICT"):
        assert not is_error(result) and not is_infrastructure_error(result)


def test_there_is_no_retry_helper_in_the_diagnostics_module():
    """The approved design reports and never retries: a retried deadlock would hide the bug."""
    import tests.integration.diagnostics as module

    assert not [name for name in dir(module) if "retry" in name.lower() or "attempt" in name.lower()]
