"""Reading what PostgreSQL says about an error (psycopg diagnostics), without parsing messages."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

LOCK_NOT_AVAILABLE = "55P03"  # lock_timeout expired while waiting for a lock


def constraint_name(exc: IntegrityError) -> str | None:
    """The unique index, constraint or foreign key the database reports (psycopg diagnostics)."""
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def sqlstate(exc: BaseException) -> str | None:
    """The SQLSTATE of a database error (through SQLAlchemy's `orig`), or None."""
    inner = getattr(exc, "orig", exc)
    state = getattr(inner, "sqlstate", None) or getattr(getattr(inner, "diag", None), "sqlstate", None)
    return str(state) if state else None


def lock_wait_timed_out(exc: BaseException) -> bool:
    """True when the error is `lock_timeout` expiring (SQLSTATE 55P03)."""
    return sqlstate(exc) == LOCK_NOT_AVAILABLE
