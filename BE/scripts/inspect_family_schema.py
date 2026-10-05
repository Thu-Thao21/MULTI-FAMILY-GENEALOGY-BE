"""
Read-only schema inspect for Sprint 1 B2 family tables.

Only SELECT against information_schema / pg_catalog.
Never prints DATABASE_URL or any row data. Column defaults are printed only when
they match a known-safe pattern (functions, booleans, numbers, short enum-like
literals); anything else is shown as <redacted>.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

TABLES = (
    "business_registrations",
    "registration_status_history",
    "registration_attachments",
    "clans",
    "clan_profiles",
    "clan_subscriptions",
    "subscription_plans",
    "plan_feature_limits",
    "clan_ownership_history",
    "clan_memberships",
    "family_admin_assignments",
    "family_admin_permissions",
    "account_invitations",
    "password_reset_tokens",
    "person_account_links",
    "support_access_grants",
    "email_delivery_logs",
    "email_delivery_attempts",
)

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "docs" / "schema_family.txt"

_SAFE_DEFAULT_PATTERNS = (
    re.compile(r"^[a-z_]+\(\)$"),  # gen_random_uuid(), now()
    re.compile(r"^CURRENT_(TIMESTAMP|DATE)$"),
    re.compile(r"^(true|false)$"),
    re.compile(r"^-?\d+(\.\d+)?$"),
    re.compile(r"^'[A-Za-z0-9_]{0,40}'::[a-z ]+(\[\])?$"),  # 'ACTIVE'::character varying
    re.compile(r"^'\{\}'::jsonb$|^'\[\]'::jsonb$"),
    re.compile(r"^nextval\('[a-z0-9_]+'::regclass\)$"),
    re.compile(r"^\(?-?\d+\)?::(integer|numeric|bigint|smallint)$"),
)


def safe_default(value: str | None) -> str:
    if value is None:
        return ""
    v = value.strip()
    if any(p.match(v) for p in _SAFE_DEFAULT_PATTERNS):
        return v
    return "<redacted>"


Q_EXISTS = """
SELECT 1 FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = :t AND table_type = 'BASE TABLE'
"""

Q_COLUMNS = """
SELECT column_name, data_type, udt_name, character_maximum_length,
       numeric_precision, numeric_scale, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = :t
ORDER BY ordinal_position
"""

Q_CONSTRAINTS = """
SELECT con.conname, con.contype, pg_get_constraintdef(con.oid)
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
WHERE nsp.nspname = 'public' AND rel.relname = :t
ORDER BY con.contype, con.conname
"""

Q_INDEXES = """
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public' AND tablename = :t
ORDER BY indexname
"""

_CONTYPE_LABEL = {
    "p": "primary key",
    "f": "foreign keys",
    "c": "check constraints",
    "u": "unique constraints",
    "x": "exclusion constraints",
}


async def inspect() -> str:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    lines: list[str] = []
    missing: list[str] = []
    add = lines.append

    try:
        async with engine.connect() as conn:
            meta = (await conn.execute(text("SELECT current_database(), current_schema()"))).one()
            add("MFGMS AI — family schema inspect (read-only)")
            add(f"database={meta[0]}  schema={meta[1]}")
            add("NOTE: connection string, row data and non-trivial defaults are omitted.")
            add("")

            for table in TABLES:
                if not (await conn.execute(text(Q_EXISTS), {"t": table})).first():
                    missing.append(table)
                    continue

                add("=" * 72)
                add(f"TABLE {table}")
                add("- columns (name | data_type | udt_name | len/prec | nullable | default)")
                for c in (await conn.execute(text(Q_COLUMNS), {"t": table})).all():
                    if c[3] is not None:
                        size = f"len={c[3]}"
                    elif c[1] == "numeric":
                        size = f"prec={c[4]},{c[5]}"
                    else:
                        size = "-"
                    add(
                        f"  {c[0]} | {c[1]} | {c[2]} | {size} | nullable={c[6]} "
                        f"| default={safe_default(c[7])}"
                    )

                cons = (await conn.execute(text(Q_CONSTRAINTS), {"t": table})).all()
                for code in ("p", "f", "u", "c", "x"):
                    group = [c for c in cons if c[1] == code]
                    if code == "x" and not group:
                        continue
                    add(f"- {_CONTYPE_LABEL[code]}")
                    if not group:
                        add("  (none)")
                    for name, _, definition in group:
                        add(f"  {name}: {definition}")

                add("- indexes")
                idx = (await conn.execute(text(Q_INDEXES), {"t": table})).all()
                if not idx:
                    add("  (none)")
                for name, definition in idx:
                    add(f"  {name}: {definition}")
                add("")

            add("=" * 72)
            add("MISSING TABLES (not found in public schema, not mapped)")
            add("  " + (", ".join(missing) if missing else "(none)"))
    finally:
        await engine.dispose()

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    report = asyncio.run(inspect())
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"[saved] {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
