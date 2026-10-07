"""provisioning jobs, idempotency keys and one pending registration per applicant (Moc E)

  provisioning_jobs   the durable record of "create the Owner account": a Firebase user and
                      a set of DB rows that no single transaction can cover. The Firebase
                      uid is derived from the job id (CHECK), so a retry can find the user
                      it created and a clean-up can only ever delete that uid, never a user
                      found by e-mail.
  idempotency_keys    Idempotency-Key bookkeeping for POST .../business and POST .../owner.
                      response_body never holds a password (enforced in code, tested).
  uq_registration_pending_same_applicant
                      two PENDING registrations with the same e-mail and clan name, ignoring
                      case, cannot coexist.

Only new tables and one new index. No existing table changes.

Requires PostgreSQL 15+ and a database that is at revision 0002. Before touching anything the
online run checks the version, the revision, the schema it builds on, that the new objects do
not exist yet, and that no pending registrations would violate the new index. It stops with a
clear message (counts and ids only, never an e-mail address) and changes nothing. The checks
are skipped in offline (--sql) mode because there is no connection.

DOWNGRADE DROPS BOTH TABLES AND EVERY ROW IN THEM. A FAILED job with needs_cleanup = true is
the only record of a Firebase user that still has to be deleted, so the online downgrade REFUSES
to run (and changes nothing) while any such row exists; the message gives the row count only.
Otherwise it prints the row counts it is about to drop.

All DDL runs in one transaction (transaction_per_migration in env.py). CREATE INDEX is NOT
concurrent; the new tables are empty and the registration table is small.

Revision ID: 0003_provisioning_idempotency
Revises: 0002_integrity_constraints
Create Date: 2026-10-06
"""

import logging
from typing import NamedTuple, Sequence, Union

import sqlalchemy as sa
from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "0003_provisioning_idempotency"
down_revision: Union[str, Sequence[str], None] = "0002_integrity_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

MIN_SERVER_VERSION_NUM = 150000  # PostgreSQL 15
MAX_KEYS_SHOWN = 10
EXPECTED_REVISION = "0002_integrity_constraints"
NL = chr(10)

# What 0003 builds on: users, clans, registrations and the objects 0002 created.
REQUIRED_RELATIONS = (
    "public.users",
    "public.clans",
    "public.business_registrations",
    "public.uq_users_email_lower",
    "public.uq_active_clan_owner",
)
# What 0003 creates: none of it may exist yet.
NEW_RELATIONS = (
    "public.provisioning_jobs",
    "public.idempotency_keys",
    "public.uq_registration_pending_same_applicant",
)

# Pending registrations that would violate uq_registration_pending_same_applicant.
# The key is the list of registration ids (no e-mail address: personal data).
PENDING_DUPLICATES_SQL = (
    "SELECT string_agg(registration_id::text, ' ' ORDER BY created_at, registration_id::text) AS k, "
    "count(*) AS n FROM business_registrations WHERE status = 'PENDING' "
    "GROUP BY lower(representative_email), lower(clan_name) HAVING count(*) > 1 ORDER BY 1"
)

COUNT_NEEDS_CLEANUP_SQL = "SELECT count(*) FROM provisioning_jobs WHERE needs_cleanup"

CREATE_PROVISIONING_JOBS = """
CREATE TABLE provisioning_jobs (
  job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_type varchar(50) NOT NULL DEFAULT 'OWNER_PROVISIONING',
  clan_id uuid NOT NULL,
  status varchar(30) NOT NULL DEFAULT 'PENDING',
  requested_by uuid,
  email varchar(255) NOT NULL,
  display_name varchar(255) NOT NULL,
  phone varchar(30),
  firebase_uid varchar(255) NOT NULL,
  firebase_user_created boolean NOT NULL DEFAULT false,
  needs_cleanup boolean NOT NULL DEFAULT false,
  user_id uuid,
  attempt_count integer NOT NULL DEFAULT 0,
  lease_expires_at timestamptz,
  error_code varchar(100),
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at timestamptz,
  CONSTRAINT provisioning_jobs_clan_id_fkey FOREIGN KEY (clan_id) REFERENCES clans (clan_id) ON DELETE CASCADE,
  CONSTRAINT provisioning_jobs_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES users (user_id) ON DELETE SET NULL,
  CONSTRAINT provisioning_jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE SET NULL,
  CONSTRAINT provisioning_jobs_job_type_check CHECK (job_type IN ('OWNER_PROVISIONING')),
  CONSTRAINT provisioning_jobs_status_check CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED_RETRYABLE', 'FAILED')),
  CONSTRAINT provisioning_jobs_attempt_count_check CHECK (attempt_count >= 0),
  CONSTRAINT provisioning_jobs_firebase_uid_check CHECK (firebase_uid = 'own-' || job_id::text),
  CONSTRAINT provisioning_jobs_needs_cleanup_check CHECK (needs_cleanup = false OR (status = 'FAILED' AND firebase_user_created)),
  CONSTRAINT provisioning_jobs_running_lease_check CHECK (status <> 'RUNNING' OR lease_expires_at IS NOT NULL)
)
"""

CREATE_IDEMPOTENCY_KEYS = """
CREATE TABLE idempotency_keys (
  idempotency_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id uuid NOT NULL,
  endpoint varchar(100) NOT NULL,
  idempotency_key varchar(128) NOT NULL,
  request_hash varchar(64) NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'IN_PROGRESS',
  resource_type varchar(50),
  resource_id uuid,
  response_status integer,
  response_body jsonb,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at timestamptz NOT NULL,
  CONSTRAINT idempotency_keys_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES users (user_id) ON DELETE CASCADE,
  CONSTRAINT uq_idempotency_actor_endpoint_key UNIQUE (actor_id, endpoint, idempotency_key),
  CONSTRAINT idempotency_keys_status_check CHECK (status IN ('IN_PROGRESS', 'COMPLETED')),
  CONSTRAINT idempotency_keys_key_length_check CHECK (char_length(idempotency_key) BETWEEN 8 AND 128),
  CONSTRAINT idempotency_keys_request_hash_check CHECK (char_length(request_hash) = 64),
  CONSTRAINT idempotency_keys_completed_check CHECK (status <> 'COMPLETED' OR response_status IS NOT NULL)
)
"""

# One job per clan unless it failed for good, and a failed job that still owns a Firebase user
# (needs_cleanup) keeps blocking the clan and the e-mail until the clean-up is done.
CREATE_LIVE_PER_CLAN_INDEX = (
    "CREATE UNIQUE INDEX uq_provisioning_job_live_per_clan ON provisioning_jobs (clan_id) "
    "WHERE status IN ('PENDING', 'RUNNING', 'FAILED_RETRYABLE', 'SUCCEEDED') OR needs_cleanup"
)
CREATE_LIVE_EMAIL_INDEX = (
    "CREATE UNIQUE INDEX uq_provisioning_job_live_email ON provisioning_jobs (lower(email)) "
    "WHERE status IN ('PENDING', 'RUNNING', 'FAILED_RETRYABLE') OR needs_cleanup"
)
CREATE_CLAN_CREATED_INDEX = (
    "CREATE INDEX idx_provisioning_jobs_clan_created ON provisioning_jobs (clan_id, created_at DESC)"
)
CREATE_PENDING_REGISTRATION_INDEX = (
    "CREATE UNIQUE INDEX uq_registration_pending_same_applicant "
    "ON business_registrations (lower(representative_email), lower(clan_name)) WHERE status = 'PENDING'"
)


class FoundDuplicates(NamedTuple):
    registration_ids: str
    count: int


def with_comment(comment: str, statement: str) -> str:
    """Prefix a statement with an SQL comment line.

    Never emit a comment on its own: a comment-only statement is an empty query, which the
    driver rejects in an online run.
    """
    return f"-- {comment}{NL}{statement}"


def find_pending_duplicates(conn) -> list[FoundDuplicates]:
    rows = conn.execute(sa.text(PENDING_DUPLICATES_SQL)).all()
    return [FoundDuplicates(str(r[0]), int(r[1])) for r in rows]


def ensure_postgres_15(conn) -> None:
    version_num = conn.execute(sa.text("SELECT current_setting('server_version_num')::int")).scalar()
    if version_num is None or int(version_num) < MIN_SERVER_VERSION_NUM:
        raise RuntimeError(
            f"Migration 0003 needs PostgreSQL 15 or newer; server_version_num={version_num}. "
            "Nothing was changed."
        )


def ensure_at_revision_0002(conn) -> None:
    rows = conn.execute(sa.text("SELECT version_num FROM alembic_version")).all()
    found = sorted(str(r[0]) for r in rows)
    if found != [EXPECTED_REVISION]:
        raise RuntimeError(
            f"Migration 0003 builds on {EXPECTED_REVISION}; this database is at {found or 'no revision'}. "
            "Nothing was changed. See docs/migrations.md."
        )


def ensure_baseline_schema(conn) -> None:
    missing = [
        name
        for name in REQUIRED_RELATIONS
        if not conn.execute(sa.text("SELECT to_regclass(:name) IS NOT NULL"), {"name": name}).scalar()
    ]
    if missing:
        raise RuntimeError(
            "Migration 0003 expects the schema left by revision 0002. "
            f"Missing: {', '.join(missing)}. Nothing was changed. See docs/migrations.md."
        )


def ensure_new_objects_absent(conn) -> None:
    present = [
        name
        for name in NEW_RELATIONS
        if conn.execute(sa.text("SELECT to_regclass(:name) IS NOT NULL"), {"name": name}).scalar()
    ]
    if present:
        raise RuntimeError(
            f"Migration 0003 would create objects that already exist: {', '.join(present)}. "
            "Someone created them by hand. Nothing was changed. See docs/migrations.md."
        )


def ensure_no_pending_duplicates(conn) -> None:
    found = find_pending_duplicates(conn)
    if not found:
        return
    lines = [
        "Migration 0003 stopped: PENDING registrations with the same e-mail and clan name "
        "(ignoring case) would violate uq_registration_pending_same_applicant. Nothing was changed.",
        f"- {len(found)} group(s) of registration ids:",
    ]
    for item in found[:MAX_KEYS_SHOWN]:
        lines.append(f"    {item.registration_ids}  x{item.count}")
    if len(found) > MAX_KEYS_SHOWN:
        lines.append(f"    ... and {len(found) - MAX_KEYS_SHOWN} more")
    lines.append(
        "Resolve them by hand first (review and reject the extra registrations; do not delete), "
        "then run the migration again. See docs/migrations.md."
    )
    raise RuntimeError(NL.join(lines))


def upgrade() -> None:
    if context.is_offline_mode():
        note = f"-- offline preview: the PostgreSQL 15, revision, schema and duplicate checks run only in an online run{NL}"
    else:
        note = ""
        conn = op.get_bind()
        ensure_postgres_15(conn)
        ensure_at_revision_0002(conn)
        ensure_baseline_schema(conn)
        ensure_new_objects_absent(conn)
        ensure_no_pending_duplicates(conn)

    op.execute(note + "SET LOCAL lock_timeout = '5s'")

    op.execute(
        with_comment(
            "provisioning_jobs: durable record of Owner provisioning (Firebase uid derived from job_id)",
            CREATE_PROVISIONING_JOBS.strip(),
        )
    )
    op.execute(
        with_comment(
            "one job per clan unless it failed for good; a job that still needs a Firebase clean-up blocks too",
            CREATE_LIVE_PER_CLAN_INDEX,
        )
    )
    op.execute(
        with_comment(
            "no two live jobs for the same e-mail (any case), in any clan",
            CREATE_LIVE_EMAIL_INDEX,
        )
    )
    op.execute(CREATE_CLAN_CREATED_INDEX)

    op.execute(
        with_comment(
            "idempotency_keys: Idempotency-Key bookkeeping; response_body never holds a password",
            CREATE_IDEMPOTENCY_KEYS.strip(),
        )
    )

    op.execute(
        with_comment(
            "one PENDING registration per applicant (e-mail and clan name, any case)",
            CREATE_PENDING_REGISTRATION_INDEX,
        )
    )


def ensure_no_pending_cleanup(conn) -> None:
    """Refuse to downgrade while a job still owns a Firebase user that has not been deleted.

    Such a row is the only record of that user. The message gives the number of rows only:
    no e-mail address, no uid.
    """
    orphans = int(conn.execute(sa.text(COUNT_NEEDS_CLEANUP_SQL)).scalar() or 0)
    if orphans:
        raise RuntimeError(
            f"Downgrade 0003 refused: {orphans} provisioning_jobs row(s) still have needs_cleanup = true. "
            "Each one is the only record of a Firebase user that still has to be deleted. "
            "Nothing was changed. Finish the clean-up first (retry those jobs), then downgrade again. "
            "See docs/migrations.md."
        )


def warn_about_data_loss(conn) -> None:
    jobs = conn.execute(sa.text("SELECT count(*) FROM provisioning_jobs")).scalar() or 0
    keys = conn.execute(sa.text("SELECT count(*) FROM idempotency_keys")).scalar() or 0
    logger.warning(
        "DOWNGRADE 0003 DROPS provisioning_jobs (%s rows, none needing a Firebase clean-up) and "
        "idempotency_keys (%s rows). The data is lost.",
        jobs,
        keys,
    )


def downgrade() -> None:
    if context.is_offline_mode():
        note = (
            f"-- WARNING: this drops provisioning_jobs and idempotency_keys with every row in them.{NL}"
            f"-- The online downgrade REFUSES to run while any job still has needs_cleanup = true:{NL}"
            f"-- such a job is the only record of a Firebase user to delete.{NL}"
        )
    else:
        note = ""
        conn = op.get_bind()
        ensure_no_pending_cleanup(conn)
        warn_about_data_loss(conn)

    op.execute(note + "SET LOCAL lock_timeout = '5s'")
    op.execute("DROP INDEX uq_registration_pending_same_applicant")
    op.execute("DROP TABLE idempotency_keys")
    op.execute("DROP TABLE provisioning_jobs")
