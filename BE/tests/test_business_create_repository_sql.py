"""The real SQL of the E5 repository methods, compiled without a database (Mốc E, step E5): the
idempotency statements (INSERT ... ON CONFLICT DO NOTHING, the lock, SET LOCAL lock_timeout) and
the writes of the clan, its profile and its subscription. The same methods run on PostgreSQL in
the integration tests."""

from __future__ import annotations

import inspect
import re
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.family.idempotency_repository import IdempotencyRepository
from app.models.family.repository import FamilyRepository
from tests.fakes import _DbError
from tests.test_public_repository_sql import RecordingSession, compiled

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
ACTOR, KEY = uuid.uuid4(), "key-0123456789"
ENDPOINT = "POST /x/{id}/business"


@pytest.fixture
def session() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def idem(session) -> IdempotencyRepository:
    return IdempotencyRepository(session)


@pytest.fixture
def family(session) -> FamilyRepository:
    return FamilyRepository(session)


# ------------------------------------------------------------------ the idempotency statements


async def insert(idem):
    return await idem.insert_in_progress(
        actor_id=ACTOR, endpoint=ENDPOINT, idempotency_key=KEY, request_hash="a" * 64, created_at=NOW, expires_at=LATER)


async def test_the_claim_is_an_insert_on_conflict_do_nothing_on_the_unique_key_returning_the_row(idem, session):
    await insert(idem)
    sql, params = compiled(session)
    assert sql.startswith("INSERT INTO idempotency_keys")
    assert "ON CONFLICT (actor_id, endpoint, idempotency_key) DO NOTHING" in sql
    assert "RETURNING" in sql and "DO UPDATE" not in sql
    assert session.statements[0].get_execution_options().get("populate_existing") is True
    for value in (ACTOR, ENDPOINT, KEY, "a" * 64, "IN_PROGRESS", NOW, LATER):
        assert value in params.values(), value
    assert KEY not in sql and ENDPOINT not in sql  # bound parameters, never text in the statement


async def test_the_new_row_starts_in_progress_with_a_hash_of_exactly_64_characters(idem, session):
    await insert(idem)
    _, params = compiled(session)
    assert "COMPLETED" not in params.values()
    assert any(isinstance(v, str) and len(v) == 64 for v in params.values())


async def test_the_existing_row_is_read_by_the_full_key_and_locked_for_no_key_update(idem, session):
    await idem.lock_existing(actor_id=ACTOR, endpoint=ENDPOINT, idempotency_key=KEY)
    sql, params = compiled(session)
    assert sql.endswith("FOR NO KEY UPDATE")
    where = sql.split("WHERE", 1)[1]
    for column in ("actor_id", "endpoint", "idempotency_key"):
        assert f"idempotency_keys.{column} = " in where, column
    assert session.statements[0].get_execution_options().get("populate_existing") is True
    assert {ACTOR, ENDPOINT, KEY} <= set(params.values())


async def test_nothing_in_the_idempotency_statements_touches_users_or_takes_a_stronger_lock(idem, session):
    await insert(idem)
    await idem.lock_existing(actor_id=ACTOR, endpoint=ENDPOINT, idempotency_key=KEY)
    for index in range(len(session.statements)):
        sql, _ = compiled(session, index)
        assert "FOR UPDATE" not in sql.replace("FOR NO KEY UPDATE", "") and "FOR SHARE" not in sql
        assert re.search(r"\busers\b", sql) is None and "JOIN" not in sql


async def test_the_lock_timeout_is_local_to_the_transaction_and_a_bound_parameter(idem, session):
    """set_config(name, value, true): is_local = true is SET LOCAL, so it never outlives the transaction."""
    await idem.set_lock_timeout(10)
    sql, params = compiled(session)
    assert sql.startswith("SELECT set_config(")
    assert list(params.values()) == ["lock_timeout", "10s", True]  # the last argument is is_local
    assert "10s" not in sql and "lock_timeout" not in sql  # bound, never in the statement text


@pytest.mark.parametrize("bad", [0, -1, "10", 1.5, None, True, "10s'; DROP TABLE users; --"])
async def test_the_lock_timeout_only_takes_a_positive_integer(idem, session, bad):
    with pytest.raises(ValueError):
        await idem.set_lock_timeout(bad)
    assert session.statements == []  # nothing was sent


async def test_reset_and_complete_only_change_the_row_they_were_given_and_only_flush(idem, session):
    from app.models.family.entities import IdempotencyKey

    row = IdempotencyKey(idempotency_id=uuid.uuid4(), actor_id=ACTOR, endpoint=ENDPOINT, idempotency_key=KEY,
                         request_hash="a" * 64, status="COMPLETED", response_status=201, response_body={"x": 1},
                         resource_type="clan", resource_id=uuid.uuid4(), created_at=NOW, expires_at=NOW)
    await idem.reset(row, request_hash="b" * 64, created_at=LATER, expires_at=LATER)
    assert (row.request_hash, row.status, row.created_at, row.expires_at) == ("b" * 64, "IN_PROGRESS", LATER, LATER)
    assert (row.response_status, row.response_body, row.resource_type, row.resource_id) == (None, None, None, None)
    resource = uuid.uuid4()
    await idem.complete(row, response_status=201, response_body={"ok": 1}, resource_type="clan", resource_id=resource)
    assert (row.status, row.response_status, row.response_body, row.resource_type, row.resource_id) == (
        "COMPLETED", 201, {"ok": 1}, "clan", resource)
    assert session.flushes == 2 and session.statements == []  # no statement of its own: the ORM flushes the change


def test_the_idempotency_repository_never_commits():
    for name, member in inspect.getmembers(IdempotencyRepository, inspect.iscoroutinefunction):
        source = inspect.getsource(member)
        assert not re.search(r"\.(commit|rollback)\(", source), name  # a call, not the word in a docstring


# Every method says how it is scoped (a new method must be added here with a reason).
IDEMPOTENCY_SCOPE = {
    "set_lock_timeout": "no table: SET LOCAL for this transaction",
    "insert_in_progress": "actor_id, endpoint and key are the inserted unique key",
    "lock_existing": "WHERE actor_id AND endpoint AND key",
    "lock_by_resource": "WHERE resource_type AND resource_id (E6b: the key working on a provisioning job)",
    "reset": "writes the row it was given, which lock_existing returned for the full key",
    "complete": "writes the row it was given, which claim returned for the full key",
    "delete": "releases the row it was given, which lock_existing returned for the full key (E6)",
    "set_resource": "writes the row it was given, which claim returned for the full key (E6)",
}


def test_every_idempotency_method_is_accounted_for_and_the_keyed_ones_take_the_full_key():
    methods = {n for n, _ in inspect.getmembers(IdempotencyRepository, inspect.iscoroutinefunction) if not n.startswith("_")}
    assert methods == set(IDEMPOTENCY_SCOPE)
    for name in ("insert_in_progress", "lock_existing"):
        params = inspect.signature(getattr(IdempotencyRepository, name)).parameters
        assert {"actor_id", "endpoint", "idempotency_key"} <= set(params), name


# ------------------------------------------------------------------ the clan, its profile and its subscription


async def make_clan(family, **over):
    args = dict(registration_id=uuid.uuid4(), clan_code="CLAN-ABCDEFGH", name="Ho Tran", created_by=uuid.uuid4(), now=NOW)
    args.update(over)
    return await family.create_clan(**args), args


async def test_a_new_clan_is_pending_and_written_inside_a_savepoint(family, session):
    clan, args = await make_clan(family)
    assert session.savepoints == ["opened", "released"]
    assert session.added == [clan] and session.flushes == 1
    assert (clan.status, clan.registration_id, clan.clan_code, clan.name, clan.created_by) == (
        "PENDING", args["registration_id"], args["clan_code"], args["name"], args["created_by"])
    assert clan.created_at == clan.updated_at == NOW and clan.activated_at is None and clan.suspended_at is None
    assert isinstance(clan.clan_id, uuid.UUID)


@pytest.mark.parametrize("constraint", ["clans_clan_code_key", "clans_registration_id_key", "something_else"])
async def test_a_rejected_clan_rolls_back_only_the_savepoint_and_re_raises_the_integrity_error(family, session, constraint):
    session.flush_error = IntegrityError("INSERT clans", {}, _DbError(constraint))
    with pytest.raises(IntegrityError) as exc:
        await make_clan(family)
    assert exc.value.orig.diag.constraint_name == constraint
    assert session.savepoints == ["opened", "rolled back"]  # the caller's transaction is still usable


async def test_the_profile_carries_the_place_of_origin_and_the_subscription_starts_pending(family, session):
    clan_id, plan_id = uuid.uuid4(), uuid.uuid4()
    profile = await family.create_clan_profile(clan_id=clan_id, origin_place="Zed Village", now=NOW)
    empty = await family.create_clan_profile(clan_id=uuid.uuid4(), origin_place=None, now=NOW)
    sub = await family.create_subscription(clan_id=clan_id, plan_id=plan_id, starts_at=NOW, ends_at=LATER, status="PENDING", now=NOW)
    assert (profile.clan_id, profile.origin_place, empty.origin_place) == (clan_id, "Zed Village", None)
    assert (sub.clan_id, sub.plan_id, sub.starts_at, sub.ends_at, sub.status, sub.auto_renew, sub.created_at) == (
        clan_id, plan_id, NOW, LATER, "PENDING", False, NOW)
    assert isinstance(sub.subscription_id, uuid.UUID)
    assert session.flushes == 3 and session.statements == []


def test_the_new_family_methods_never_commit():
    for name in ("create_clan", "create_clan_profile", "create_subscription"):
        source = inspect.getsource(getattr(FamilyRepository, name))
        assert not re.search(r"\.(commit|rollback)\(", source), name  # a call, not the word in a docstring
