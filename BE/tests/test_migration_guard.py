"""Migration safety, no database needed.

Covers: the database fingerprint, the ALLOW_MIGRATE / MIGRATE_EXPECT_FINGERPRINT guard (as a
function and through the real `python -m alembic` entry point, with an unreachable host so any
connection attempt would fail), the offline SQL preview, the migration chain, and the
pre-flight duplicate check of revision 0002 against a fake connection.

Nothing here touches a database. The URL below is fake and contains marker secrets: no output
may ever contain them.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.db.fingerprint import database_fingerprint, database_name, target_summary
from app.db.migration_guard import (
    ENV_ALLOW,
    ENV_FINGERPRINT,
    check_guard,
    enforce_guard,
)

BE_DIR = Path(__file__).resolve().parents[1]
HOST = "ep-fake-host-12345.example.invalid"
USER = "fake_user_zq"
PASSWORD = "S3cr3tPassw0rdXyz"
URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}/mfgms_fake?sslmode=require"
SECRETS = (HOST, USER, PASSWORD)
FINGERPRINT = hashlib.sha256(f"{HOST}/mfgms_fake".encode()).hexdigest()[:8]


def assert_no_secret(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text, f"{secret!r} leaked"


# ---------------------------------------------------------------- fingerprint


def test_fingerprint_is_the_first_8_hex_of_sha256_over_host_and_database():
    assert database_fingerprint(URL) == FINGERPRINT
    assert len(FINGERPRINT) == 8 and int(FINGERPRINT, 16) >= 0


def test_fingerprint_ignores_user_password_and_query_but_not_host_or_database():
    same = f"postgresql+psycopg://other:otherpw@{HOST}/mfgms_fake"
    assert database_fingerprint(same) == FINGERPRINT
    assert database_fingerprint(URL.replace(HOST, "ep-another-host.example.invalid")) != FINGERPRINT
    assert database_fingerprint(URL.replace("mfgms_fake", "other_db")) != FINGERPRINT


def test_target_summary_names_the_database_and_never_the_host_user_or_password():
    summary = target_summary(URL)
    assert summary == f"database=mfgms_fake fingerprint={FINGERPRINT}"
    assert database_name(URL) == "mfgms_fake"
    assert_no_secret(summary)


# ---------------------------------------------------------------- guard function


def test_guard_refuses_without_allow_migrate_and_shows_the_fingerprint_to_confirm():
    message = check_guard(URL, {})
    assert message is not None and ENV_ALLOW in message
    assert FINGERPRINT in message and "database=mfgms_fake" in message
    assert_no_secret(message)


@pytest.mark.parametrize("value", ["0", "true", "yes", "", " 1", "2"])
def test_guard_accepts_only_the_exact_value_1(value):
    environ = {ENV_ALLOW: value, ENV_FINGERPRINT: FINGERPRINT}
    assert check_guard(URL, environ) is not None


def test_guard_refuses_without_a_fingerprint_and_prints_the_current_one():
    message = check_guard(URL, {ENV_ALLOW: "1"})
    assert message is not None and ENV_FINGERPRINT in message and FINGERPRINT in message
    assert_no_secret(message)
    blank = check_guard(URL, {ENV_ALLOW: "1", ENV_FINGERPRINT: "   "})
    assert blank is not None and FINGERPRINT in blank


def test_guard_refuses_a_wrong_fingerprint_and_prints_the_current_one():
    message = check_guard(URL, {ENV_ALLOW: "1", ENV_FINGERPRINT: "deadbeef"})
    assert message is not None and "does not match" in message and FINGERPRINT in message
    assert_no_secret(message)


def test_guard_needs_both_conditions():
    assert check_guard(URL, {ENV_FINGERPRINT: FINGERPRINT}) is not None  # fingerprint alone is not enough


def test_guard_allows_a_matching_fingerprint_ignoring_case_and_spaces():
    assert check_guard(URL, {ENV_ALLOW: "1", ENV_FINGERPRINT: FINGERPRINT}) is None
    assert check_guard(URL, {ENV_ALLOW: "1", ENV_FINGERPRINT: f"  {FINGERPRINT.upper()} "}) is None


def test_the_fingerprint_of_one_database_does_not_unlock_another():
    other = URL.replace("mfgms_fake", "mfgms_prod")
    assert check_guard(other, {ENV_ALLOW: "1", ENV_FINGERPRINT: FINGERPRINT}) is not None


def test_enforce_guard_raises_system_exit_with_the_message():
    with pytest.raises(SystemExit) as exc:
        enforce_guard(URL, {})
    assert ENV_ALLOW in str(exc.value.code) and FINGERPRINT in str(exc.value.code)
    enforce_guard(URL, {ENV_ALLOW: "1", ENV_FINGERPRINT: FINGERPRINT})  # allowed: no exception


def test_guard_messages_are_ascii_so_a_cp1252_console_can_print_them():
    for environ in ({}, {ENV_ALLOW: "1"}, {ENV_ALLOW: "1", ENV_FINGERPRINT: "00000000"}):
        check_guard(URL, environ).encode("ascii")


# ---------------------------------------------------------------- real CLI entry points


def run_cli(*args: str, environ: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in (ENV_ALLOW, ENV_FINGERPRINT)}
    env["DATABASE_URL"] = URL
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(environ or {})
    return subprocess.run(
        [sys.executable, *args],
        cwd=BE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_alembic_online_commands_stop_before_connecting_without_the_guard_variables():
    for command in (["current"], ["upgrade", "head"], ["stamp", "head"], ["downgrade", "-1"]):
        proc = run_cli("-m", "alembic", *command)
        output = proc.stdout + proc.stderr
        assert proc.returncode != 0, command
        assert ENV_ALLOW in output and FINGERPRINT in output, command
        assert_no_secret(output)
        # a refused run must not even reach the engine (the host is unreachable by design)
        assert "alembic target:" not in output, command


def test_alembic_stops_on_a_wrong_fingerprint():
    proc = run_cli("-m", "alembic", "upgrade", "head", environ={ENV_ALLOW: "1", ENV_FINGERPRINT: "deadbeef"})
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0 and "does not match" in output and FINGERPRINT in output
    assert_no_secret(output)


def test_alembic_offline_preview_needs_no_guard_and_makes_no_connection():
    proc = run_cli("-m", "alembic", "upgrade", "base:head", "--sql")
    assert proc.returncode == 0, proc.stderr[-600:]
    sql = proc.stdout
    assert "CREATE TABLE alembic_version" in sql and "'0001_baseline'" in sql
    assert "NULLS NOT DISTINCT WHERE revoked_at IS NULL" in sql
    for name in (
        "uq_active_user_role_scope",
        "uq_user_sessions_token_jti_hash",
        "uq_family_admin_active_assignment",
        "uq_users_email_lower",
    ):
        assert name in sql, name
    assert "ON users (lower(email))" in sql
    assert f"database=mfgms_fake fingerprint={FINGERPRINT}" in proc.stderr
    assert_no_secret(sql + proc.stderr)


def test_alembic_downgrade_preview_restores_the_old_role_index():
    proc = run_cli("-m", "alembic", "downgrade", "0002_integrity_constraints:0001_baseline", "--sql")
    assert proc.returncode == 0, proc.stderr[-600:]
    sql = proc.stdout
    for name in ("uq_users_email_lower", "uq_family_admin_active_assignment", "uq_user_sessions_token_jti_hash"):
        assert f"DROP INDEX {name};" in sql, name
    recreate = next(line for line in sql.splitlines() if line.startswith("CREATE UNIQUE INDEX uq_active_user_role_scope"))
    assert "NULLS NOT DISTINCT" not in recreate and "WHERE revoked_at IS NULL" in recreate
    assert_no_secret(sql + proc.stderr)


def test_the_fingerprint_command_prints_only_the_database_and_the_fingerprint():
    proc = run_cli("-m", "app.db.fingerprint")
    assert proc.returncode == 0, proc.stderr[-600:]
    assert proc.stdout.strip() == f"database=mfgms_fake fingerprint={FINGERPRINT}"
    assert_no_secret(proc.stdout + proc.stderr)


# ---------------------------------------------------------------- migration chain


def test_the_history_is_one_line_baseline_then_0002_then_0003():
    script = ScriptDirectory.from_config(Config(str(BE_DIR / "alembic.ini")))
    assert script.get_heads() == ["0003_provisioning_idempotency"]
    assert script.get_revision("0003_provisioning_idempotency").down_revision == "0002_integrity_constraints"
    assert script.get_revision("0002_integrity_constraints").down_revision == "0001_baseline"
    assert script.get_revision("0001_baseline").down_revision is None


def test_the_baseline_is_empty():
    """"The tables already exist": the revision never imports alembic.op, so it cannot run DDL."""
    module = load_migration("0001_baseline")
    assert not hasattr(module, "op") and not hasattr(module, "sa")
    assert module.upgrade() is None and module.downgrade() is None


# ---------------------------------------------------------------- revision 0002 logic


def load_migration(name: str):
    path = BE_DIR / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"migration_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResult:
    def __init__(self, rows=(), scalar=None):
        self._rows, self._scalar = list(rows), scalar

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar


class FakeConn:
    """Answers the migration's queries from a table of canned rows."""

    def __init__(self, *, version_num=180006, duplicates=None, missing=()):
        self.version_num = version_num
        self.duplicates = duplicates or {}  # substring of the SQL -> rows
        self.missing = set(missing)  # relations to_regclass() cannot find
        self.seen: list[str] = []

    def execute(self, clause, params=None):
        sql = str(clause)
        self.seen.append(sql)
        if "server_version_num" in sql:
            return FakeResult(scalar=self.version_num)
        if "to_regclass" in sql:
            return FakeResult(scalar=params["name"] not in self.missing)
        for marker, rows in self.duplicates.items():
            if marker in sql:
                return FakeResult(rows)
        return FakeResult()


@pytest.fixture
def mig():
    return load_migration("0002_integrity_constraints")


def test_no_duplicates_means_the_preflight_check_passes_silently(mig):
    conn = FakeConn()
    mig.ensure_postgres_15(conn)
    mig.ensure_baseline_schema(conn)
    mig.ensure_no_duplicates(conn)
    assert len(conn.seen) == 1 + len(mig.REQUIRED_RELATIONS) + len(mig.DUPLICATE_CHECKS)


def test_a_database_without_the_baseline_schema_is_refused_with_the_missing_names(mig):
    conn = FakeConn(missing={"public.user_sessions", "public.uq_active_user_role_scope"})
    with pytest.raises(RuntimeError) as exc:
        mig.ensure_baseline_schema(conn)
    message = str(exc.value)
    assert "public.user_sessions" in message and "public.uq_active_user_role_scope" in message
    assert "public.users" not in message  # only what is really missing
    assert "initial_schema.sql" in message and "Nothing was changed" in message
    message.encode("ascii")


def test_every_relation_the_migration_touches_is_in_the_baseline_check(mig):
    for name in ("users", "user_sessions", "user_roles", "family_admin_assignments", "uq_active_user_role_scope"):
        assert f"public.{name}" in mig.REQUIRED_RELATIONS


def test_every_planned_constraint_has_a_duplicate_check(mig):
    names = " ".join(check.name for check in mig.DUPLICATE_CHECKS)
    for token in ("KI-03", "KI-04", "KI-08", "lower(email)"):
        assert token in names
    # NULL-safe grouping: GROUP BY treats NULLs as equal, like NULLS NOT DISTINCT does
    role_check = next(c for c in mig.DUPLICATE_CHECKS if "KI-03" in c.name)
    assert "GROUP BY user_id, role_id, clan_id" in role_check.sql and "revoked_at IS NULL" in role_check.sql
    fa_check = next(c for c in mig.DUPLICATE_CHECKS if "KI-08" in c.name)
    assert "GROUP BY clan_id, user_id, branch_id" in fa_check.sql and "revoked_at IS NULL" in fa_check.sql


def test_duplicates_stop_the_migration_with_counts_and_keys_but_never_secrets(mig):
    keys_role = [(f"{i:08d}-user 00000000-role (system)", 2) for i in range(12)]
    conn = FakeConn(
        duplicates={
            "FROM user_roles": keys_role,
            "FROM user_sessions": [("hash-that-must-not-print-abc123", 2)],
            "FROM family_admin_assignments": [("clan-1 user-1 (clan-wide)", 3)],
            "FROM users": [("someone@example.com", 2), ("other@example.com", 2)],
        }
    )
    with pytest.raises(RuntimeError) as exc:
        mig.ensure_no_duplicates(conn)
    message = str(exc.value)
    assert "Nothing was changed" in message and "revoked_at" in message
    assert "12 group(s)" in message and "... and 2 more" in message  # capped key list
    assert "(system)" in message and "(clan-wide)" in message  # keys of non-sensitive checks
    assert "1 group(s)" in message and "2 group(s)" in message
    assert "hash-that-must-not-print-abc123" not in message  # token hash never printed
    assert "someone@example.com" not in message and "other@example.com" not in message  # no e-mail
    message.encode("ascii")  # printable on a cp1252 console


def test_only_the_checks_that_found_something_are_reported(mig):
    conn = FakeConn(duplicates={"FROM family_admin_assignments": [("k", 2)]})
    with pytest.raises(RuntimeError) as exc:
        mig.ensure_no_duplicates(conn)
    message = str(exc.value)
    assert "KI-08" in message and "KI-03" not in message and "KI-04" not in message


@pytest.mark.parametrize("version_num, allowed", [(140011, False), (149999, False), (150000, True), (180006, True)])
def test_postgres_15_is_required(mig, version_num, allowed):
    conn = FakeConn(version_num=version_num)
    if allowed:
        mig.ensure_postgres_15(conn)
    else:
        with pytest.raises(RuntimeError, match="PostgreSQL 15"):
            mig.ensure_postgres_15(conn)


class RecordingOp:
    def __init__(self, conn):
        self._conn = conn
        self.statements: list[str] = []

    def get_bind(self):
        return self._conn

    def execute(self, sql):
        self.statements.append(str(sql))


def run_online(mig, monkeypatch, fn_name, conn=None):
    op = RecordingOp(conn or FakeConn())
    monkeypatch.setattr(mig, "op", op)
    monkeypatch.setattr(mig, "context", types.SimpleNamespace(is_offline_mode=lambda: False))
    getattr(mig, fn_name)()
    return op


def only_sql(statement: str) -> str:
    return "\n".join(line for line in statement.splitlines() if not line.strip().startswith("--")).strip()


@pytest.mark.parametrize("fn_name", ["upgrade", "downgrade"])
def test_no_statement_is_a_bare_comment_which_the_driver_would_reject_as_an_empty_query(mig, monkeypatch, fn_name):
    op = run_online(mig, monkeypatch, fn_name)
    assert op.statements
    for statement in op.statements:
        assert only_sql(statement), f"comment-only statement: {statement!r}"


def test_upgrade_checks_first_then_replaces_the_role_index_and_adds_the_three_others(mig, monkeypatch):
    conn = FakeConn()
    op = run_online(mig, monkeypatch, "upgrade", conn)
    assert any("server_version_num" in sql for sql in conn.seen)  # checks ran before any DDL
    sql = [only_sql(s) for s in op.statements]
    assert sql[0] == "SET LOCAL lock_timeout = '5s'"
    assert sql[1] == "DROP INDEX uq_active_user_role_scope"
    assert sql[2].startswith("CREATE UNIQUE INDEX uq_active_user_role_scope ON user_roles (user_id, role_id, clan_id)")
    assert sql[2].endswith("NULLS NOT DISTINCT WHERE revoked_at IS NULL")
    assert sql[3] == "CREATE UNIQUE INDEX uq_user_sessions_token_jti_hash ON user_sessions (token_jti_hash)"
    assert sql[4] == (
        "CREATE UNIQUE INDEX uq_family_admin_active_assignment ON family_admin_assignments "
        "(clan_id, user_id, branch_id) NULLS NOT DISTINCT WHERE revoked_at IS NULL"
    )
    assert sql[5] == "CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email))"
    assert len(sql) == 6 and not any("CONCURRENTLY" in s for s in sql)


def test_upgrade_on_duplicate_data_raises_before_any_ddl(mig, monkeypatch):
    conn = FakeConn(duplicates={"FROM user_roles": [("u r (system)", 2)]})
    op = RecordingOp(conn)
    monkeypatch.setattr(mig, "op", op)
    monkeypatch.setattr(mig, "context", types.SimpleNamespace(is_offline_mode=lambda: False))
    with pytest.raises(RuntimeError, match="Nothing was changed"):
        mig.upgrade()
    assert op.statements == []  # not even SET LOCAL


def test_upgrade_on_a_database_without_the_baseline_raises_before_any_ddl(mig, monkeypatch):
    op = RecordingOp(FakeConn(missing={"public.family_admin_assignments"}))
    monkeypatch.setattr(mig, "op", op)
    monkeypatch.setattr(mig, "context", types.SimpleNamespace(is_offline_mode=lambda: False))
    with pytest.raises(RuntimeError, match="family_admin_assignments"):
        mig.upgrade()
    assert op.statements == []


def test_upgrade_on_an_old_server_raises_before_any_ddl(mig, monkeypatch):
    op = RecordingOp(FakeConn(version_num=140000))
    monkeypatch.setattr(mig, "op", op)
    monkeypatch.setattr(mig, "context", types.SimpleNamespace(is_offline_mode=lambda: False))
    with pytest.raises(RuntimeError, match="PostgreSQL 15"):
        mig.upgrade()
    assert op.statements == []


def test_offline_upgrade_skips_the_checks_because_there_is_no_connection(mig, monkeypatch):
    op = RecordingOp(conn=None)  # get_bind() would hand back None: any use would crash
    monkeypatch.setattr(mig, "op", op)
    monkeypatch.setattr(mig, "context", types.SimpleNamespace(is_offline_mode=lambda: True))
    mig.upgrade()
    assert "offline preview" in op.statements[0] and "SET LOCAL lock_timeout" in op.statements[0]


def test_downgrade_restores_exactly_the_old_state(mig, monkeypatch):
    op = run_online(mig, monkeypatch, "downgrade")
    sql = [only_sql(s) for s in op.statements]
    assert sql[0] == "SET LOCAL lock_timeout = '5s'"
    assert sql[1:4] == [
        "DROP INDEX uq_users_email_lower",
        "DROP INDEX uq_family_admin_active_assignment",
        "DROP INDEX uq_user_sessions_token_jti_hash",
    ]
    assert sql[4] == "DROP INDEX uq_active_user_role_scope"
    assert sql[5] == (
        "CREATE UNIQUE INDEX uq_active_user_role_scope ON user_roles (user_id, role_id, clan_id) "
        "WHERE revoked_at IS NULL"
    )
    assert len(sql) == 6
