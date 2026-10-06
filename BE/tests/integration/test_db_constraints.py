"""Constraints added by migration 0002_integrity_constraints, on the real DB. Rolled back.

NEEDS THE MIGRATION APPLIED to the database these tests run against; on a database without it
they fail on purpose (that is how a missing migration shows up). Covers:
  KI-04  uq_user_sessions_token_jti_hash
  KI-08  uq_family_admin_active_assignment
  email  uq_users_email_lower (users_email_key, the exact-match unique, still exists)
  KI-03  has its own file: test_user_roles_unique_index.py
plus the real definition of every index in pg_indexes and the migration's own pre-flight check
run against the live data.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models.user_access.entities import User, UserSession
from tests.integration.factory import now

FA_CODE = "MEMBER_ACCOUNT_MANAGE"
BE_DIR = Path(__file__).resolve().parents[2]


def violated_constraint(exc: IntegrityError) -> str | None:
    """Name of the constraint or unique index the DB reports (psycopg diagnostics)."""
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


async def must_reject(session, factory, expected_constraint: str):
    """Run `factory()` in a savepoint; the DB must refuse it, naming `expected_constraint`."""
    with pytest.raises(IntegrityError) as exc:
        async with session.begin_nested():
            await factory()
    assert violated_constraint(exc.value) == expected_constraint


# ------------------------------------------------------------------ KI-08


async def test_a_second_active_clan_wide_assignment_is_rejected(session, world):
    clan, user = await world.clan(), await world.user()
    await world.fa(clan, user, FA_CODE)
    await must_reject(session, lambda: world.fa(clan, user, "PERSON_VIEW"), "uq_family_admin_active_assignment")


async def test_a_second_active_assignment_for_the_same_branch_is_rejected(session, world):
    clan, user = await world.clan(), await world.user()
    branch = await world.branch(clan)
    await world.fa(clan, user, FA_CODE, branch_id=branch)
    await must_reject(
        session, lambda: world.fa(clan, user, "PERSON_VIEW", branch_id=branch), "uq_family_admin_active_assignment"
    )


async def test_clan_wide_and_branch_limited_assignments_can_coexist(session, world):
    clan, user = await world.clan(), await world.user()
    await world.fa(clan, user, FA_CODE)
    await world.fa(clan, user, FA_CODE, branch_id=await world.branch(clan))


async def test_assignments_for_two_different_branches_can_coexist(session, world):
    clan, user = await world.clan(), await world.user()
    await world.fa(clan, user, FA_CODE, branch_id=await world.branch(clan))
    await world.fa(clan, user, FA_CODE, branch_id=await world.branch(clan))


async def test_a_new_assignment_after_a_revoke_is_allowed_and_revoked_history_may_repeat(session, world):
    clan, user = await world.clan(), await world.user()
    await world.fa(clan, user, FA_CODE, revoked=True)
    await world.fa(clan, user, FA_CODE, revoked=True)  # revoked rows are outside the index
    await world.fa(clan, user, FA_CODE)  # the new active one
    await must_reject(session, lambda: world.fa(clan, user, FA_CODE), "uq_family_admin_active_assignment")


async def test_the_same_user_in_two_clans_and_two_users_in_one_clan_are_independent(session, world):
    clan_a, clan_b = await world.clan(), await world.clan()
    user, other = await world.user(), await world.user()
    await world.fa(clan_a, user, FA_CODE)
    await world.fa(clan_b, user, FA_CODE)
    await world.fa(clan_a, other, FA_CODE)


# ------------------------------------------------------------------ e-mail


async def test_emails_that_differ_only_by_case_are_rejected_by_the_lower_index(session, world):
    tag = uuid.uuid4().hex[:12]
    first = await world.user(email=f"itest-Case-{tag}@Example.TEST")
    assert first.email == f"itest-Case-{tag}@Example.TEST"
    await must_reject(
        session, lambda: world.user(email=f"itest-case-{tag}@example.test"), "uq_users_email_lower"
    )


async def test_an_identical_email_is_still_rejected(session, world):
    tag = uuid.uuid4().hex[:12]
    await world.user(email=f"itest-same-{tag}@example.test")
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await world.user(email=f"itest-same-{tag}@example.test")


async def test_different_emails_are_allowed_and_the_stored_case_is_kept(session, world):
    tag = uuid.uuid4().hex[:12]
    a = await world.user(email=f"itest-Mixed-{tag}@Example.test")
    b = await world.user(email=f"itest-other-{tag}@example.test")
    stored = (await session.execute(select(User.email).where(User.user_id == a.user_id))).scalar_one()
    assert stored == f"itest-Mixed-{tag}@Example.test"  # email is never lowercased (decision 24)
    assert a.user_id != b.user_id


async def test_the_exact_match_unique_users_email_key_still_exists(session):
    rows = await session.execute(
        text("SELECT conname FROM pg_constraint WHERE conname = 'users_email_key' AND contype = 'u'")
    )
    assert rows.scalar_one_or_none() == "users_email_key"


# ------------------------------------------------------------------ KI-04


def raw_session(user, token_hash: str | None) -> UserSession:
    t = now()
    return UserSession(
        session_id=uuid.uuid4(),
        user_id=user.user_id,
        token_jti_hash=token_hash,
        created_at=t,
        expires_at=t + timedelta(hours=8),
    )


async def test_a_duplicate_token_hash_is_rejected_by_the_unique_index(session, world):
    a, b = await world.user(), await world.user()
    token_hash = uuid.uuid4().hex + uuid.uuid4().hex

    async def add(user):
        session.add(raw_session(user, token_hash))
        await session.flush()

    await add(a)
    await must_reject(session, lambda: add(b), "uq_user_sessions_token_jti_hash")


async def test_sessions_without_a_hash_are_not_in_conflict_with_each_other(session, world):
    user = await world.user()
    for _ in range(3):
        session.add(raw_session(user, None))
    await session.flush()  # NULLs are distinct: no IntegrityError


async def test_different_hashes_are_allowed(session, world):
    user = await world.user()
    await world.session_for(user)
    await world.session_for(user)


# ------------------------------------------------------------------ the real index definitions


async def index_definitions(session) -> dict[str, str]:
    rows = await session.execute(
        text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' "
            "AND indexname IN ('uq_active_user_role_scope', 'uq_user_sessions_token_jti_hash', "
            "'uq_family_admin_active_assignment', 'uq_users_email_lower')"
        )
    )
    return {name: definition for name, definition in rows.all()}


async def test_the_four_indexes_exist_with_the_planned_definitions(session):
    defs = await index_definitions(session)
    assert set(defs) == {
        "uq_active_user_role_scope",
        "uq_user_sessions_token_jti_hash",
        "uq_family_admin_active_assignment",
        "uq_users_email_lower",
    }, "migration 0002 is not applied to this database"
    for definition in defs.values():
        assert definition.startswith("CREATE UNIQUE INDEX")

    role = defs["uq_active_user_role_scope"]
    assert "(user_id, role_id, clan_id)" in role and "NULLS NOT DISTINCT" in role
    assert "WHERE (revoked_at IS NULL)" in role

    fa = defs["uq_family_admin_active_assignment"]
    assert "ON public.family_admin_assignments" in fa and "(clan_id, user_id, branch_id)" in fa
    assert "NULLS NOT DISTINCT" in fa and "WHERE (revoked_at IS NULL)" in fa

    assert "ON public.user_sessions" in defs["uq_user_sessions_token_jti_hash"]
    assert "(token_jti_hash)" in defs["uq_user_sessions_token_jti_hash"]
    assert "NULLS NOT DISTINCT" not in defs["uq_user_sessions_token_jti_hash"]  # NULL hashes stay allowed

    assert "ON public.users" in defs["uq_users_email_lower"] and "lower(" in defs["uq_users_email_lower"]


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


# ------------------------------------------------------------------ the migration's own check on live data


def load_migration():
    path = BE_DIR / "alembic" / "versions" / "0002_integrity_constraints.py"
    spec = importlib.util.spec_from_file_location("migration_0002_live", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_preflight_check_finds_no_duplicates_in_a_migrated_database(session):
    """After the migration the unique indexes make the check's own queries return nothing."""
    migration = load_migration()
    connection = await session.connection()
    assert await connection.run_sync(migration.find_duplicates) == []
    await connection.run_sync(migration.ensure_postgres_15)
