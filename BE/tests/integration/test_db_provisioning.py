"""Objects added by migration 0003_provisioning_idempotency, on the real DB. Rolled back.

NEEDS THE MIGRATION APPLIED to the database these tests run against; on a database without it
they fail on purpose (that is how a missing migration shows up). Covers every constraint and
index of provisioning_jobs and idempotency_keys, uq_registration_pending_same_applicant, the real
index definitions in pg_indexes, the column lists, and the migration's own pre-flight check run
against live data.

The rules that matter most are the two that protect the Firebase clean-up (plan item A2 and A5):
a job can only ever point at the uid 'own-' + its own job_id, and a failed job that still owns a
Firebase user keeps blocking its clan and its e-mail until the clean-up is done.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DataError

from app.models.family.entities import IdempotencyKey, ProvisioningJob
from tests.integration.factory import now
from tests.integration.test_db_constraints import must_reject

BE_DIR = Path(__file__).resolve().parents[2]
LIVE_PER_CLAN = "uq_provisioning_job_live_per_clan"
LIVE_EMAIL = "uq_provisioning_job_live_email"
UNIQUE_KEY = "uq_idempotency_actor_endpoint_key"
PENDING_SAME_APPLICANT = "uq_registration_pending_same_applicant"


async def add_job(session, **fields) -> ProvisioningJob:
    """Insert a job row exactly as given (no helper defaults) so a test can break a rule."""
    job_id = fields.pop("job_id", uuid.uuid4())
    values = {
        "clan_id": None,
        "email": f"itest-raw-{uuid.uuid4().hex[:12]}@example.test",
        "display_name": "Integration Test Owner",
        "firebase_uid": f"own-{job_id}",
        **fields,
    }
    row = ProvisioningJob(job_id=job_id, **values)
    session.add(row)
    await session.flush()
    return row


# ------------------------------------------------------------------ provisioning_jobs: the uid rule (A2)


async def test_a_job_is_created_with_the_defaults_of_a_fresh_job(session, world):
    clan = await world.clan()
    job = await world.job(clan)
    await session.refresh(job)
    assert job.status == "PENDING" and job.job_type == "OWNER_PROVISIONING"
    assert job.attempt_count == 0 and job.firebase_user_created is False and job.needs_cleanup is False
    assert job.user_id is None and job.lease_expires_at is None and job.completed_at is None
    assert job.created_at is not None and job.updated_at is not None


@pytest.mark.parametrize(
    "uid_for",
    [
        lambda job_id, email: f"own-{uuid.uuid4()}",  # another job's uid
        lambda job_id, email: f"own-{job_id.hex}",  # same id, different spelling
        lambda job_id, email: f"own-{email}",  # derived from the e-mail
        lambda job_id, email: email,  # the e-mail itself
        lambda job_id, email: str(job_id),  # missing the prefix
        lambda job_id, email: f"OWN-{job_id}",  # wrong case
        lambda job_id, email: f"own-{job_id}-x",  # trailing junk
    ],
    ids=["other-job", "hex-spelling", "from-email", "email", "no-prefix", "upper-prefix", "suffix"],
)
async def test_a_job_can_only_point_at_the_uid_derived_from_its_own_id(session, world, uid_for):
    """A2: the clean-up deletes only this uid; the DB refuses any other value outright."""
    clan = await world.clan()
    job_id = uuid.uuid4()
    email = f"itest-uid-{uuid.uuid4().hex[:12]}@example.test"
    await must_reject(
        session,
        lambda: add_job(session, job_id=job_id, clan_id=clan.clan_id, email=email, firebase_uid=uid_for(job_id, email)),
        "provisioning_jobs_firebase_uid_check",
    )


async def test_the_uid_of_a_job_cannot_be_changed_afterwards_to_a_foreign_user(session, world):
    clan = await world.clan()
    job = await world.job(clan)
    await must_reject(
        session,
        lambda: session.execute(
            text("UPDATE provisioning_jobs SET firebase_uid = :uid WHERE job_id = :id"),
            {"uid": "someone-elses-uid", "id": job.job_id},
        ),
        "provisioning_jobs_firebase_uid_check",
    )


# ------------------------------------------------------------------ provisioning_jobs: one live job per clan


@pytest.mark.parametrize("status", ["PENDING", "RUNNING", "FAILED_RETRYABLE", "SUCCEEDED"])
async def test_a_clan_cannot_have_a_second_job_while_one_is_live_or_done(session, world, status):
    clan = await world.clan()
    await world.job(clan, status=status)
    await must_reject(session, lambda: world.job(clan), LIVE_PER_CLAN)


async def test_a_job_that_failed_for_good_does_not_block_a_new_one(session, world):
    clan = await world.clan()
    await world.job(clan, status="FAILED")
    await world.job(clan, status="FAILED")  # history may repeat
    await world.job(clan)  # a new attempt is allowed


async def test_two_clans_each_have_their_own_job(session, world):
    await world.job(await world.clan())
    await world.job(await world.clan())


async def test_a_failed_job_that_still_needs_a_clean_up_blocks_its_clan_until_it_is_done(session, world):
    """A5: a Firebase user may still exist, so no new job for this clan until it is deleted."""
    clan = await world.clan()
    stuck = await world.job(clan, status="FAILED", needs_cleanup=True)
    await must_reject(session, lambda: world.job(clan), LIVE_PER_CLAN)

    stuck.needs_cleanup = False  # the clean-up deleted the Firebase user
    await session.flush()
    await world.job(clan)  # now a new job may start


# ------------------------------------------------------------------ provisioning_jobs: one live job per e-mail


async def test_two_live_jobs_cannot_share_an_email_in_any_case_even_in_different_clans(session, world):
    first, second = await world.clan(), await world.clan()
    tag = uuid.uuid4().hex[:12]
    await world.job(first, email=f"itest-Owner-{tag}@Example.TEST")
    await must_reject(session, lambda: world.job(second, email=f"itest-owner-{tag}@example.test"), LIVE_EMAIL)


@pytest.mark.parametrize("status", ["RUNNING", "FAILED_RETRYABLE"])
async def test_every_live_status_blocks_the_email(session, world, status):
    first, second = await world.clan(), await world.clan()
    tag = uuid.uuid4().hex[:12]
    await world.job(first, status=status, email=f"itest-live-{tag}@example.test")
    await must_reject(session, lambda: world.job(second, email=f"ITEST-LIVE-{tag}@example.test"), LIVE_EMAIL)


async def test_an_email_is_free_again_once_the_job_failed_for_good_or_succeeded(session, world):
    """After SUCCEEDED the e-mail belongs to a real user, which users.uq_users_email_lower guards."""
    tag = uuid.uuid4().hex[:12]
    email = f"itest-free-{tag}@example.test"
    await world.job(await world.clan(), status="FAILED", email=email)
    await world.job(await world.clan(), status="SUCCEEDED", email=email.upper())
    await world.job(await world.clan(), email=email)


async def test_a_failed_job_that_needs_a_clean_up_blocks_its_email_in_other_clans(session, world):
    first, second = await world.clan(), await world.clan()
    tag = uuid.uuid4().hex[:12]
    stuck = await world.job(first, status="FAILED", needs_cleanup=True, email=f"itest-stuck-{tag}@example.test")
    await must_reject(session, lambda: world.job(second, email=f"ITEST-STUCK-{tag}@example.test"), LIVE_EMAIL)

    stuck.needs_cleanup = False
    await session.flush()
    await world.job(second, email=f"itest-stuck-{tag}@example.test")


# ------------------------------------------------------------------ provisioning_jobs: the other CHECKs


@pytest.mark.parametrize("status", ["PENDING", "RUNNING", "SUCCEEDED", "FAILED_RETRYABLE"])
async def test_only_a_failed_job_may_need_a_clean_up(session, world, status):
    clan = await world.clan()
    await must_reject(
        session,
        lambda: add_job(
            session,
            clan_id=clan.clan_id,
            status=status,
            needs_cleanup=True,
            firebase_user_created=True,
            lease_expires_at=now() + timedelta(minutes=1),
        ),
        "provisioning_jobs_needs_cleanup_check",
    )


async def test_a_clean_up_needs_a_firebase_user_that_this_job_created(session, world):
    clan = await world.clan()
    await must_reject(
        session,
        lambda: add_job(session, clan_id=clan.clan_id, status="FAILED", needs_cleanup=True, firebase_user_created=False),
        "provisioning_jobs_needs_cleanup_check",
    )
    await add_job(session, clan_id=clan.clan_id, status="FAILED", needs_cleanup=True, firebase_user_created=True)


async def test_a_running_job_must_carry_a_lease(session, world):
    clan = await world.clan()
    await must_reject(
        session, lambda: add_job(session, clan_id=clan.clan_id, status="RUNNING"), "provisioning_jobs_running_lease_check"
    )
    await add_job(session, clan_id=clan.clan_id, status="RUNNING", lease_expires_at=now() + timedelta(seconds=60))


async def test_a_lease_cannot_be_dropped_from_a_running_job(session, world):
    job = await world.job(await world.clan(), status="RUNNING")
    await must_reject(
        session,
        lambda: session.execute(
            text("UPDATE provisioning_jobs SET lease_expires_at = NULL WHERE job_id = :id"), {"id": job.job_id}
        ),
        "provisioning_jobs_running_lease_check",
    )


@pytest.mark.parametrize(
    "fields, constraint",
    [
        ({"status": "DONE"}, "provisioning_jobs_status_check"),
        ({"status": "pending"}, "provisioning_jobs_status_check"),
        ({"job_type": "OWNER_TRANSFER"}, "provisioning_jobs_job_type_check"),
        ({"attempt_count": -1}, "provisioning_jobs_attempt_count_check"),
    ],
    ids=["unknown-status", "lowercase-status", "unknown-type", "negative-attempts"],
)
async def test_values_outside_the_domain_are_rejected(session, world, fields, constraint):
    clan = await world.clan()
    await must_reject(session, lambda: add_job(session, clan_id=clan.clan_id, **fields), constraint)


async def test_every_status_of_the_state_machine_is_accepted(session, world):
    for status in ("PENDING", "RUNNING", "SUCCEEDED", "FAILED_RETRYABLE", "FAILED"):
        await world.job(await world.clan(), status=status)


async def test_a_job_needs_an_existing_clan(session):
    await must_reject(
        session, lambda: add_job(session, clan_id=uuid.uuid4()), "provisioning_jobs_clan_id_fkey"
    )


async def test_deleting_a_clan_deletes_its_jobs_and_deleting_a_user_only_clears_the_reference(session, world):
    sa, owner = await world.user(), await world.user()
    clan = await world.clan()
    job = await world.job(clan, requested_by=sa)
    job.user_id = owner.user_id
    await session.flush()

    await session.execute(text("DELETE FROM users WHERE user_id IN (:a, :b)"), {"a": sa.user_id, "b": owner.user_id})
    await session.refresh(job)
    assert job.requested_by is None and job.user_id is None  # ON DELETE SET NULL

    await session.execute(text("DELETE FROM clans WHERE clan_id = :c"), {"c": clan.clan_id})
    left = (await session.execute(select(ProvisioningJob).where(ProvisioningJob.job_id == job.job_id))).scalar_one_or_none()
    assert left is None  # ON DELETE CASCADE


# ------------------------------------------------------------------ idempotency_keys


async def test_the_same_key_twice_for_one_actor_and_endpoint_is_rejected(session, world):
    actor = await world.user()
    await world.idempotency(actor, key="key-0001-aaaa")
    await must_reject(session, lambda: world.idempotency(actor, key="key-0001-aaaa"), UNIQUE_KEY)


async def test_the_same_key_is_allowed_for_another_endpoint_or_another_actor(session, world):
    first, second = await world.user(), await world.user()
    await world.idempotency(first, endpoint="business.create", key="shared-key-1")
    await world.idempotency(first, endpoint="clan.owner.provision", key="shared-key-1")
    await world.idempotency(second, endpoint="business.create", key="shared-key-1")


@pytest.mark.parametrize("length, allowed", [(7, False), (8, True), (128, True), (0, False)])
async def test_the_key_must_be_8_to_128_characters(session, world, length, allowed):
    actor = await world.user()
    key = "k" * length
    if allowed:
        await world.idempotency(actor, key=key)
    else:
        await must_reject(session, lambda: world.idempotency(actor, key=key), "idempotency_keys_key_length_check")


async def test_a_key_longer_than_128_characters_is_refused_by_the_column_type(session, world):
    """varchar(128) already refuses it, before the CHECK is looked at: a data error, not a CHECK."""
    actor = await world.user()
    with pytest.raises(DataError):
        async with session.begin_nested():
            await world.idempotency(actor, key="k" * 129)


@pytest.mark.parametrize("request_hash", ["a" * 63, "", "short"])
async def test_the_request_hash_must_be_exactly_64_characters(session, world, request_hash):
    actor = await world.user()

    async def insert():
        row = await world.idempotency(actor, key=uuid.uuid4().hex)
        await session.execute(
            text("UPDATE idempotency_keys SET request_hash = :h WHERE idempotency_id = :i"),
            {"h": request_hash, "i": row.idempotency_id},
        )

    await must_reject(session, insert, "idempotency_keys_request_hash_check")


async def test_a_request_hash_longer_than_64_characters_is_refused_by_the_column_type(session, world):
    actor = await world.user()
    row = await world.idempotency(actor)
    with pytest.raises(DataError):
        async with session.begin_nested():
            await session.execute(
                text("UPDATE idempotency_keys SET request_hash = :h WHERE idempotency_id = :i"),
                {"h": "a" * 65, "i": row.idempotency_id},
            )


async def test_a_completed_key_must_carry_the_response_status(session, world):
    actor = await world.user()
    await must_reject(
        session, lambda: world.idempotency(actor, status="COMPLETED"), "idempotency_keys_completed_check"
    )
    await world.idempotency(actor, status="COMPLETED", response_status=201)
    await world.idempotency(actor, status="IN_PROGRESS")  # an unfinished key has no response yet


async def test_an_unknown_status_is_rejected(session, world):
    actor = await world.user()
    await must_reject(session, lambda: world.idempotency(actor, status="DONE"), "idempotency_keys_status_check")


async def test_the_response_body_round_trips_as_json_and_defaults_are_set(session, world):
    actor = await world.user()
    row = await world.idempotency(actor, status="COMPLETED", response_status=201)
    row.response_body = {"clan_id": str(uuid.uuid4()), "temporary_password": None}
    await session.flush()
    await session.refresh(row)
    assert row.response_body["temporary_password"] is None
    assert row.created_at is not None and row.expires_at > row.created_at


async def test_an_actor_must_exist_and_deleting_the_actor_deletes_its_keys(session, world):
    await must_reject(
        session,
        lambda: session.execute(
            text(
                "INSERT INTO idempotency_keys (actor_id, endpoint, idempotency_key, request_hash, expires_at) "
                "VALUES (:a, 'business.create', :k, :h, now() + interval '1 day')"
            ),
            {"a": uuid.uuid4(), "k": uuid.uuid4().hex, "h": "a" * 64},
        ),
        "idempotency_keys_actor_id_fkey",
    )
    actor = await world.user()
    row = await world.idempotency(actor)
    await session.execute(text("DELETE FROM users WHERE user_id = :u"), {"u": actor.user_id})
    left = (await session.execute(select(IdempotencyKey).where(IdempotencyKey.idempotency_id == row.idempotency_id))).scalar_one_or_none()
    assert left is None


# ------------------------------------------------------------------ uq_registration_pending_same_applicant


async def test_two_pending_registrations_of_the_same_applicant_are_rejected_in_any_case(session, world):
    plan = await world.plan()
    tag = uuid.uuid4().hex[:12]
    await world.registration(plan, email=f"itest-Ann-{tag}@Example.TEST", clan_name=f"Itest Clan {tag}")
    await must_reject(
        session,
        lambda: world.registration(plan, email=f"ITEST-ann-{tag}@example.test", clan_name=f"ITEST CLAN {tag}"),
        PENDING_SAME_APPLICANT,
    )


async def test_the_same_applicant_may_register_a_different_clan_and_different_applicants_the_same_clan(session, world):
    plan = await world.plan()
    tag = uuid.uuid4().hex[:12]
    await world.registration(plan, email=f"itest-a-{tag}@example.test", clan_name=f"Clan One {tag}")
    await world.registration(plan, email=f"itest-a-{tag}@example.test", clan_name=f"Clan Two {tag}")
    await world.registration(plan, email=f"itest-b-{tag}@example.test", clan_name=f"Clan One {tag}")


@pytest.mark.parametrize("status", ["APPROVED", "REJECTED", "DRAFT", "NEED_SUPPLEMENT", "CANCELLED"])
async def test_only_pending_registrations_collide(session, world, status):
    plan = await world.plan()
    tag = uuid.uuid4().hex[:12]
    email, name = f"itest-c-{tag}@example.test", f"Clan {tag}"
    await world.registration(plan, email=email, clan_name=name, status=status)
    await world.registration(plan, email=email, clan_name=name, status=status)  # history may repeat
    await world.registration(plan, email=email, clan_name=name)  # and one pending is still fine
    await must_reject(session, lambda: world.registration(plan, email=email, clan_name=name), PENDING_SAME_APPLICANT)


async def test_a_reviewed_registration_frees_the_slot_for_a_new_pending_one(session, world):
    plan = await world.plan()
    tag = uuid.uuid4().hex[:12]
    email, name = f"itest-d-{tag}@example.test", f"Clan {tag}"
    first = await world.registration(plan, email=email, clan_name=name)
    await must_reject(session, lambda: world.registration(plan, email=email, clan_name=name), PENDING_SAME_APPLICANT)

    first.status = "REJECTED"
    await session.flush()
    await world.registration(plan, email=email, clan_name=name)


# ------------------------------------------------------------------ the real definitions


async def index_definitions(session) -> dict[str, str]:
    rows = await session.execute(
        text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND indexname IN "
            "('uq_provisioning_job_live_per_clan', 'uq_provisioning_job_live_email', "
            "'idx_provisioning_jobs_clan_created', 'uq_registration_pending_same_applicant')"
        )
    )
    return {name: definition for name, definition in rows.all()}


async def test_the_indexes_exist_with_the_planned_definitions(session):
    defs = await index_definitions(session)
    assert set(defs) == {
        LIVE_PER_CLAN,
        LIVE_EMAIL,
        "idx_provisioning_jobs_clan_created",
        PENDING_SAME_APPLICANT,
    }, "migration 0003 is not applied to this database"

    per_clan = defs[LIVE_PER_CLAN]
    assert per_clan.startswith("CREATE UNIQUE INDEX") and "ON public.provisioning_jobs" in per_clan
    assert "(clan_id)" in per_clan and "needs_cleanup" in per_clan
    for status in ("PENDING", "RUNNING", "FAILED_RETRYABLE", "SUCCEEDED"):
        assert f"'{status}'" in per_clan, status
    assert "'FAILED'::" not in per_clan.replace("'FAILED_RETRYABLE'", "")  # a failed job is not live

    by_email = defs[LIVE_EMAIL]
    assert by_email.startswith("CREATE UNIQUE INDEX") and "lower((email)::text)" in by_email
    assert "needs_cleanup" in by_email and "'SUCCEEDED'" not in by_email

    assert defs["idx_provisioning_jobs_clan_created"].startswith("CREATE INDEX")
    assert "(clan_id, created_at DESC)" in defs["idx_provisioning_jobs_clan_created"]

    pending = defs[PENDING_SAME_APPLICANT]
    assert pending.startswith("CREATE UNIQUE INDEX") and "ON public.business_registrations" in pending
    assert "lower((representative_email)::text)" in pending and "lower((clan_name)::text)" in pending
    assert "'PENDING'" in pending


async def table_columns(session, table: str) -> list[str]:
    rows = await session.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t"),
        {"t": table},
    )
    return [r[0] for r in rows.all()]


@pytest.mark.parametrize("table", ["provisioning_jobs", "idempotency_keys"])
async def test_the_columns_are_the_orm_columns_and_none_can_hold_a_secret(session, table):
    from app.models.registry import target_metadata

    columns = await table_columns(session, table)
    assert columns, f"{table} does not exist: migration 0003 is not applied to this database"
    assert set(columns) == {c.name for c in target_metadata.tables[table].columns}
    for name in columns:
        for word in ("password", "secret", "token", "credential"):
            assert word not in name, f"{table}.{name}"


async def test_the_check_constraints_of_the_new_tables_exist_under_the_orm_names(session):
    from sqlalchemy import CheckConstraint

    from app.models.registry import target_metadata

    rows = await session.execute(
        text(
            "SELECT conname FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE c.contype = 'c' AND t.relname IN ('provisioning_jobs', 'idempotency_keys')"
        )
    )
    in_db = {r[0] for r in rows.all()}
    declared = {
        c.name
        for table in ("provisioning_jobs", "idempotency_keys")
        for c in target_metadata.tables[table].constraints
        if isinstance(c, CheckConstraint)
    }
    assert in_db == declared and len(declared) == 10


async def test_the_orm_declares_the_same_index_names_as_the_database(session):
    from app.models.registry import target_metadata

    in_db = set(await index_definitions(session))
    declared = {
        index.name
        for table in target_metadata.tables.values()
        for index in table.indexes
        if index.name in in_db
    }
    assert declared == in_db


async def test_the_database_is_at_revision_0003(session):
    rows = await session.execute(text("SELECT version_num FROM alembic_version"))
    assert [r[0] for r in rows.all()] == ["0003_provisioning_idempotency"]


# ------------------------------------------------------------------ the migration's own check on live data


def load_migration():
    path = BE_DIR / "alembic" / "versions" / "0003_provisioning_idempotency.py"
    spec = importlib.util.spec_from_file_location("migration_0003_live", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_preflight_duplicate_query_is_valid_sql_and_finds_nothing_in_a_migrated_database(session):
    """After the migration the unique index makes the check's own query return nothing."""
    migration = load_migration()
    connection = await session.connection()
    assert await connection.run_sync(migration.find_pending_duplicates) == []
    await connection.run_sync(migration.ensure_postgres_15)


async def test_the_preflight_duplicate_query_groups_exactly_what_the_index_would_reject(session):
    """With the index in place no real duplicate can exist, and tests never run DDL. So feed the
    migration's own query a VALUES list standing in for the table, and see what it groups."""
    migration = load_migration()
    ids = [str(uuid.uuid4()) for _ in range(5)]
    rows = [
        (ids[0], "Ann@Example.TEST", "Clan One", "PENDING"),
        (ids[1], "ann@example.test", "CLAN ONE", "PENDING"),  # same applicant, any case: duplicate of ids[0]
        (ids[2], "ann@example.test", "Clan Two", "PENDING"),  # other clan name: not a duplicate
        (ids[3], "ann@example.test", "clan one", "APPROVED"),  # not pending: not a duplicate
        (ids[4], "bob@example.test", "Clan One", "PENDING"),  # other applicant: not a duplicate
    ]
    params = {}
    values = []
    for i, (rid, email, name, status) in enumerate(rows):
        params.update({f"i{i}": rid, f"e{i}": email, f"c{i}": name, f"s{i}": status})
        values.append(f"(CAST(:i{i} AS uuid), :e{i}, :c{i}, :s{i}, now())")
    stand_in = (
        "(VALUES " + ", ".join(values) + ") AS business_registrations"
        "(registration_id, representative_email, clan_name, status, created_at)"
    )
    sql = migration.PENDING_DUPLICATES_SQL.replace("FROM business_registrations", "FROM " + stand_in)
    assert stand_in in sql  # the replacement really happened
    found = (await session.execute(text(sql), params)).all()
    assert len(found) == 1
    key, count = found[0]
    assert count == 2 and set(key.split()) == {ids[0], ids[1]}
    assert "@" not in key  # ids only, never an address


async def test_the_downgrade_refusal_query_counts_the_jobs_that_still_need_a_clean_up(session, world):
    """The query behind the downgrade refusal is valid on PostgreSQL and counts exactly those jobs."""
    migration = load_migration()
    connection = await session.connection()

    def count(conn) -> int:
        return int(conn.execute(text(migration.COUNT_NEEDS_CLEANUP_SQL)).scalar())

    before = await connection.run_sync(count)
    clan = await world.clan()
    await world.job(clan, status="FAILED", needs_cleanup=True)
    await world.job(await world.clan(), status="FAILED")  # failed but nothing to clean up: not counted
    await world.job(await world.clan())  # a live job: not counted
    assert await connection.run_sync(count) == before + 1
    with pytest.raises(RuntimeError, match=f"{before + 1} provisioning_jobs row"):
        await connection.run_sync(migration.ensure_no_pending_cleanup)
