"""Database access for `idempotency_keys` (migration 0003). Only flushes: never commits.

Every statement is scoped by (actor_id, endpoint, idempotency_key): the unique index
uq_idempotency_actor_endpoint_key. The logic (replay, conflict, expiry) lives in
app/core/idempotency.py; this class only reads and writes rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.family.entities import IdempotencyKey


class IdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def set_lock_timeout(self, seconds: int) -> None:
        """`lock_timeout` for the rest of THIS transaction only (set_config with is_local = true is
        SET LOCAL as a bound-parameter statement: safe behind a transaction pooler, it never
        outlives the transaction). Bounds every later lock wait."""
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 1:
            raise ValueError("seconds must be a positive integer")
        await self._session.execute(select(func.set_config("lock_timeout", f"{seconds}s", True)))

    async def insert_in_progress(
        self,
        *,
        actor_id: uuid.UUID,
        endpoint: str,
        idempotency_key: str,
        request_hash: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> IdempotencyKey | None:
        """INSERT ... ON CONFLICT DO NOTHING. Returns the new row, or None when the key exists.

        When the conflicting row belongs to a transaction that is still open, PostgreSQL makes
        this statement WAIT for that transaction to end: a concurrent request with the same key
        then sees the committed result (or, if the first one rolled back, inserts its own row).
        """
        stmt = (
            pg_insert(IdempotencyKey)
            .values(
                idempotency_id=uuid.uuid4(),
                actor_id=actor_id,
                endpoint=endpoint,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                status="IN_PROGRESS",
                created_at=created_at,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    IdempotencyKey.actor_id,
                    IdempotencyKey.endpoint,
                    IdempotencyKey.idempotency_key,
                ]
            )
            .returning(IdempotencyKey)
        )
        result = await self._session.execute(
            select(IdempotencyKey).from_statement(stmt).execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def lock_existing(
        self, *, actor_id: uuid.UUID, endpoint: str, idempotency_key: str
    ) -> IdempotencyKey | None:
        """The row of a key, locked FOR NO KEY UPDATE and re-read from the database."""
        stmt = (
            select(IdempotencyKey)
            .where(
                IdempotencyKey.actor_id == actor_id,
                IdempotencyKey.endpoint == endpoint,
                IdempotencyKey.idempotency_key == idempotency_key,
            )
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def reset(
        self, row: IdempotencyKey, *, request_hash: str, created_at: datetime, expires_at: datetime
    ) -> None:
        """Re-arm an EXPIRED row for a new request (it was locked by lock_existing)."""
        row.request_hash = request_hash
        row.status = "IN_PROGRESS"
        row.resource_type = None
        row.resource_id = None
        row.response_status = None
        row.response_body = None
        row.created_at = created_at
        row.expires_at = expires_at
        await self._session.flush()

    async def delete(self, row: IdempotencyKey) -> None:
        """Release a key whose request ended without a replayable answer (a failure is not stored)."""
        await self._session.delete(row)
        await self._session.flush()

    async def set_resource(self, row: IdempotencyKey, *, resource_type: str, resource_id: uuid.UUID) -> None:
        """Say what this IN_PROGRESS key is working on (E6: the provisioning job)."""
        row.resource_type = resource_type
        row.resource_id = resource_id
        await self._session.flush()

    async def complete(
        self,
        row: IdempotencyKey,
        *,
        response_status: int,
        response_body: dict[str, Any] | None,
        resource_type: str | None,
        resource_id: uuid.UUID | None,
    ) -> None:
        row.status = "COMPLETED"
        row.response_status = response_status
        row.response_body = response_body
        row.resource_type = resource_type
        row.resource_id = resource_id
        await self._session.flush()
