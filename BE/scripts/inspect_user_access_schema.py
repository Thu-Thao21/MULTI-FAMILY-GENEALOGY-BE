"""
Read-only schema inspect for Sprint 1 B1 user-access tables.

Only SELECT against information_schema / pg_catalog.
Does not print DATABASE_URL or any row data.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

TABLES = (
    "users",
    "credential_metadata",
    "user_sessions",
    "login_history",
    "audit_logs",
    "roles",
    "permissions",
    "role_permissions",
    "user_roles",
)

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "docs" / "schema_user_access.txt"


async def inspect() -> str:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    lines: list[str] = []

    def add(line: str = "") -> None:
        lines.append(line)

    try:
        async with engine.connect() as conn:
            meta = (
                await conn.execute(
                    text("SELECT current_database(), current_schema()")
                )
            ).one()
            add("MFGMS AI — user_access schema inspect (read-only)")
            add(f"database={meta[0]}  schema={meta[1]}")
            add("NOTE: connection string and row data are intentionally omitted.")
            add("")

            for table in TABLES:
                exists = (
                    await conn.execute(
                        text(
                            """
                            SELECT 1
                            FROM information_schema.tables
                            WHERE table_schema = 'public'
                              AND table_name = :table
                              AND table_type = 'BASE TABLE'
                            """
                        ),
                        {"table": table},
                    )
                ).first()
                add("=" * 72)
                if not exists:
                    add(f"TABLE {table}: NOT FOUND in public schema")
                    add("")
                    continue

                add(f"TABLE {table}")
                add(
                    "- columns (name | data_type | udt_name | max_len | is_nullable | column_default)"
                )
                cols = (
                    await conn.execute(
                        text(
                            """
                            SELECT column_name, data_type, udt_name,
                                   character_maximum_length, is_nullable, column_default
                            FROM information_schema.columns
                            WHERE table_schema = 'public' AND table_name = :table
                            ORDER BY ordinal_position
                            """
                        ),
                        {"table": table},
                    )
                ).all()
                for col in cols:
                    default = col[5] if col[5] is not None else ""
                    max_len = col[3] if col[3] is not None else "-"
                    add(
                        f"  {col[0]} | {col[1]} | {col[2]} | max_len={max_len} "
                        f"| nullable={col[4]} | default={default}"
                    )

                add("- primary key")
                pks = (
                    await conn.execute(
                        text(
                            """
                            SELECT kcu.column_name, tc.constraint_name
                            FROM information_schema.table_constraints tc
                            JOIN information_schema.key_column_usage kcu
                              ON tc.constraint_name = kcu.constraint_name
                             AND tc.table_schema = kcu.table_schema
                            WHERE tc.table_schema = 'public'
                              AND tc.table_name = :table
                              AND tc.constraint_type = 'PRIMARY KEY'
                            ORDER BY kcu.ordinal_position
                            """
                        ),
                        {"table": table},
                    )
                ).all()
                if pks:
                    for pk in pks:
                        add(f"  {pk[0]} (constraint={pk[1]})")
                else:
                    add("  (none)")

                add("- foreign keys")
                fks = (
                    await conn.execute(
                        text(
                            """
                            SELECT
                              tc.constraint_name,
                              kcu.column_name,
                              ccu.table_name AS foreign_table,
                              ccu.column_name AS foreign_column
                            FROM information_schema.table_constraints tc
                            JOIN information_schema.key_column_usage kcu
                              ON tc.constraint_name = kcu.constraint_name
                             AND tc.table_schema = kcu.table_schema
                            JOIN information_schema.constraint_column_usage ccu
                              ON ccu.constraint_name = tc.constraint_name
                             AND ccu.table_schema = tc.table_schema
                            WHERE tc.table_schema = 'public'
                              AND tc.table_name = :table
                              AND tc.constraint_type = 'FOREIGN KEY'
                            ORDER BY tc.constraint_name, kcu.ordinal_position
                            """
                        ),
                        {"table": table},
                    )
                ).all()
                if fks:
                    for fk in fks:
                        add(
                            f"  {fk[1]} -> {fk[2]}.{fk[3]} (constraint={fk[0]})"
                        )
                else:
                    add("  (none)")

                add("- check constraints")
                checks = (
                    await conn.execute(
                        text(
                            """
                            SELECT con.conname, pg_get_constraintdef(con.oid) AS definition
                            FROM pg_constraint con
                            JOIN pg_class rel ON rel.oid = con.conrelid
                            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                            WHERE nsp.nspname = 'public'
                              AND rel.relname = :table
                              AND con.contype = 'c'
                            ORDER BY con.conname
                            """
                        ),
                        {"table": table},
                    )
                ).all()
                if checks:
                    for chk in checks:
                        add(f"  {chk[0]}: {chk[1]}")
                else:
                    add("  (none)")

                add("- unique constraints")
                uniques = (
                    await conn.execute(
                        text(
                            """
                            SELECT tc.constraint_name,
                                   string_agg(kcu.column_name, ', ' ORDER BY kcu.ordinal_position)
                            FROM information_schema.table_constraints tc
                            JOIN information_schema.key_column_usage kcu
                              ON tc.constraint_name = kcu.constraint_name
                             AND tc.table_schema = kcu.table_schema
                            WHERE tc.table_schema = 'public'
                              AND tc.table_name = :table
                              AND tc.constraint_type = 'UNIQUE'
                            GROUP BY tc.constraint_name
                            ORDER BY tc.constraint_name
                            """
                        ),
                        {"table": table},
                    )
                ).all()
                if uniques:
                    for uq in uniques:
                        add(f"  {uq[0]}: ({uq[1]})")
                else:
                    add("  (none)")

                add("")
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
