"""How the concurrency tests report an error that is NOT an application error (E4b).

A request in a concurrency test returns 'ok', an application error code, or
'ERROR:<type>:<sqlstate or no-sqlstate>:<first 60 characters of the message>'. The sqlstate is what
tells infrastructure from a real bug at a glance:

  no-sqlstate   the connection itself broke (Neon closed it): an infrastructure problem
  40P01         deadlock detected         } these are bugs in the code under test,
  23xxx         integrity violation       } and they are NEVER retried or excused
  55P03         lock not available        }

There is deliberately NO retry anywhere: a test that retried a deadlock or a unique violation would
hide the very bug it exists to find.

The message is scrubbed first: connection strings, host / user / password / dbname fragments and
long hex or base64-looking tokens are removed, so a connection problem can never leak a secret
into a test report.
"""

from __future__ import annotations

import re

NO_SQLSTATE = "no-sqlstate"
MESSAGE_LIMIT = 60

_SCRUBBERS = (
    (re.compile(r"\S+://\S+"), "<url>"),  # any connection string / URL
    (re.compile(r"\b(?:host|hostaddr|user|password|dbname|port|channel_binding|sslmode)=\S+", re.I), "<conn>"),
    (re.compile(r"\b[\w.-]+\.neon\.tech\b", re.I), "<host>"),
    (re.compile(r"\b[A-Za-z0-9+/_-]{32,}={0,2}"), "<token>"),
)


def sqlstate_of(exc: BaseException) -> str:
    """The SQLSTATE of a database error (through SQLAlchemy's `orig`), or 'no-sqlstate'."""
    inner = getattr(exc, "orig", exc)
    state = getattr(inner, "sqlstate", None) or getattr(getattr(inner, "diag", None), "sqlstate", None)
    return str(state) if state else NO_SQLSTATE


def scrubbed_message(exc: BaseException, limit: int = MESSAGE_LIMIT) -> str:
    inner = getattr(exc, "orig", exc)
    text = " ".join(str(inner).split())  # one line
    for pattern, replacement in _SCRUBBERS:
        text = pattern.sub(replacement, text)
    return text[:limit]


def describe_error(exc: BaseException) -> str:
    """'ERROR:<type>:<sqlstate or no-sqlstate>:<first 60 characters of the scrubbed message>'."""
    inner = getattr(exc, "orig", exc)
    return f"ERROR:{type(inner).__name__}:{sqlstate_of(exc)}:{scrubbed_message(exc)}"


def is_error(result) -> bool:
    return str(result).startswith("ERROR:")


def is_infrastructure_error(result) -> bool:
    """True for a report whose connection broke (no sqlstate): useful for the summary line only."""
    parts = str(result).split(":", 3)
    return len(parts) >= 3 and parts[0] == "ERROR" and parts[2] == NO_SQLSTATE
