"""Idempotency-Key support (Mốc E): the header, the request hash, and the claim / complete protocol.

Scope of a key: (the signed-in caller, the endpoint, the key), with a 7-day life (`expires_at`).
There is no cleanup job (KI-21): an expired row is only noticed when its key is used again, and
is then re-armed in place.

Two layers, so that E6 (which calls Firebase and cannot hold one transaction open across it) can
use the same protocol in TWO PHASES:

  claim_idempotency(...)      public. INSERT ... ON CONFLICT DO NOTHING for the key, or read and
                              lock the existing row. Outcome NEW, REPLAY or IN_PROGRESS; a key
                              reused with a different request_hash raises IDEMPOTENCY_KEY_CONFLICT.
  complete_idempotency(...)   public. Stores the response and marks the row COMPLETED.
  run_idempotent(...)         a thin wrapper for the ONE-transaction case (E5): claim, run the work,
                              complete, commit once. Nothing in it is private to E5.

How E6 will use the two phases (NOT built yet; nothing here makes it impossible):
  phase 1  one transaction: claim (outcome NEW), create the job row (and whatever must exist
           before the call), then COMMIT. The key row stays IN_PROGRESS, now visible to others:
           a concurrent request with the same key gets outcome IN_PROGRESS (E6 answers 409 with
           Retry-After, or points at the job through row.resource_id).
  call     Firebase (no transaction open).
  phase 2  a new transaction: lock the key row again, record the result on the job, then
           complete_idempotency(...) and COMMIT.
  A process that dies between the phases leaves the row IN_PROGRESS until it expires; recovery is
  E6's retry of the stuck job (amendment A1), not this module's concern.

In ONE transaction (E5) the key row is written in the same transaction as the work, so a request
that dies half-way simply rolls everything back, key included: a key can never be stuck. Only a
SUCCESSFUL response is stored and replayed; an error is not stored, so a retry re-checks the
conditions from scratch.

The hash covers the method, the endpoint template, the path parameters and the normalized body.
A stored response never holds a secret: complete_idempotency refuses a body with a key whose name
suggests one (password, token, secret).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Mapping, Protocol

from fastapi import Header
from sqlalchemy.exc import OperationalError

from app.core.db_errors import lock_wait_timed_out
from app.core.errors import AppError
from app.schemas.errors import ErrorCode

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
IDEMPOTENCY_REPLAYED_HEADER = "Idempotency-Replayed"
KEY_MIN_LENGTH = 8
KEY_MAX_LENGTH = 128
KEY_PATTERN = r"^[\x21-\x7E]+$"  # printable ASCII, no space
IDEMPOTENCY_TTL = timedelta(days=7)
LOCK_TIMEOUT_SECONDS = 10  # a lock wait longer than this means a stuck transaction, not a race

NEW = "NEW"
REPLAY = "REPLAY"
IN_PROGRESS = "IN_PROGRESS"
COMPLETED = "COMPLETED"

_SECRET_KEY_WORDS = ("password", "token", "secret")


# ----- the header -----


def idempotency_key_header(
    idempotency_key: str = Header(
        ...,
        alias=IDEMPOTENCY_KEY_HEADER,
        min_length=KEY_MIN_LENGTH,
        max_length=KEY_MAX_LENGTH,
        pattern=KEY_PATTERN,
        description=(
            "Required. 8 to 128 printable ASCII characters without spaces (a UUID is recommended). "
            "The same key with the same request replays the first response; the same key with a "
            "different request is 409 IDEMPOTENCY_KEY_CONFLICT."
        ),
    ),
) -> str:
    """Missing, too short, too long or odd characters: the standard 422 (the value is never echoed)."""
    return idempotency_key


# ----- the request hash -----


def _canonical(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def compute_request_hash(
    *,
    method: str,
    endpoint: str,
    path_params: Mapping[str, Any] | None = None,
    body: Mapping[str, Any] | None = None,
) -> str:
    """SHA-256 (64 hex characters) of the canonical JSON of the request.

    `endpoint` is the route template; `path_params` the values that fill it (a UUID is written in
    its canonical lower-case form); `body` the NORMALIZED body: pass it through
    model_dump(mode="json", exclude_none=True) so that an absent field and a null one hash alike.
    """
    document = {
        "method": method.upper(),
        "endpoint": endpoint,
        "path": _canonical(path_params or {}),
        "body": _canonical(body or {}),
    }
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ----- claim / complete -----


class IdempotencyStore(Protocol):
    """What the protocol needs from the database layer (IdempotencyRepository, or a fake)."""

    async def set_lock_timeout(self, seconds: int) -> None: ...

    async def insert_in_progress(
        self, *, actor_id: uuid.UUID, endpoint: str, idempotency_key: str, request_hash: str,
        created_at: datetime, expires_at: datetime,
    ) -> Any | None: ...

    async def lock_existing(self, *, actor_id: uuid.UUID, endpoint: str, idempotency_key: str) -> Any | None: ...

    async def lock_by_resource(self, *, resource_type: str, resource_id: uuid.UUID) -> Any | None: ...

    async def reset(self, row: Any, *, request_hash: str, created_at: datetime, expires_at: datetime) -> None: ...

    async def delete(self, row: Any) -> None: ...

    async def set_resource(self, row: Any, *, resource_type: str, resource_id: uuid.UUID) -> None: ...

    async def complete(
        self, row: Any, *, response_status: int, response_body: dict[str, Any] | None,
        resource_type: str | None, resource_id: uuid.UUID | None,
    ) -> None: ...


@dataclass(frozen=True)
class IdempotencyClaim:
    outcome: str  # NEW | REPLAY | IN_PROGRESS
    row: Any  # the idempotency_keys row (REPLAY: row.response_status / row.response_body)


@dataclass(frozen=True)
class IdempotentOutcome:
    """What the work of one request produced: stored for replay when it is a success."""

    status: int
    body: dict[str, Any]
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None


@dataclass(frozen=True)
class IdempotentResult:
    status: int
    body: dict[str, Any]
    replayed: bool


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def busy_error() -> AppError:
    """Another request holds the lock for longer than the lock timeout, or a key is still IN_PROGRESS."""
    return AppError(
        ErrorCode.STATE_CONFLICT,
        "Another request for the same resource is still in progress; retry shortly.",
        headers={"Retry-After": "1"},
    )


async def claim_idempotency(
    store: IdempotencyStore,
    *,
    actor_id: uuid.UUID,
    endpoint: str,
    key: str,
    request_hash: str,
    now: datetime,
) -> IdempotencyClaim:
    """Phase 1. Takes the key, or tells what already exists. Writes inside the CALLER's transaction.

    The wait for a concurrent request with the same key happens in the INSERT itself (the unique
    index): this call returns only after that request committed or rolled back.
    """
    await store.set_lock_timeout(LOCK_TIMEOUT_SECONDS)
    expires_at = now + IDEMPOTENCY_TTL
    for _ in range(2):
        row = await store.insert_in_progress(
            actor_id=actor_id, endpoint=endpoint, idempotency_key=key, request_hash=request_hash,
            created_at=now, expires_at=expires_at,
        )
        if row is not None:
            return IdempotencyClaim(NEW, row)
        existing = await store.lock_existing(actor_id=actor_id, endpoint=endpoint, idempotency_key=key)
        if existing is None:
            continue  # the row vanished between the two statements: take the key again
        if existing.expires_at <= now:  # an old key, free to be used again
            await store.reset(existing, request_hash=request_hash, created_at=now, expires_at=expires_at)
            return IdempotencyClaim(NEW, existing)
        if existing.request_hash != request_hash:
            raise AppError(ErrorCode.IDEMPOTENCY_KEY_CONFLICT)
        if existing.status == COMPLETED:
            return IdempotencyClaim(REPLAY, existing)
        return IdempotencyClaim(IN_PROGRESS, existing)
    raise AppError(ErrorCode.INTERNAL_ERROR)  # two vanishing rows in a row: not a race, a bug


def _assert_no_secret(value: Any, path: str = "response_body") -> None:
    if isinstance(value, Mapping):
        for name, inner in value.items():
            if any(word in str(name).lower() for word in _SECRET_KEY_WORDS):
                raise ValueError(f"{path}.{name}: a stored idempotent response must not hold a secret")
            _assert_no_secret(inner, f"{path}.{name}")
    elif isinstance(value, (list, tuple)):
        for index, inner in enumerate(value):
            _assert_no_secret(inner, f"{path}[{index}]")


async def complete_idempotency(
    store: IdempotencyStore,
    row: Any,
    *,
    response_status: int,
    response_body: dict[str, Any] | None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
) -> None:
    """Phase 2. Records the response and marks the row COMPLETED (inside the caller's transaction)."""
    if response_body is not None:
        _assert_no_secret(response_body)
        json.dumps(response_body)  # must be plain JSON: it goes to a jsonb column
    await store.complete(
        row, response_status=response_status, response_body=response_body,
        resource_type=resource_type, resource_id=resource_id,
    )


# ----- the one-transaction wrapper -----


class _UnitOfWork(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


async def rollback_quietly(db: _UnitOfWork) -> None:
    try:
        await db.rollback()
    except Exception:  # noqa: BLE001 - the original error is the one worth reporting
        pass


_rollback_quietly = rollback_quietly  # (the name run_idempotent has always used)


@asynccontextmanager
async def rollback_on_error(db: _UnitOfWork):
    """One database transaction of a multi-transaction flow (E6): any error rolls it back, and the wait
    for a lock that outlasts lock_timeout becomes 409 with Retry-After instead of a 503."""
    try:
        yield
    except OperationalError as exc:
        await _rollback_quietly(db)
        if lock_wait_timed_out(exc):
            raise busy_error() from None
        raise
    except BaseException:
        await _rollback_quietly(db)
        raise


async def run_idempotent(
    *,
    db: _UnitOfWork,
    store: IdempotencyStore,
    actor_id: uuid.UUID,
    endpoint: str,
    key: str,
    request_hash: str,
    execute: Callable[[], Awaitable[IdempotentOutcome]],
    now: datetime | None = None,
) -> IdempotentResult:
    """claim, run the work, complete, COMMIT ONCE: all in one transaction.

    `execute` writes through the repositories (which only flush) and never commits. Any error
    rolls the whole transaction back, the key row included. A replay writes nothing.
    """
    moment = now or utcnow()
    try:
        claim = await claim_idempotency(
            store, actor_id=actor_id, endpoint=endpoint, key=key, request_hash=request_hash, now=moment
        )
        if claim.outcome == REPLAY:
            return IdempotentResult(
                status=claim.row.response_status, body=claim.row.response_body or {}, replayed=True
            )
        if claim.outcome == IN_PROGRESS:
            raise busy_error()  # cannot happen in one transaction; kept for a row left by a two-phase caller
        outcome = await execute()
        await complete_idempotency(
            store, claim.row, response_status=outcome.status, response_body=outcome.body,
            resource_type=outcome.resource_type, resource_id=outcome.resource_id,
        )
        await db.commit()
        return IdempotentResult(status=outcome.status, body=outcome.body, replayed=False)
    except OperationalError as exc:
        await _rollback_quietly(db)
        if lock_wait_timed_out(exc):
            raise busy_error() from None
        raise
    except BaseException:
        await _rollback_quietly(db)
        raise
