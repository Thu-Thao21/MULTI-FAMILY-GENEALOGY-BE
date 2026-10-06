"""Fingerprint of the database a DATABASE_URL points to.

The fingerprint is the first 8 hex characters of sha256("<host>/<database>"). It lets a person
confirm WHICH database a migration is about to touch (a Neon branch has the same database name
as its parent, so the name alone does not tell them apart) without ever printing the host, the
user or the password.

Read-only, makes no connection:

    .venv\\Scripts\\python.exe -m app.db.fingerprint

Output messages are ASCII on purpose: a Windows console in cp1252 cannot print anything else.
"""

from __future__ import annotations

import hashlib

from sqlalchemy.engine import make_url

FINGERPRINT_LENGTH = 8


def database_fingerprint(url: str) -> str:
    """First 8 hex chars of sha256 over "<host>/<database>". Never includes user or password."""
    parsed = make_url(url)
    material = f"{parsed.host or ''}/{parsed.database or ''}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


def database_name(url: str) -> str:
    return make_url(url).database or ""


def target_summary(url: str) -> str:
    """"database=<name> fingerprint=<8 hex>": safe to print and to log."""
    return f"database={database_name(url)} fingerprint={database_fingerprint(url)}"


def main() -> int:
    from app.core.config import settings

    print(target_summary(settings.DATABASE_URL))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
