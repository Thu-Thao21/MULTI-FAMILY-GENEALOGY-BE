"""The idempotency core (Mốc E, step E5), without a database: the header, the request hash, the
claim / complete protocol (public, so that E6 can use it in two phases) and the one-transaction
wrapper run_idempotent. The real SQL is in test_business_create_repository_sql.py, the real
database in the integration tests."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.errors import AppError, register_exception_handlers
from app.core.idempotency import (
    IDEMPOTENCY_TTL,
    IN_PROGRESS,
    LOCK_TIMEOUT_SECONDS,
    NEW,
    REPLAY,
    IdempotentOutcome,
    claim_idempotency,
    complete_idempotency,
    compute_request_hash,
    idempotency_key_header,
    run_idempotent,
)
from app.core.request_id import RequestIdMiddleware
from app.schemas.errors import ErrorCode
from tests.fakes import FakeIdempotencyRepo, FakeTx, _SqlStateError

NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
ACTOR, OTHER_ACTOR = uuid.uuid4(), uuid.uuid4()
ENDPOINT = "POST /things/{thing_id}/make"
KEY = "key-0123456789"
HASH_A, HASH_B = "a" * 64, "b" * 64


def code(exc: AppError) -> str:
    return str(exc.code)


# ------------------------------------------------------------------ the request hash


def h(**kw):
    base = dict(method="POST", endpoint=ENDPOINT, path_params={"thing_id": uuid.UUID(int=1)}, body={"clan_code": "ABC"})
    return compute_request_hash(**{**base, **kw})


def test_the_hash_is_64_hex_characters_and_stable():
    value = h()
    assert len(value) == 64 and int(value, 16) >= 0
    assert value == h() == h(body={"clan_code": "ABC"})


def test_the_hash_does_not_depend_on_key_order_or_on_uuid_spelling_and_treats_no_body_as_empty():
    assert h(body={"a": 1, "b": {"y": 2, "x": 1}}) == h(body={"b": {"x": 1, "y": 2}, "a": 1})
    assert h(path_params={"thing_id": uuid.UUID(int=1)}) == h(path_params={"thing_id": uuid.UUID("00000000-0000-0000-0000-000000000001")})
    assert h(body=None) == h(body={})
    assert h(method="post") == h(method="POST")


@pytest.mark.parametrize("change", [
    dict(method="PUT"), dict(endpoint="POST /other/{thing_id}/make"),
    dict(path_params={"thing_id": uuid.UUID(int=2)}), dict(path_params={}),
    dict(body={"clan_code": "ABD"}), dict(body={"clan_code": "ABC", "extra": 1}), dict(body={}),
])
def test_anything_that_makes_the_request_different_changes_the_hash(change):
    assert h(**change) != h()


def test_the_path_parameter_is_in_the_hash_so_another_resource_conflicts():
    assert h(path_params={"thing_id": uuid.UUID(int=1)}) != h(path_params={"thing_id": uuid.UUID(int=2)})


def test_unicode_is_hashed_as_utf8_and_a_null_field_is_the_callers_to_drop():
    assert h(body={"name": "Nguyễn"}) == h(body={"name": "Nguyễn"})
    assert h(body={"name": "Nguyễn"}) != h(body={"name": "Nguyen"})
    assert h(body={"a": None}) != h(body={})  # the caller passes exclude_none=True to make them equal


def test_the_business_request_normalization_makes_absent_and_null_equal():
    from app.schemas.business import BusinessCreateRequest

    dump = lambda m: m.model_dump(mode="json", exclude_none=True)  # noqa: E731
    assert h(body=dump(BusinessCreateRequest())) == h(body=dump(BusinessCreateRequest(clan_code=None))) == h(body={})
    assert h(body=dump(BusinessCreateRequest(clan_code="ABC"))) == h()


# ------------------------------------------------------------------ the header


def header_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    @app.post("/probe")
    async def probe(key: str = Depends(idempotency_key_header)):
        return {"key": key}

    return TestClient(app)


def test_the_header_is_required():
    r = header_client().post("/probe")
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "header.Idempotency-Key" in r.json()["error"]["message"]


@pytest.mark.parametrize("value, accepted", [
    ("1234567", False), ("12345678", True), ("x" * 128, True), ("x" * 129, False),
    ("550e8400-e29b-41d4-a716-446655440000", True), ("a.b_c-d:e~f=g/h+i", True),
    ("has space inside", False), ("quote\"inside1", True),
])
def test_the_key_is_8_to_128_printable_ascii_characters_without_spaces(value, accepted):
    r = header_client().post("/probe", headers={"Idempotency-Key": value})
    assert (r.status_code == 200) is accepted, (value, r.text)
    if accepted:
        assert r.json() == {"key": value}  # the value arrives untouched
    else:
        assert r.status_code == 422 and value not in r.text  # never echoed


def test_an_empty_header_is_refused_and_the_header_name_is_case_insensitive():
    assert header_client().post("/probe", headers={"Idempotency-Key": ""}).status_code == 422
    assert header_client().post("/probe", headers={"idempotency-key": KEY}).status_code == 200


def test_the_key_is_not_logged(caplog):
    caplog.set_level(logging.DEBUG)
    header_client().post("/probe", headers={"Idempotency-Key": "secret-looking-key-123"})
    app_logs = " | ".join(r.getMessage() for r in caplog.records if not r.name.startswith(("httpx", "httpcore")))
    assert "secret-looking-key-123" not in app_logs


# ------------------------------------------------------------------ claim


def claim(store, **kw):
    args = dict(actor_id=ACTOR, endpoint=ENDPOINT, key=KEY, request_hash=HASH_A, now=NOW)
    return claim_idempotency(store, **{**args, **kw})


async def test_the_first_claim_creates_an_in_progress_row_that_lives_seven_days():
    store = FakeIdempotencyRepo()
    result = await claim(store)
    assert result.outcome == NEW
    row = result.row
    assert (row.actor_id, row.endpoint, row.idempotency_key, row.request_hash, row.status) == (ACTOR, ENDPOINT, KEY, HASH_A, "IN_PROGRESS")
    assert row.expires_at - row.created_at == IDEMPOTENCY_TTL == timedelta(days=7)
    assert len(store.rows) == 1


async def test_the_lock_timeout_is_set_before_anything_else():
    store = FakeIdempotencyRepo()
    await claim(store)
    assert store.calls[0] == "idem.set_lock_timeout" and store.lock_timeout_seconds == LOCK_TIMEOUT_SECONDS == 10


async def test_a_second_claim_of_a_completed_key_with_the_same_hash_is_a_replay():
    store = FakeIdempotencyRepo()
    first = await claim(store)
    await complete_idempotency(store, first.row, response_status=201, response_body={"ok": True}, resource_type="thing", resource_id=uuid.UUID(int=5))
    again = await claim(store)
    assert again.outcome == REPLAY and again.row is first.row
    assert (again.row.response_status, again.row.response_body, again.row.resource_id) == (201, {"ok": True}, uuid.UUID(int=5))
    assert len(store.rows) == 1


async def test_the_same_key_with_another_hash_is_a_conflict_whatever_its_status():
    store = FakeIdempotencyRepo()
    first = await claim(store)
    with pytest.raises(AppError) as in_progress:
        await claim(store, request_hash=HASH_B)
    assert code(in_progress.value) == "IDEMPOTENCY_KEY_CONFLICT" and in_progress.value.status_code == 409
    await complete_idempotency(store, first.row, response_status=201, response_body={})
    with pytest.raises(AppError) as completed:
        await claim(store, request_hash=HASH_B)
    assert code(completed.value) == "IDEMPOTENCY_KEY_CONFLICT"
    assert store.rows[0].request_hash == HASH_A  # the first request is untouched


async def test_a_key_is_scoped_by_caller_and_endpoint_and_the_key_itself():
    store = FakeIdempotencyRepo()
    await claim(store)
    for kw in (dict(actor_id=OTHER_ACTOR), dict(endpoint="POST /other"), dict(key="another-key-9999")):
        assert (await claim(store, request_hash=HASH_B, **kw)).outcome == NEW, kw
    assert len(store.rows) == 4


async def test_an_expired_key_is_reused_in_place_even_with_another_hash():
    store = FakeIdempotencyRepo()
    first = await claim(store)
    await complete_idempotency(store, first.row, response_status=201, response_body={"old": 1}, resource_type="thing", resource_id=uuid.UUID(int=5))
    later = NOW + IDEMPOTENCY_TTL + timedelta(seconds=1)
    result = await claim(store, request_hash=HASH_B, now=later)
    assert result.outcome == NEW and result.row is first.row and len(store.rows) == 1
    row = result.row
    assert (row.request_hash, row.status, row.created_at, row.expires_at) == (HASH_B, "IN_PROGRESS", later, later + IDEMPOTENCY_TTL)
    assert (row.response_status, row.response_body, row.resource_type, row.resource_id) == (None, None, None, None)
    assert "idem.reset" in store.calls


async def test_the_expiry_boundary_counts_as_expired_and_one_second_before_does_not():
    store = FakeIdempotencyRepo()
    first = await claim(store)
    await complete_idempotency(store, first.row, response_status=201, response_body={})
    assert (await claim(store, now=NOW + IDEMPOTENCY_TTL - timedelta(seconds=1))).outcome == REPLAY
    assert (await claim(store, now=NOW + IDEMPOTENCY_TTL)).outcome == NEW


async def test_a_row_that_vanishes_between_the_insert_and_the_read_is_taken_again():
    store = FakeIdempotencyRepo()
    await claim(store)
    store.vanish_once = True
    result = await claim(store)
    assert result.outcome == NEW and len(store.rows) == 1
    assert store.calls.count("idem.insert") == 3  # first claim, the failed insert, the retry


async def test_two_vanishing_rows_in_a_row_is_a_bug_not_a_race():
    class Vanishing(FakeIdempotencyRepo):
        async def lock_existing(self, **kw):
            await super().lock_existing(**kw)
            return None

    store = Vanishing()
    await claim(store)
    with pytest.raises(AppError) as exc:
        await claim(store)
    assert code(exc.value) == "INTERNAL_ERROR"
    # the first claim, then exactly TWO attempts: it gives up, it does not loop on a row that keeps vanishing
    assert store.calls.count("idem.insert") == 3 and store.calls.count("idem.lock_existing") == 2


async def test_a_row_left_in_progress_by_a_two_phase_caller_is_reported_not_replayed():
    store = FakeIdempotencyRepo()
    await claim(store)
    again = await claim(store)
    assert again.outcome == IN_PROGRESS


# ------------------------------------------------------------------ complete


async def test_complete_stores_the_response_and_marks_the_row_completed():
    store = FakeIdempotencyRepo()
    first = await claim(store)
    await complete_idempotency(store, first.row, response_status=201, response_body={"clan_id": str(uuid.UUID(int=9)), "n": [1, {"a": 2}]}, resource_type="clan", resource_id=uuid.UUID(int=9))
    row = store.rows[0]
    assert (row.status, row.response_status, row.resource_type, row.resource_id) == ("COMPLETED", 201, "clan", uuid.UUID(int=9))


@pytest.mark.parametrize("body", [
    {"password": "x"}, {"temporary_password": "x"}, {"Temp_Password": "x"}, {"access_token": "x"},
    {"id_token": "x"}, {"client_secret": "x"}, {"outer": {"inner": {"password": "x"}}},
    {"items": [{"ok": 1}, {"token": "x"}]},
])
async def test_a_stored_response_may_never_hold_a_secret(body):
    store = FakeIdempotencyRepo()
    first = await claim(store)
    with pytest.raises(ValueError):
        await complete_idempotency(store, first.row, response_status=201, response_body=body)
    assert store.rows[0].status == "IN_PROGRESS"  # nothing was stored


async def test_a_stored_response_must_be_plain_json():
    store = FakeIdempotencyRepo()
    first = await claim(store)
    for body in ({"when": NOW}, {"id": uuid.UUID(int=1)}):
        with pytest.raises(TypeError):
            await complete_idempotency(store, first.row, response_status=201, response_body=body)


async def test_complete_accepts_no_body():
    store = FakeIdempotencyRepo()
    first = await claim(store)
    await complete_idempotency(store, first.row, response_status=204, response_body=None)
    assert store.rows[0].status == "COMPLETED" and store.rows[0].response_body is None


# ------------------------------------------------------------------ the one-transaction wrapper


def run(store, tx, execute, **kw):
    args = dict(db=tx, store=store, actor_id=ACTOR, endpoint=ENDPOINT, key=KEY, request_hash=HASH_A, execute=execute, now=NOW)
    return run_idempotent(**{**args, **kw})


def world():
    store = FakeIdempotencyRepo()
    tx = FakeTx(idem=store)
    return store, tx


async def test_a_success_runs_the_work_inside_the_claim_stores_the_response_and_commits_once():
    store, tx = world()
    tx.begin()
    seen = []

    async def work():
        seen.append(list(store.calls))
        return IdempotentOutcome(201, {"ok": True}, "thing", uuid.UUID(int=7))

    result = await run(store, tx, work)
    assert (result.status, result.body, result.replayed) == (201, {"ok": True}, False)
    assert seen == [["idem.set_lock_timeout", "idem.insert"]]  # the work runs after the claim, before complete
    assert store.calls[-1] == "idem.complete" and tx.events == ["commit"]
    assert store.rows[0].status == "COMPLETED" and store.rows[0].resource_id == uuid.UUID(int=7)


async def test_a_replay_returns_the_stored_response_runs_nothing_and_writes_nothing():
    store, tx = world()
    tx.begin()

    async def work():
        return IdempotentOutcome(201, {"clan": 1}, "thing", uuid.UUID(int=7))

    await run(store, tx, work)
    tx.events.clear()
    tx.begin()

    async def must_not_run():
        raise AssertionError("a replay must not run the work again")

    again = await run(store, tx, must_not_run)
    assert (again.status, again.body, again.replayed) == (201, {"clan": 1}, True)
    assert tx.events == [] and len(store.rows) == 1  # no commit, no rollback, no new row


async def test_an_error_in_the_work_rolls_back_and_the_key_is_not_stored():
    store, tx = world()
    tx.begin()

    async def boom():
        raise AppError(ErrorCode.STATE_CONFLICT)

    with pytest.raises(AppError):
        await run(store, tx, boom)
    assert tx.events == ["rollback"] and store.rows == []  # no stuck key: a retry starts from scratch

    tx.begin()

    async def fine():
        return IdempotentOutcome(201, {"ok": 1})

    assert (await run(store, tx, fine)).replayed is False  # the same key is usable again


async def test_an_unexpected_error_also_rolls_back_and_propagates_unchanged():
    store, tx = world()
    tx.begin()

    async def bug():
        raise KeyError("bug")

    with pytest.raises(KeyError):
        await run(store, tx, bug)
    assert tx.events == ["rollback"] and store.rows == []


async def test_a_different_request_with_the_same_key_is_a_conflict_and_changes_nothing():
    store, tx = world()
    tx.begin()

    async def work():
        return IdempotentOutcome(201, {"v": 1})

    await run(store, tx, work)
    tx.events.clear()
    tx.begin()
    with pytest.raises(AppError) as exc:
        await run(store, tx, work, request_hash=HASH_B)
    assert code(exc.value) == "IDEMPOTENCY_KEY_CONFLICT"
    assert store.rows[0].request_hash == HASH_A and store.rows[0].response_body == {"v": 1}


@pytest.mark.parametrize("where", ["claim", "work"])
async def test_a_lock_wait_timeout_is_409_with_retry_after_not_a_503(where):
    store, tx = world()
    tx.begin()
    if where == "claim":
        store.wait_error = True

    async def work():
        raise OperationalError("SELECT ... FOR NO KEY UPDATE", {}, _SqlStateError("55P03"))

    with pytest.raises(AppError) as exc:
        await run(store, tx, work)
    assert code(exc.value) == "STATE_CONFLICT" and exc.value.status_code == 409
    assert exc.value.headers == {"Retry-After": "1"}
    assert tx.events == ["rollback"]


async def test_any_other_database_error_is_not_turned_into_a_409():
    store, tx = world()
    tx.begin()

    async def work():
        raise OperationalError("SELECT 1", {}, _SqlStateError("57P01"))  # admin shutdown: a real outage

    with pytest.raises(OperationalError):
        await run(store, tx, work)
    assert tx.events == ["rollback"]


async def test_a_failed_commit_rolls_back_and_the_key_is_not_left_behind():
    store, tx = world()
    tx.begin()
    tx.fail_commit = True

    async def work():
        return IdempotentOutcome(201, {"ok": 1})

    with pytest.raises(OperationalError):
        await run(store, tx, work)
    assert tx.events == ["commit", "rollback"] and store.rows == []  # the commit was tried, then undone


async def test_a_response_with_a_secret_is_refused_and_nothing_is_committed():
    store, tx = world()
    tx.begin()

    async def work():
        return IdempotentOutcome(201, {"temporary_password": "hunter2"})

    with pytest.raises(ValueError):
        await run(store, tx, work)
    assert tx.events == ["rollback"] and store.rows == []


async def test_a_key_row_left_in_progress_is_reported_as_busy():
    store, tx = world()
    tx.begin()
    await claim(store)  # a two-phase caller committed its first phase

    async def work():
        raise AssertionError("must not run")

    with pytest.raises(AppError) as exc:
        await run(store, tx, work)
    assert code(exc.value) == "STATE_CONFLICT" and exc.value.headers == {"Retry-After": "1"}


# ------------------------------------------------------------------ the two-phase shape E6 will use


async def test_the_public_claim_and_complete_support_a_two_phase_flow():
    """E6: phase 1 claim + commit; the key row is then visible as IN_PROGRESS and carries the job id;
    phase 2 completes it later; afterwards the same key replays. Nothing here is built for E6: it
    only proves the primitives allow it."""
    store, tx = world()
    tx.begin()
    first = await claim(store)
    assert first.outcome == NEW
    first.row.resource_type, first.row.resource_id = "provisioning_job", uuid.UUID(int=77)  # phase 1 writes the job id
    await tx.commit()  # ... and COMMITS before calling Firebase

    tx.begin()  # a concurrent request meanwhile
    meanwhile = await claim(store)
    assert meanwhile.outcome == IN_PROGRESS and meanwhile.row.resource_id == uuid.UUID(int=77)
    with pytest.raises(AppError):
        await claim(store, request_hash=HASH_B)

    tx.begin()  # phase 2, after Firebase answered
    again = await claim(store)
    assert again.outcome == IN_PROGRESS
    await complete_idempotency(store, again.row, response_status=202, response_body={"job_id": str(uuid.UUID(int=77)), "status": "SUCCEEDED"}, resource_type="provisioning_job", resource_id=uuid.UUID(int=77))
    await tx.commit()

    final = await claim(store)
    assert final.outcome == REPLAY and final.row.response_status == 202


def test_run_idempotent_is_a_thin_layer_over_the_public_primitives():
    import inspect

    import app.core.idempotency as module

    source = inspect.getsource(module.run_idempotent)
    assert "claim_idempotency(" in source and "complete_idempotency(" in source
    for name in ("claim_idempotency", "complete_idempotency", "compute_request_hash", "idempotency_key_header"):
        assert not name.startswith("_") and callable(getattr(module, name))
