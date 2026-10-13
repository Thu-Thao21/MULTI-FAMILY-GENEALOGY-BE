"""Safety guard for Alembic runs that touch a database (used by alembic/env.py).

A run is allowed only when BOTH hold:
  1. ALLOW_MIGRATE=1
  2. MIGRATE_EXPECT_FINGERPRINT equals the fingerprint of the database DATABASE_URL points to
     (see app/db/fingerprint.py; get it with `python -m app.db.fingerprint`).

When a condition fails the message names the current database and its fingerprint so the
person can confirm the target. It never contains the host, the user or the password.
Messages are ASCII on purpose (Windows consoles in cp1252 cannot print anything else).
"""

from __future__ import annotations

from collections.abc import Mapping

from app.db.fingerprint import database_fingerprint, target_summary

ENV_ALLOW = "ALLOW_MIGRATE"
ENV_FINGERPRINT = "MIGRATE_EXPECT_FINGERPRINT"


def check_guard(url: str, environ: Mapping[str, str]) -> str | None:
    """None when the run is allowed; otherwise a printable refusal message."""
    current = target_summary(url)
    if environ.get(ENV_ALLOW) != "1":
        return (
            f"Refusing to run: {ENV_ALLOW}=1 is not set. Alembic touches the database only on purpose.\n"
            f"Current target: {current}\n"
            f"If this is the intended database, set {ENV_ALLOW}=1 and "
            f"{ENV_FINGERPRINT}=<fingerprint above>."
        )
    expected = (environ.get(ENV_FINGERPRINT) or "").strip().lower()
    if not expected:
        return (
            f"Refusing to run: {ENV_FINGERPRINT} is not set.\n"
            f"Current target: {current}\n"
            f"If this is the intended database, set {ENV_FINGERPRINT}=<fingerprint above>."
        )
    if expected != database_fingerprint(url):
        return (
            f"Refusing to run: {ENV_FINGERPRINT} does not match the current target.\n"
            f"Current target: {current}\n"
            "DATABASE_URL points somewhere else than the database you confirmed. Nothing was changed."
        )
    return None


def enforce_guard(url: str, environ: Mapping[str, str]) -> None:
    """Raise SystemExit(<message>) (exit code 1, message on stderr) when the run is not allowed."""
    refusal = check_guard(url, environ)
    if refusal is not None:
        raise SystemExit(refusal)
