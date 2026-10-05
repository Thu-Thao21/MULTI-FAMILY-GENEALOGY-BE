"""
Read-only drift check: ORM target_metadata vs the real database.

For every table in app.models.registry.target_metadata:
  - ERRORS (exit code 1): missing table, missing/extra column, type family mismatch,
    nullable mismatch, primary key mismatch.
  - INFO (never an error): index and CHECK constraint names present only on one side.

Types are compared by family, not by raw string:
  uuid, timestamptz, timestamp, inet, jsonb, json, text, bool, int2/int4/int8,
  varchar(n) (length checked), numeric(p,s) (precision/scale checked), date.

Runs inside a READ ONLY transaction. Prints no DATABASE_URL and no row data.
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import (  # noqa: E402
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.dialects.postgresql import INET, JSON, JSONB, UUID  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.types import TypeEngine  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.models.registry import target_metadata  # noqa: E402

TypeFamily = tuple


def orm_family(t: TypeEngine) -> TypeFamily:
    # Order matters: subclasses before their bases.
    if isinstance(t, UUID):
        return ("uuid",)
    if isinstance(t, DateTime):
        return ("timestamptz",) if t.timezone else ("timestamp",)
    if isinstance(t, Date):
        return ("date",)
    if isinstance(t, INET):
        return ("inet",)
    if isinstance(t, JSONB):
        return ("jsonb",)
    if isinstance(t, JSON):
        return ("json",)
    if isinstance(t, Text):
        return ("text",)
    if isinstance(t, String):
        return ("varchar", t.length) if t.length is not None else ("text",)
    if isinstance(t, Boolean):
        return ("bool",)
    if isinstance(t, BigInteger):
        return ("int8",)
    if isinstance(t, SmallInteger):
        return ("int2",)
    if isinstance(t, Integer):
        return ("int4",)
    if isinstance(t, Float):
        return ("float",)
    if isinstance(t, Numeric):
        return ("numeric", t.precision, t.scale)
    return ("other", t.compile(dialect=postgresql.dialect()).lower())


_DB_SIMPLE = {
    "uuid": ("uuid",),
    "timestamptz": ("timestamptz",),
    "timestamp": ("timestamp",),
    "date": ("date",),
    "inet": ("inet",),
    "jsonb": ("jsonb",),
    "json": ("json",),
    "text": ("text",),
    "bool": ("bool",),
    "int2": ("int2",),
    "int4": ("int4",),
    "int8": ("int8",),
    "float4": ("float",),
    "float8": ("float",),
}


def db_family(udt: str, max_len: int | None, prec: int | None, scale: int | None) -> TypeFamily:
    if udt == "varchar":
        return ("varchar", max_len) if max_len is not None else ("text",)
    if udt == "numeric":
        return ("numeric", prec, scale)
    return _DB_SIMPLE.get(udt, ("other", udt))


def fmt(f: TypeFamily) -> str:
    name, *args = f
    args = [a for a in args if a is not None]
    return f"{name}({','.join(map(str, args))})" if args else name


Q_TABLES = """
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
"""

Q_COLUMNS = """
SELECT table_name, column_name, udt_name, character_maximum_length,
       numeric_precision, numeric_scale, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = ANY(:tables)
"""

Q_PK = """
SELECT rel.relname, a.attname
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
JOIN LATERAL unnest(con.conkey) AS k(attnum) ON true
JOIN pg_attribute a ON a.attrelid = rel.oid AND a.attnum = k.attnum
WHERE nsp.nspname = 'public' AND con.contype = 'p' AND rel.relname = ANY(:tables)
"""

Q_CHECKS = """
SELECT rel.relname, con.conname
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
WHERE nsp.nspname = 'public' AND con.contype = 'c' AND rel.relname = ANY(:tables)
"""

# Standalone indexes only: skip indexes that back a PK/UNIQUE/EXCLUDE constraint.
Q_INDEXES = """
SELECT t.relname, i.relname
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_namespace nsp ON nsp.oid = t.relnamespace
WHERE nsp.nspname = 'public' AND t.relname = ANY(:tables)
  AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = ix.indexrelid)
"""


async def load_db(tables: list[str]) -> dict:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            p = {"tables": tables}
            existing = {r[0] for r in (await conn.execute(text(Q_TABLES))).all()}
            cols = (await conn.execute(text(Q_COLUMNS), p)).all()
            pks = (await conn.execute(text(Q_PK), p)).all()
            checks = (await conn.execute(text(Q_CHECKS), p)).all()
            idx = (await conn.execute(text(Q_INDEXES), p)).all()
            await conn.rollback()
    finally:
        await engine.dispose()

    db_cols: dict[str, dict[str, tuple]] = defaultdict(dict)
    for t, c, udt, ln, pr, sc, nul in cols:
        db_cols[t][c] = (db_family(udt, ln, pr, sc), nul == "YES")
    db_pk: dict[str, set[str]] = defaultdict(set)
    for t, c in pks:
        db_pk[t].add(c)
    db_checks: dict[str, set[str]] = defaultdict(set)
    for t, n in checks:
        db_checks[t].add(n)
    db_idx: dict[str, set[str]] = defaultdict(set)
    for t, n in idx:
        db_idx[t].add(n)
    return {
        "existing": existing,
        "cols": db_cols,
        "pk": db_pk,
        "checks": db_checks,
        "idx": db_idx,
    }


def main() -> int:
    orm_tables = sorted(target_metadata.tables)
    db = asyncio.run(load_db(orm_tables))

    errors: list[str] = []
    info: list[str] = []
    coverage: list[tuple[str, int, int]] = []

    for name in orm_tables:
        table = target_metadata.tables[name]
        if name not in db["existing"]:
            errors.append(f"[{name}] table missing in DB")
            continue

        dcols = db["cols"][name]
        ocols = {c.name: c for c in table.columns}
        coverage.append((name, len(set(ocols) & set(dcols)), len(dcols)))

        for cname in sorted(set(dcols) - set(ocols)):
            errors.append(f"[{name}] column only in DB: {cname}")
        for cname in sorted(set(ocols) - set(dcols)):
            errors.append(f"[{name}] column only in ORM: {cname}")

        for cname in sorted(set(ocols) & set(dcols)):
            col = ocols[cname]
            d_fam, d_null = dcols[cname]
            o_fam = orm_family(col.type)
            if o_fam != d_fam:
                errors.append(
                    f"[{name}.{cname}] type: ORM={fmt(o_fam)} DB={fmt(d_fam)}"
                )
            if bool(col.nullable) != d_null:
                errors.append(
                    f"[{name}.{cname}] nullable: ORM={bool(col.nullable)} DB={d_null}"
                )

        o_pk = {c.name for c in table.primary_key.columns}
        d_pk = db["pk"][name]
        if o_pk != d_pk:
            errors.append(f"[{name}] primary key: ORM={sorted(o_pk)} DB={sorted(d_pk)}")

        o_checks = {
            c.name for c in table.constraints if isinstance(c, CheckConstraint) and c.name
        }
        d_checks = db["checks"][name]
        for n in sorted(d_checks - o_checks):
            info.append(f"[{name}] CHECK only in DB: {n}")
        for n in sorted(o_checks - d_checks):
            info.append(f"[{name}] CHECK only in ORM: {n}")

        o_idx = {i.name for i in table.indexes if i.name}
        d_idx = db["idx"][name]
        for n in sorted(d_idx - o_idx):
            info.append(f"[{name}] index only in DB: {n}")
        for n in sorted(o_idx - d_idx):
            info.append(f"[{name}] index only in ORM: {n}")

    print(f"ORM vs DB check (read-only). Tables in metadata: {len(orm_tables)}")
    print()
    print("Column coverage (mapped/total in DB):")
    for name, mapped, total in coverage:
        print(f"  {name:<32} {mapped}/{total}")
    print()
    print(f"ERRORS ({len(errors)}): columns, types, nullable, PK")
    for e in errors:
        print(f"  {e}")
    if not errors:
        print("  (none)")
    print()
    print(f"INFO ({len(info)}): index / CHECK names, not counted as errors")
    for i in info:
        print(f"  {i}")
    if not info:
        print("  (none)")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
