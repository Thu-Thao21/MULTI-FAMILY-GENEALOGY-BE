"""integrity constraints: KI-03, KI-04, KI-08 and case-insensitive unique e-mail

  KI-03  uq_active_user_role_scope becomes NULLS NOT DISTINCT, so a duplicate active
         SYSTEM_ADMIN grant (clan_id IS NULL) is rejected.
  KI-04  unique user_sessions.token_jti_hash.
  KI-08  at most one active family_admin_assignments row per (clan_id, user_id, branch_id),
         where a NULL branch_id (clan-wide) counts as one value.
  Email  unique lower(users.email). users_email_key (exact match) stays.

Requires PostgreSQL 15+ (NULLS NOT DISTINCT). Before touching anything, the online run checks
the version, that the baseline schema is there (the tables and the old role index it replaces),
and looks for rows that would violate a new constraint; it stops with a clear message
(counts and keys only, never an e-mail address or a token hash) and changes nothing.
The checks are skipped in offline (--sql) mode because there is no connection.

All DDL runs in one transaction (transaction_per_migration in env.py), so a failure rolls
back everything. CREATE INDEX is NOT concurrent: it blocks writes to the table while it runs.

Revision ID: 0002_integrity_constraints
Revises: 0001_baseline
Create Date: 2026-10-06
"""

from typing import NamedTuple, Sequence, Union

import sqlalchemy as sa
from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "0002_integrity_constraints"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MIN_SERVER_VERSION_NUM = 150000  # PostgreSQL 15
MAX_KEYS_SHOWN = 10
NL = chr(10)


class DuplicateCheck(NamedTuple):
    name: str
    sql: str  # returns rows (key_text, n): one row per group with n > 1
    show_keys: bool  # False when the key is sensitive (e-mail address, token hash)


DUPLICATE_CHECKS: tuple[DuplicateCheck, ...] = (
    DuplicateCheck(
        "KI-03 user_roles: active rows sharing (user_id, role_id, clan_id), NULL clan counts as equal",
        "SELECT user_id::text || ' ' || role_id::text || ' ' || coalesce(clan_id::text, '(system)') AS k, "
        "count(*) AS n FROM user_roles WHERE revoked_at IS NULL "
        "GROUP BY user_id, role_id, clan_id HAVING count(*) > 1 ORDER BY 1",
        True,
    ),
    DuplicateCheck(
        "KI-04 user_sessions: rows sharing token_jti_hash",
        "SELECT 'hidden' AS k, count(*) AS n FROM user_sessions WHERE token_jti_hash IS NOT NULL "
        "GROUP BY token_jti_hash HAVING count(*) > 1",
        False,
    ),
    DuplicateCheck(
        "KI-08 family_admin_assignments: active rows sharing (clan_id, user_id, branch_id), NULL branch counts as equal",
        "SELECT clan_id::text || ' ' || user_id::text || ' ' || coalesce(branch_id::text, '(clan-wide)') AS k, "
        "count(*) AS n FROM family_admin_assignments WHERE revoked_at IS NULL "
        "GROUP BY clan_id, user_id, branch_id HAVING count(*) > 1 ORDER BY 1",
        True,
    ),
    DuplicateCheck(
        "email users: rows sharing lower(email)",
        "SELECT 'hidden' AS k, count(*) AS n FROM users GROUP BY lower(email) HAVING count(*) > 1",
        False,
    ),
)


def find_duplicates(conn) -> list[tuple[DuplicateCheck, list[tuple[str, int]]]]:
    """Run every check; return only the checks that found duplicate groups."""
    found = []
    for check in DUPLICATE_CHECKS:
        rows = [(str(r[0]), int(r[1])) for r in conn.execute(sa.text(check.sql)).all()]
        if rows:
            found.append((check, rows))
    return found


# What 0002 builds on: the schema of the dev database (docs/schema_*.txt), recorded by 0001.
REQUIRED_RELATIONS = (
    "public.users",
    "public.user_sessions",
    "public.user_roles",
    "public.family_admin_assignments",
    "public.uq_active_user_role_scope",
)


def ensure_baseline_schema(conn) -> None:
    missing = [
        name
        for name in REQUIRED_RELATIONS
        if not conn.execute(sa.text("SELECT to_regclass(:name) IS NOT NULL"), {"name": name}).scalar()
    ]
    if missing:
        raise RuntimeError(
            "Migration 0002 expects the schema recorded by baseline 0001 (the dev database schema). "
            f"Missing: {', '.join(missing)}. database/initial_schema.sql is an old export and is not "
            "enough to build that schema. Nothing was changed. See docs/migrations.md."
        )


def ensure_postgres_15(conn) -> None:
    version_num = conn.execute(sa.text("SELECT current_setting('server_version_num')::int")).scalar()
    if version_num is None or int(version_num) < MIN_SERVER_VERSION_NUM:
        raise RuntimeError(
            f"Migration 0002 needs PostgreSQL 15 or newer (NULLS NOT DISTINCT); "
            f"server_version_num={version_num}. Nothing was changed."
        )


def ensure_no_duplicates(conn) -> None:
    found = find_duplicates(conn)
    if not found:
        return
    lines = ["Migration 0002 stopped: existing rows would violate a new unique index. Nothing was changed."]
    for check, rows in found:
        lines.append(f"- {check.name}: {len(rows)} group(s)")
        if check.show_keys:
            for key, n in rows[:MAX_KEYS_SHOWN]:
                lines.append(f"    {key}  x{n}")
            if len(rows) > MAX_KEYS_SHOWN:
                lines.append(f"    ... and {len(rows) - MAX_KEYS_SHOWN} more")
    lines.append(
        "Clean the duplicates by hand first (revoke the extra rows by setting revoked_at; do not delete), "
        "then run the migration again. See docs/migrations.md."
    )
    raise RuntimeError(NL.join(lines))


def with_comment(comment: str, statement: str) -> str:
    """Prefix a statement with an SQL comment line.

    Never emit a comment on its own: a comment-only statement is an empty query, which the
    driver rejects in an online run.
    """
    return f"-- {comment}{NL}{statement}"


def upgrade() -> None:
    if context.is_offline_mode():
        note = f"-- offline preview: the PostgreSQL 15 and duplicate checks run only in an online run{NL}"
    else:
        note = ""
        conn = op.get_bind()
        ensure_postgres_15(conn)
        ensure_baseline_schema(conn)
        ensure_no_duplicates(conn)

    op.execute(note + "SET LOCAL lock_timeout = '5s'")

    op.execute(
        with_comment(
            "KI-03: same name, now NULLS NOT DISTINCT (system-scope rows with clan_id NULL are equal)",
            "DROP INDEX uq_active_user_role_scope",
        )
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_active_user_role_scope ON user_roles (user_id, role_id, clan_id) "
        "NULLS NOT DISTINCT WHERE revoked_at IS NULL"
    )

    op.execute(
        with_comment(
            "KI-04: one session per token hash (NULL hashes stay allowed, NULLs are distinct)",
            "CREATE UNIQUE INDEX uq_user_sessions_token_jti_hash ON user_sessions (token_jti_hash)",
        )
    )

    op.execute(
        with_comment(
            "KI-08: one active assignment per (clan, user, branch); NULL branch (clan-wide) is one value",
            "CREATE UNIQUE INDEX uq_family_admin_active_assignment "
            "ON family_admin_assignments (clan_id, user_id, branch_id) "
            "NULLS NOT DISTINCT WHERE revoked_at IS NULL",
        )
    )

    op.execute(
        with_comment(
            "e-mail is unique regardless of case (users_email_key, exact match, stays)",
            "CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email))",
        )
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.execute("DROP INDEX uq_users_email_lower")
    op.execute("DROP INDEX uq_family_admin_active_assignment")
    op.execute("DROP INDEX uq_user_sessions_token_jti_hash")

    op.execute(
        with_comment(
            "back to the pre-0002 definition of uq_active_user_role_scope (NULLs distinct)",
            "DROP INDEX uq_active_user_role_scope",
        )
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_active_user_role_scope ON user_roles (user_id, role_id, clan_id) "
        "WHERE revoked_at IS NULL"
    )
