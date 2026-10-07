"""The real SQL of the public repository methods (Mốc E, step E3), compiled without a database.

The HTTP tests use fake repositories, so they cannot see the SQL. These tests capture the
statements the real FamilyRepository sends and check what matters: the ACTIVE filter, the
ordering, paging, one query for all features, the lower() comparison that mirrors the unique
index, and the rows written. The same methods are exercised on PostgreSQL by the integration
tests that come after this step.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.dialects import postgresql

from app.models.family.entities import BusinessRegistration, RegistrationStatusHistory
from app.models.family.repository import FamilyRepository

NOW = datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)


class _Rows:
    def all(self):
        return []


class _Result:
    def scalars(self):
        return _Rows()

    def scalar_one(self):
        return 0

    def scalar_one_or_none(self):
        return None

    def first(self):
        return None

    def all(self):  # row results (E4: the SA list selects columns, not entities)
        return []


class _Nested:
    """`async with session.begin_nested()`: records that a SAVEPOINT was opened and how it ended."""

    def __init__(self, session: "RecordingSession") -> None:
        self._session = session

    async def __aenter__(self):
        self._session.savepoints.append("opened")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._session.savepoints.append("rolled back" if exc_type else "released")
        return False


class RecordingSession:
    def __init__(self) -> None:
        self.statements: list = []
        self.added: list = []
        self.flushes = 0
        self.savepoints: list[str] = []
        self.flush_error: Exception | None = None

    def begin_nested(self) -> _Nested:
        return _Nested(self)

    async def execute(self, stmt, *args, **kwargs):
        self.statements.append(stmt)
        return _Result()

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1
        if self.flush_error is not None:
            raise self.flush_error


def compiled(session: RecordingSession, index: int = 0):
    c = session.statements[index].compile(dialect=postgresql.dialect())
    sql = re.sub(r"::[A-Z_\[\]]+", "", " ".join(str(c).split()))  # the driver adds type casts to binds
    return sql, dict(c.params)


@pytest.fixture
def session() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def repo(session) -> FamilyRepository:
    return FamilyRepository(session)


async def test_the_page_of_plans_is_active_only_cheapest_first_and_paged(repo, session):
    await repo.list_active_plans_page(limit=7, offset=14)
    sql, params = compiled(session)
    assert "FROM subscription_plans" in sql and "subscription_plans.status = %(status_1)s" in sql
    assert params["status_1"] == "ACTIVE"
    assert "ORDER BY subscription_plans.price ASC, subscription_plans.code ASC" in sql
    assert "LIMIT %(param_1)s OFFSET %(param_2)s" in sql
    assert sorted(v for v in params.values() if isinstance(v, int)) == [7, 14]


async def test_the_total_counts_the_same_plans_the_page_lists(repo, session):
    await repo.count_active_plans()
    sql, params = compiled(session)
    assert "count(*)" in sql.lower() and "FROM subscription_plans" in sql
    assert "subscription_plans.status = %(status_1)s" in sql and params["status_1"] == "ACTIVE"


async def test_the_features_of_a_whole_page_come_from_one_query(repo, session):
    ids = [uuid.uuid4() for _ in range(5)]
    await repo.list_feature_limits_for_plans(ids)
    assert len(session.statements) == 1
    sql, params = compiled(session)
    assert "FROM plan_feature_limits" in sql and "plan_feature_limits.plan_id IN" in sql
    assert "ORDER BY plan_feature_limits.plan_id, plan_feature_limits.feature_code" in sql
    assert set(next(v for v in params.values() if isinstance(v, list))) == set(ids)


async def test_no_plans_means_no_query_for_features(repo, session):
    assert await repo.list_feature_limits_for_plans([]) == []
    assert session.statements == []


async def test_the_duplicate_check_compares_with_lower_on_both_sides_like_the_unique_index(repo, session):
    assert await repo.exists_pending_registration(email="Ann@Example.TEST", clan_name="Ho Nguyen") is False
    sql, params = compiled(session)
    assert "FROM business_registrations" in sql
    assert "lower(business_registrations.representative_email) = lower(%(lower_1)s)" in sql
    assert "lower(business_registrations.clan_name) = lower(%(lower_2)s)" in sql
    assert "business_registrations.status = %(status_1)s" in sql and params["status_1"] == "PENDING"
    assert "LIMIT" in sql
    assert {params["lower_1"], params["lower_2"]} == {"Ann@Example.TEST", "Ho Nguyen"}  # lower() is the database's job


async def test_a_registration_is_added_pending_with_the_hash_and_flushed(repo, session):
    rid, plan = uuid.uuid4(), uuid.uuid4()
    row = await repo.create_registration(
        registration_id=rid, requested_plan_id=plan, representative_name="N", representative_email="E@X.co",
        representative_phone=None, clan_name="C", origin_place=None, tracking_code_hash="h" * 64, now=NOW,
    )
    assert session.added == [row] and session.flushes == 1
    assert isinstance(row, BusinessRegistration)
    assert (row.registration_id, row.requested_plan_id, row.status) == (rid, plan, "PENDING")
    assert row.tracking_code_hash == "h" * 64 and row.representative_email == "E@X.co"
    assert row.created_at == NOW and row.updated_at == NOW


async def test_the_first_status_history_row_has_no_previous_status_and_no_actor(repo, session):
    rid = uuid.uuid4()
    row = await repo.add_registration_status_history(
        registration_id=rid, from_status=None, to_status="PENDING", changed_by=None, reason=None, now=NOW
    )
    assert session.added == [row] and session.flushes == 1
    assert isinstance(row, RegistrationStatusHistory)
    assert (row.registration_id, row.from_status, row.to_status) == (rid, None, "PENDING")
    assert row.changed_by is None and row.reason is None and row.changed_at == NOW


async def test_a_registration_is_looked_up_by_the_hash_only(repo, session):
    await repo.get_registration_by_tracking_hash("a" * 64)
    sql, params = compiled(session)
    assert "business_registrations.tracking_code_hash = %(tracking_code_hash_1)s" in sql
    assert params["tracking_code_hash_1"] == "a" * 64
