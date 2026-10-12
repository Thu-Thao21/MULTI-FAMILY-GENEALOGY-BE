"""Revision 0003 (provisioning jobs, idempotency keys, pending-registration index), no database.

Covers: the pre-flight checks against a fake connection (every refusal happens before any DDL),
the exact statements and their order, the CHECKs that protect the Firebase clean-up rule, the
data-loss warning of the downgrade, the offline SQL preview through the real `python -m alembic`
entry point, and a drift test between the migration and the ORM declarations.

Nothing here touches a database. The integration side is tests/integration/test_db_provisioning.py.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.models.registry import target_metadata

BE_DIR = Path(__file__).resolve().parents[1]
URL = "postgresql+psycopg://fake_user_zq:S3cr3tPassw0rdXyz@ep-fake-host-12345.example.invalid/mfgms_fake?sslmode=require"
SECRETS = ("fake_user_zq", "S3cr3tPassw0rdXyz", "ep-fake-host-12345.example.invalid")

REVISION = "0003_provisioning_idempotency"
PREVIOUS = "0002_integrity_constraints"


def load_migration():
    path = BE_DIR / "alembic" / "versions" / f"{REVISION}.py"
    spec = importlib.util.spec_from_file_location("migration_0003_unit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mig():
    return load_migration()


class FakeResult:
    def __init__(self, rows=(), scalar=None):
        self._rows, self._scalar = list(rows), scalar

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar


class FakeConn:
    """A database at revision 0002 unless told otherwise."""

    def __init__(self, mig, *, version_num=180006, revisions=(PREVIOUS,), missing=(), present=(), duplicates=(), counts=None, needs_cleanup=0):
        self.needs_cleanup = needs_cleanup  # provisioning_jobs rows with needs_cleanup = true
        self.version_num = version_num
        self.revisions = list(revisions)
        self.existing = (set(mig.REQUIRED_RELATIONS) - set(missing)) | set(present)
        self.duplicates = list(duplicates)
        self.counts = counts or {}
        self.seen: list[str] = []

    def execute(self, clause, params=None):
        sql = str(clause)
        self.seen.append(sql)
        if "server_version_num" in sql:
            return FakeResult(scalar=self.version_num)
        if "FROM alembic_version" in sql:
            return FakeResult([(r,) for r in self.revisions])
        if "to_regclass" in sql:
            return FakeResult(scalar=params["name"] in self.existing)
        if "FROM business_registrations" in sql:
            return FakeResult(self.duplicates)
        if "WHERE needs_cleanup" in sql:
            return FakeResult(scalar=self.needs_cleanup)
        for table, count in self.counts.items():
            if f"FROM {table}" in sql:
                return FakeResult(scalar=count)
        return FakeResult(scalar=0)


class RecordingOp:
    def __init__(self, conn):
        self._conn = conn
        self.statements: list[str] = []

    def get_bind(self):
        return self._conn

    def execute(self, sql):
        self.statements.append(str(sql))


def run(mig, monkeypatch, fn_name, conn, *, offline=False):
    op = RecordingOp(conn)
    monkeypatch.setattr(mig, "op", op)
    monkeypatch.setattr(mig, "context", types.SimpleNamespace(is_offline_mode=lambda: offline))
    getattr(mig, fn_name)()
    return op


def only_sql(statement: str) -> str:
    return "\n".join(line for line in statement.splitlines() if not line.strip().startswith("--")).strip()


# ---------------------------------------------------------------- pre-flight checks


def test_a_clean_0002_database_passes_every_check_silently(mig):
    conn = FakeConn(mig)
    mig.ensure_postgres_15(conn)
    mig.ensure_at_revision_0002(conn)
    mig.ensure_baseline_schema(conn)
    mig.ensure_new_objects_absent(conn)
    mig.ensure_no_pending_duplicates(conn)


@pytest.mark.parametrize("version_num, allowed", [(140011, False), (149999, False), (150000, True), (180006, True)])
def test_postgres_15_is_required(mig, version_num, allowed):
    conn = FakeConn(mig, version_num=version_num)
    if allowed:
        mig.ensure_postgres_15(conn)
    else:
        with pytest.raises(RuntimeError, match="PostgreSQL 15"):
            mig.ensure_postgres_15(conn)


@pytest.mark.parametrize(
    "revisions",
    [["0001_baseline"], [REVISION], [], [PREVIOUS, "0001_baseline"], ["something_else"]],
    ids=["at-0001", "already-0003", "no-revision", "two-rows", "unknown"],
)
def test_only_a_database_at_exactly_revision_0002_is_accepted(mig, revisions):
    with pytest.raises(RuntimeError, match="Nothing was changed") as exc:
        mig.ensure_at_revision_0002(FakeConn(mig, revisions=revisions))
    assert PREVIOUS in str(exc.value)


def test_missing_schema_is_named_and_refused(mig):
    conn = FakeConn(mig, missing={"public.uq_users_email_lower", "public.clans"})
    with pytest.raises(RuntimeError) as exc:
        mig.ensure_baseline_schema(conn)
    message = str(exc.value)
    assert "public.uq_users_email_lower" in message and "public.clans" in message
    assert "public.users" not in message and "Nothing was changed" in message


def test_every_relation_0003_builds_on_is_checked(mig):
    for name in ("users", "clans", "business_registrations", "uq_users_email_lower", "uq_active_clan_owner"):
        assert f"public.{name}" in mig.REQUIRED_RELATIONS


def test_objects_that_already_exist_are_refused_by_name(mig):
    conn = FakeConn(mig, present={"public.provisioning_jobs", "public.uq_registration_pending_same_applicant"})
    with pytest.raises(RuntimeError) as exc:
        mig.ensure_new_objects_absent(conn)
    message = str(exc.value)
    assert "provisioning_jobs" in message and "uq_registration_pending_same_applicant" in message
    assert "idempotency_keys" not in message and "Nothing was changed" in message


def test_every_object_the_migration_creates_is_in_the_absence_check(mig):
    for name in ("provisioning_jobs", "idempotency_keys", "uq_registration_pending_same_applicant"):
        assert f"public.{name}" in mig.NEW_RELATIONS


def test_pending_duplicates_are_reported_by_registration_id_only_and_capped(mig):
    groups = [(f"id-{i}a id-{i}b", 2) for i in range(12)]
    conn = FakeConn(mig, duplicates=groups)
    with pytest.raises(RuntimeError) as exc:
        mig.ensure_no_pending_duplicates(conn)
    message = str(exc.value)
    assert "12 group(s)" in message and "id-0a id-0b  x2" in message
    assert "... and 2 more" in message and "Nothing was changed" in message
    assert "do not delete" in message and "@" not in message
    message.encode("ascii")


def test_the_duplicate_query_matches_the_index_it_protects(mig):
    sql = mig.PENDING_DUPLICATES_SQL
    assert "status = 'PENDING'" in sql
    assert "GROUP BY lower(representative_email), lower(clan_name)" in sql
    assert "HAVING count(*) > 1" in sql
    # The report shows registration ids only: nothing personal may appear in what the query selects.
    select_list = sql.split(" FROM ")[0]
    assert "string_agg(registration_id::text" in select_list
    assert "email" not in select_list and "clan_name" not in select_list and "name" not in select_list.replace("registration", "")
    assert "lower(representative_email), lower(clan_name)" in mig.CREATE_PENDING_REGISTRATION_INDEX
    assert "WHERE status = 'PENDING'" in mig.CREATE_PENDING_REGISTRATION_INDEX


@pytest.mark.parametrize(
    "conn_kwargs, match",
    [
        ({"version_num": 140000}, "PostgreSQL 15"),
        ({"revisions": ["0001_baseline"]}, "builds on"),
        ({"missing": {"public.clans"}}, "public.clans"),
        ({"present": {"public.idempotency_keys"}}, "already exist"),
        ({"duplicates": [("a b", 2)]}, "uq_registration_pending_same_applicant"),
    ],
    ids=["old-server", "wrong-revision", "missing-schema", "objects-exist", "pending-duplicates"],
)
def test_every_refusal_happens_before_any_ddl(mig, monkeypatch, conn_kwargs, match):
    op = RecordingOp(FakeConn(mig, **conn_kwargs))
    monkeypatch.setattr(mig, "op", op)
    monkeypatch.setattr(mig, "context", types.SimpleNamespace(is_offline_mode=lambda: False))
    with pytest.raises(RuntimeError, match=match):
        mig.upgrade()
    assert op.statements == []  # not even SET LOCAL


# ---------------------------------------------------------------- statements


def test_upgrade_runs_the_checks_then_creates_exactly_the_planned_objects_in_order(mig, monkeypatch):
    conn = FakeConn(mig)
    op = run(mig, monkeypatch, "upgrade", conn)
    assert any("server_version_num" in s for s in conn.seen) and any("alembic_version" in s for s in conn.seen)
    sql = [only_sql(s) for s in op.statements]
    assert sql[0] == "SET LOCAL lock_timeout = '5s'"
    assert sql[1].startswith("CREATE TABLE provisioning_jobs (")
    assert sql[2].startswith("CREATE UNIQUE INDEX uq_provisioning_job_live_per_clan ON provisioning_jobs (clan_id)")
    assert sql[3].startswith("CREATE UNIQUE INDEX uq_provisioning_job_live_email ON provisioning_jobs (lower(email))")
    assert sql[4].startswith("CREATE INDEX idx_provisioning_jobs_clan_created ON provisioning_jobs (clan_id, created_at DESC)")
    assert sql[5].startswith("CREATE TABLE idempotency_keys (")
    assert sql[6].startswith("CREATE UNIQUE INDEX uq_registration_pending_same_applicant ON business_registrations")
    assert len(sql) == 7
    assert not any("CONCURRENTLY" in s for s in sql)
    # Only creations: no existing table is altered, emptied or rewritten.
    assert all(s.startswith(("SET LOCAL", "CREATE TABLE", "CREATE UNIQUE INDEX", "CREATE INDEX")) for s in sql)
    assert [s.split()[2] for s in sql if s.startswith("CREATE TABLE")] == ["provisioning_jobs", "idempotency_keys"]


@pytest.mark.parametrize("fn_name", ["upgrade", "downgrade"])
def test_no_statement_is_a_bare_comment_which_the_driver_would_reject_as_an_empty_query(mig, monkeypatch, fn_name):
    op = run(mig, monkeypatch, fn_name, FakeConn(mig))
    assert op.statements
    for statement in op.statements:
        assert only_sql(statement), f"comment-only statement: {statement!r}"


def create_table_text(mig, table: str) -> str:
    return getattr(mig, {"provisioning_jobs": "CREATE_PROVISIONING_JOBS", "idempotency_keys": "CREATE_IDEMPOTENCY_KEYS"}[table])


def test_the_firebase_uid_of_a_job_is_forced_to_be_own_plus_job_id(mig):
    """A2: the clean-up may delete only the uid derived from the job; the DB refuses any other."""
    ddl = create_table_text(mig, "provisioning_jobs")
    assert "CONSTRAINT provisioning_jobs_firebase_uid_check CHECK (firebase_uid = 'own-' || job_id::text)" in ddl


def test_a_clean_up_is_only_possible_for_a_failed_job_that_created_a_firebase_user(mig):
    ddl = create_table_text(mig, "provisioning_jobs")
    assert "CHECK (needs_cleanup = false OR (status = 'FAILED' AND firebase_user_created))" in ddl


def test_a_running_job_must_have_a_lease(mig):
    assert "CHECK (status <> 'RUNNING' OR lease_expires_at IS NOT NULL)" in create_table_text(mig, "provisioning_jobs")


def test_a_failed_job_that_needs_a_clean_up_keeps_blocking_the_clan_and_the_email(mig):
    """A5: both live indexes also cover needs_cleanup, so a new job cannot start meanwhile."""
    assert mig.CREATE_LIVE_PER_CLAN_INDEX.endswith("OR needs_cleanup")
    assert mig.CREATE_LIVE_EMAIL_INDEX.endswith("OR needs_cleanup")
    assert "'SUCCEEDED'" in mig.CREATE_LIVE_PER_CLAN_INDEX  # one Owner job per clan, forever
    assert "'SUCCEEDED'" not in mig.CREATE_LIVE_EMAIL_INDEX  # e-mail of a finished job is guarded by users
    assert "lower(email)" in mig.CREATE_LIVE_EMAIL_INDEX


def test_job_statuses_match_the_states_of_the_plan(mig):
    ddl = create_table_text(mig, "provisioning_jobs")
    assert "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED_RETRYABLE', 'FAILED')" in ddl


def columns_of(ddl: str) -> list[str]:
    body = ddl.split("(", 1)[1]
    names = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith(("CONSTRAINT", ")")):
            continue
        names.append(line.split()[0])
    return names


@pytest.mark.parametrize("table", ["provisioning_jobs", "idempotency_keys"])
def test_no_column_can_hold_a_password_or_a_secret(mig, table):
    for name in columns_of(create_table_text(mig, table)):
        assert not re.search(r"pass|secret|token|credential", name, re.I), name


def test_the_idempotency_table_guards_its_inputs(mig):
    ddl = create_table_text(mig, "idempotency_keys")
    assert "CONSTRAINT uq_idempotency_actor_endpoint_key UNIQUE (actor_id, endpoint, idempotency_key)" in ddl
    assert "CHECK (char_length(idempotency_key) BETWEEN 8 AND 128)" in ddl
    assert "CHECK (char_length(request_hash) = 64)" in ddl
    assert "CHECK (status <> 'COMPLETED' OR response_status IS NOT NULL)" in ddl
    assert "status IN ('IN_PROGRESS', 'COMPLETED')" in ddl


# ---------------------------------------------------------------- downgrade


def test_the_online_downgrade_warns_with_the_row_counts_before_dropping(mig, monkeypatch, caplog):
    conn = FakeConn(mig, counts={"provisioning_jobs": 7, "idempotency_keys": 3})
    with caplog.at_level(logging.WARNING, logger="alembic.runtime.migration"):
        op = run(mig, monkeypatch, "downgrade", conn)
    warning = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert "DOWNGRADE 0003 DROPS" in warning and "7 rows" in warning and "3 rows" in warning
    assert "data is lost" in warning
    sql = [only_sql(s) for s in op.statements]
    assert sql == [
        "SET LOCAL lock_timeout = '5s'",
        "DROP INDEX uq_registration_pending_same_applicant",
        "DROP TABLE idempotency_keys",
        "DROP TABLE provisioning_jobs",
    ]


@pytest.mark.parametrize("orphans", [1, 2, 40])
def test_the_online_downgrade_refuses_while_a_job_still_needs_a_firebase_clean_up(mig, monkeypatch, caplog, orphans):
    """Such a row is the only record of a Firebase user: stop, change nothing, say only how many."""
    conn = FakeConn(mig, counts={"provisioning_jobs": 50, "idempotency_keys": 4}, needs_cleanup=orphans)
    op = RecordingOp(conn)
    monkeypatch.setattr(mig, "op", op)
    monkeypatch.setattr(mig, "context", types.SimpleNamespace(is_offline_mode=lambda: False))
    with caplog.at_level(logging.WARNING, logger="alembic.runtime.migration"):
        with pytest.raises(RuntimeError, match="Downgrade 0003 refused") as exc:
            mig.downgrade()
    message = str(exc.value)
    assert f"{orphans} provisioning_jobs row(s)" in message and "Nothing was changed" in message
    assert "@" not in message and "own-" not in message and "example" not in message  # no e-mail, no uid
    assert "50" not in message  # only the rows that need a clean-up are counted, not all rows
    message.encode("ascii")
    assert op.statements == []  # not even SET LOCAL: nothing was dropped
    assert not [r for r in caplog.records if "DROPS" in r.getMessage()]  # the refusal comes before the warning


def test_the_downgrade_goes_ahead_when_jobs_exist_but_none_needs_a_clean_up(mig, monkeypatch, caplog):
    conn = FakeConn(mig, counts={"provisioning_jobs": 5, "idempotency_keys": 2}, needs_cleanup=0)
    with caplog.at_level(logging.WARNING, logger="alembic.runtime.migration"):
        op = run(mig, monkeypatch, "downgrade", conn)
    assert [only_sql(s) for s in op.statements][-1] == "DROP TABLE provisioning_jobs"
    assert any("5 rows, none needing a Firebase clean-up" in r.getMessage() for r in caplog.records)


def test_the_refusal_counts_exactly_the_rows_that_need_a_clean_up(mig):
    sql = mig.COUNT_NEEDS_CLEANUP_SQL
    assert sql == "SELECT count(*) FROM provisioning_jobs WHERE needs_cleanup"
    assert "FROM provisioning_jobs" in sql and "idempotency" not in sql


def test_the_refusal_check_runs_before_the_data_loss_warning(mig):
    conn = FakeConn(mig, needs_cleanup=3)
    with pytest.raises(RuntimeError):
        mig.ensure_no_pending_cleanup(conn)
    assert conn.seen == [mig.COUNT_NEEDS_CLEANUP_SQL]  # nothing else was asked
    mig.ensure_no_pending_cleanup(FakeConn(mig, needs_cleanup=0))  # none: passes silently


def test_the_offline_downgrade_preview_carries_a_data_loss_warning_and_makes_no_query(mig, monkeypatch):
    op = RecordingOp(conn=None)  # any use of the connection would crash
    monkeypatch.setattr(mig, "op", op)
    monkeypatch.setattr(mig, "context", types.SimpleNamespace(is_offline_mode=lambda: True))
    mig.downgrade()
    first = op.statements[0]
    assert "WARNING" in first and "every row" in first and "needs_cleanup" in first and "SET LOCAL lock_timeout" in first
    assert "REFUSES" in first  # the preview tells the reader the online downgrade stops while clean-ups are pending


def test_the_offline_upgrade_skips_the_checks_because_there_is_no_connection(mig, monkeypatch):
    op = RecordingOp(conn=None)
    monkeypatch.setattr(mig, "op", op)
    monkeypatch.setattr(mig, "context", types.SimpleNamespace(is_offline_mode=lambda: True))
    mig.upgrade()
    assert "offline preview" in op.statements[0] and "SET LOCAL lock_timeout" in op.statements[0]


# ---------------------------------------------------------------- the ORM says the same thing


def migration_statements(mig) -> list[str]:
    return [
        mig.CREATE_PROVISIONING_JOBS.strip(),
        mig.CREATE_IDEMPOTENCY_KEYS.strip(),
        mig.CREATE_LIVE_PER_CLAN_INDEX,
        mig.CREATE_LIVE_EMAIL_INDEX,
        mig.CREATE_CLAN_CREATED_INDEX,
        mig.CREATE_PENDING_REGISTRATION_INDEX,
    ]


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@pytest.mark.parametrize("table", ["provisioning_jobs", "idempotency_keys"])
def test_the_orm_has_exactly_the_columns_of_the_migration(mig, table):
    assert {c.name for c in target_metadata.tables[table].columns} == set(columns_of(create_table_text(mig, table)))


@pytest.mark.parametrize("table", ["provisioning_jobs", "idempotency_keys"])
def test_every_check_constraint_is_declared_identically_in_the_orm(mig, table):
    ddl = create_table_text(mig, table)
    in_migration = {}
    for line in ddl.splitlines():
        line = line.strip().rstrip(",")
        m = re.match(r"CONSTRAINT (\w+) CHECK \((.*)\)$", line)
        if m:
            in_migration[m.group(1)] = squash(m.group(2))
    from sqlalchemy import CheckConstraint

    in_orm = {
        c.name: squash(c.sqltext.text)
        for c in target_metadata.tables[table].constraints
        if isinstance(c, CheckConstraint)
    }
    assert in_orm == in_migration
    assert in_orm  # not vacuous


def test_the_orm_unique_constraint_of_the_idempotency_table_matches(mig):
    from sqlalchemy import UniqueConstraint

    uniques = {
        c.name: [col.name for col in c.columns]
        for c in target_metadata.tables["idempotency_keys"].constraints
        if isinstance(c, UniqueConstraint)
    }
    assert uniques == {"uq_idempotency_actor_endpoint_key": ["actor_id", "endpoint", "idempotency_key"]}


def test_every_index_compiles_to_the_same_sql_in_the_orm_and_the_migration(mig):
    dialect = postgresql.dialect()
    in_orm = []
    for table_name in ("provisioning_jobs", "business_registrations"):
        for index in target_metadata.tables[table_name].indexes:
            if index.name in {
                "uq_provisioning_job_live_per_clan",
                "uq_provisioning_job_live_email",
                "idx_provisioning_jobs_clan_created",
                "uq_registration_pending_same_applicant",
            }:
                in_orm.append(squash(str(CreateIndex(index).compile(dialect=dialect))))
    in_migration = [squash(s) for s in migration_statements(mig) if "INDEX" in s]
    assert sorted(in_orm) == sorted(in_migration)
    assert len(in_orm) == 4
    assert target_metadata.tables["idempotency_keys"].indexes == set()  # only the UNIQUE constraint


def test_the_orm_columns_of_the_new_tables_carry_the_same_nullability_as_the_ddl(mig):
    ddl_not_null = {}
    for table in ("provisioning_jobs", "idempotency_keys"):
        for line in create_table_text(mig, table).splitlines():
            line = line.strip().rstrip(",")
            if not line or line.startswith(("CONSTRAINT", ")", "CREATE")):
                continue
            ddl_not_null[(table, line.split()[0])] = "NOT NULL" in line or "PRIMARY KEY" in line
    for (table, column), not_null in ddl_not_null.items():
        orm_column = target_metadata.tables[table].columns[column]
        assert (not orm_column.nullable) == not_null, (table, column)


# ---------------------------------------------------------------- the real entry point


def run_cli(*args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("ALLOW_MIGRATE", "MIGRATE_EXPECT_FINGERPRINT")}
    env["DATABASE_URL"] = URL
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BE_DIR, env=env, capture_output=True, text=True, timeout=120
    )


def test_the_offline_upgrade_preview_from_0002_shows_the_new_objects_and_connects_nowhere():
    proc = run_cli("upgrade", f"{PREVIOUS}:head", "--sql")
    assert proc.returncode == 0, proc.stderr[-600:]
    sql = proc.stdout
    for name in (
        "CREATE TABLE provisioning_jobs",
        "CREATE TABLE idempotency_keys",
        "uq_provisioning_job_live_per_clan",
        "uq_provisioning_job_live_email",
        "idx_provisioning_jobs_clan_created",
        "uq_registration_pending_same_applicant",
        "provisioning_jobs_firebase_uid_check",
        "uq_idempotency_actor_endpoint_key",
    ):
        assert name in sql, name
    assert f"SET version_num='{REVISION}'" in sql and f"'{PREVIOUS}'" in sql
    assert "uq_users_email_lower" not in sql  # 0002 is not repeated
    for secret in SECRETS:
        assert secret not in sql + proc.stderr


def test_the_offline_downgrade_preview_to_0002_drops_both_tables_with_a_warning():
    proc = run_cli("downgrade", f"{REVISION}:{PREVIOUS}", "--sql")
    assert proc.returncode == 0, proc.stderr[-600:]
    sql = proc.stdout
    assert "-- WARNING: this drops provisioning_jobs and idempotency_keys" in sql
    for line in ("DROP INDEX uq_registration_pending_same_applicant;", "DROP TABLE idempotency_keys;", "DROP TABLE provisioning_jobs;"):
        assert line in sql, line
    assert f"SET version_num='{PREVIOUS}'" in sql
    for secret in SECRETS:
        assert secret not in sql + proc.stderr


@pytest.mark.parametrize("command", [["upgrade", "head"], ["downgrade", "-1"], ["current"], ["stamp", "head"]])
def test_the_existing_guard_still_stops_every_online_command_before_connecting(command):
    proc = run_cli(*command)
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0 and "ALLOW_MIGRATE" in output
    assert "alembic target:" not in output
    for secret in SECRETS:
        assert secret not in output
