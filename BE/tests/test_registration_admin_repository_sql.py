"""The real SQL of the registration administration methods (Mốc E, step E4), compiled without a
database. The HTTP tests use fake repositories, so only these tests see the statements the real
FamilyRepository sends: the row lock, the filters, the ordering, the paging, the LIKE escaping,
and the columns the list is allowed to select. The same methods run on PostgreSQL in the
integration tests."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.dialects import postgresql

from app.models.family.entities import BusinessRegistration
from app.models.family.repository import FamilyRepository
from tests.test_public_repository_sql import RecordingSession, compiled

FROM = datetime(2026, 10, 1, tzinfo=timezone.utc)
TO = datetime(2026, 10, 8, tzinfo=timezone.utc)
NO_FILTER = dict(status=None, q=None, created_from=None, created_to=None)


@pytest.fixture
def session() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def repo(session) -> FamilyRepository:
    return FamilyRepository(session)


def literal(session: RecordingSession, index: int = 0) -> str:
    stmt = session.statements[index]
    return " ".join(str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).split())


# ------------------------------------------------------------------ lock


async def test_the_review_lock_is_for_no_key_update_and_rereads_the_row(repo, session):
    await repo.lock_registration(uuid.uuid4())
    sql, _ = compiled(session)
    assert sql.endswith("FOR NO KEY UPDATE"), sql
    assert "FOR UPDATE" not in sql.replace("FOR NO KEY UPDATE", "")
    assert "FOR SHARE" not in sql and "KEY SHARE" not in sql
    assert session.statements[0].get_execution_options().get("populate_existing") is True
    assert "users" not in sql and "JOIN" not in sql  # one table: the users row is never locked
    assert "registration_id =" in sql.split("WHERE", 1)[1]


async def test_only_the_registration_row_is_locked_no_plan_join_under_the_lock(repo, session):
    await repo.lock_registration(uuid.uuid4())
    sql, _ = compiled(session)
    assert re.findall(r"FROM (\w+)", sql) == ["business_registrations"]


# ------------------------------------------------------------------ list


async def test_the_list_selects_only_the_columns_it_shows(repo, session):
    await repo.list_registrations_page(limit=20, offset=0, **NO_FILTER)
    select_part = compiled(session)[0].split(" FROM ", 1)[0]
    for shown in ("registration_id", "clan_name", "representative_name", "requested_plan_id", "requested_plan_code",
                  "status", "created_at", "reviewed_at"):
        assert shown in select_part, shown
    for hidden in ("representative_email", "representative_phone", "origin_place", "rejection_reason",
                   "reviewed_by", "tracking_code_hash", "updated_at"):
        assert hidden not in select_part, hidden


async def test_the_list_joins_the_plan_and_orders_newest_first_with_the_id_as_tie_breaker(repo, session):
    await repo.list_registrations_page(limit=20, offset=0, **NO_FILTER)
    sql, _ = compiled(session)
    assert "JOIN subscription_plans ON subscription_plans.plan_id = business_registrations.requested_plan_id" in sql
    assert "ORDER BY business_registrations.created_at DESC, business_registrations.registration_id DESC" in sql
    assert "WHERE" not in sql  # no filter, no WHERE


async def test_paging_is_a_limit_and_an_offset_in_the_query(repo, session):
    await repo.list_registrations_page(limit=25, offset=50, **NO_FILTER)
    sql, params = compiled(session)
    assert "LIMIT" in sql and "OFFSET" in sql
    assert sorted(v for v in params.values() if isinstance(v, int)) == [25, 50]


async def test_the_status_filter_is_an_equality_on_a_bound_value(repo, session):
    await repo.list_registrations_page(limit=20, offset=0, **{**NO_FILTER, "status": "PENDING"})
    sql, params = compiled(session)
    assert "business_registrations.status = " in sql.split("WHERE", 1)[1]
    assert "PENDING" in params.values() and "PENDING" not in sql


async def test_the_date_bounds_are_inclusive_below_and_exclusive_above(repo, session):
    await repo.list_registrations_page(limit=20, offset=0, **{**NO_FILTER, "created_from": FROM, "created_to": TO})
    where = compiled(session)[0].split("WHERE", 1)[1].split("ORDER BY", 1)[0]
    assert re.search(r"created_at >= ", where) and re.search(r"created_at < ", where)
    assert "<=" not in where and " > " not in where
    _, params = compiled(session)
    assert FROM in params.values() and TO in params.values()


async def test_the_search_is_a_case_insensitive_substring_on_exactly_three_columns(repo, session):
    await repo.list_registrations_page(limit=20, offset=0, **{**NO_FILTER, "q": "Nguyen"})
    sql, params = compiled(session)
    where = sql.split("WHERE", 1)[1].split("ORDER BY", 1)[0]
    assert where.count("ILIKE") == 3 and where.count(" OR ") == 2
    for column in ("clan_name", "representative_name", "representative_email"):
        assert f"business_registrations.{column} ILIKE" in where, column
    for other in ("representative_phone", "origin_place", "rejection_reason", "tracking_code_hash"):
        assert other not in where, other
    assert "%Nguyen%" in params.values() and "Nguyen" not in sql  # a bound pattern, never in the SQL text
    assert where.count("ESCAPE") == 3


@pytest.mark.parametrize("q, pattern", [
    ("50%", "%50\\%%"), ("a_b", "%a\\_b%"), ("back\\slash", "%back\\\\slash%"), ("%_\\", "%\\%\\_\\\\%"),
    ("plain", "%plain%"),
])
async def test_like_wildcards_and_backslash_in_the_search_are_escaped(repo, session, q, pattern):
    await repo.list_registrations_page(limit=20, offset=0, **{**NO_FILTER, "q": q})
    _, params = compiled(session)
    assert pattern in params.values(), (q, pattern, params)


async def test_a_search_with_an_injection_shape_stays_a_bound_value(repo, session):
    nasty = "x'; DROP TABLE business_registrations; --"
    await repo.list_registrations_page(limit=20, offset=0, **{**NO_FILTER, "q": nasty})
    sql, params = compiled(session)
    escaped = nasty.replace("_", "\\_")  # the underscore of the table name is escaped like any other
    assert "DROP" not in sql and "--" not in sql
    assert f"%{escaped}%" in params.values()


async def test_every_filter_together_is_one_where_joined_by_and(repo, session):
    await repo.list_registrations_page(limit=20, offset=0, status="PENDING", q="ho", created_from=FROM, created_to=TO)
    where = compiled(session)[0].split("WHERE", 1)[1].split("ORDER BY", 1)[0]
    assert where.count(" AND ") == 3 and "status" in where and "ILIKE" in where


# ------------------------------------------------------------------ count


async def test_the_count_uses_the_same_filters_and_has_no_paging_or_join(repo, session):
    filters = dict(status="APPROVED", q="clan", created_from=FROM, created_to=TO)
    await repo.list_registrations_page(limit=20, offset=0, **filters)
    assert await repo.count_registrations(**filters) == 0
    list_sql, list_params = compiled(session, 0)
    count_sql, count_params = compiled(session, 1)
    assert count_sql.startswith("SELECT count(*)")
    assert "LIMIT" not in count_sql and "OFFSET" not in count_sql and "ORDER BY" not in count_sql
    assert "JOIN" not in count_sql

    def where(sql: str) -> str:
        return sql.split("WHERE", 1)[1].split("ORDER BY", 1)[0].strip()

    assert where(list_sql) == where(count_sql)
    assert {v for v in list_params.values() if not isinstance(v, int) or isinstance(v, bool)} <= set(count_params.values())


async def test_the_count_has_no_where_without_filters(repo, session):
    await repo.count_registrations(**NO_FILTER)
    assert "WHERE" not in compiled(session)[0]


# ------------------------------------------------------------------ detail and write


async def test_the_detail_reads_one_registration_with_its_plan_code(repo, session):
    await repo.get_registration_with_plan(uuid.uuid4())
    sql, _ = compiled(session)
    assert "subscription_plans.code" in sql and "JOIN subscription_plans" in sql
    assert "FOR " not in sql  # a read never takes a lock (a review is not blocked by a reader)
    assert "business_registrations.registration_id = " in sql.split("WHERE", 1)[1]


async def test_applying_a_review_sets_the_fields_and_only_flushes(repo, session):
    reg = BusinessRegistration(registration_id=uuid.uuid4(), status="PENDING")
    reviewer, now = uuid.uuid4(), datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
    await repo.apply_registration_review(reg, status="REJECTED", reviewed_by=reviewer, rejection_reason="why", now=now)
    assert (reg.status, reg.reviewed_by, reg.reviewed_at, reg.rejection_reason, reg.updated_at) == (
        "REJECTED", reviewer, now, "why", now)
    assert session.flushes == 1 and session.statements == []  # no commit exists on this session double


async def test_an_approval_clears_the_rejection_reason_column(repo, session):
    reg = BusinessRegistration(registration_id=uuid.uuid4(), status="PENDING", rejection_reason="stale")
    await repo.apply_registration_review(
        reg, status="APPROVED", reviewed_by=uuid.uuid4(), rejection_reason=None, now=datetime.now(timezone.utc))
    assert reg.rejection_reason is None


def test_the_repository_methods_never_commit():
    import inspect

    for name in ("list_registrations_page", "count_registrations", "get_registration_with_plan",
                 "lock_registration", "apply_registration_review"):
        source = inspect.getsource(getattr(FamilyRepository, name))
        assert "commit" not in source and "rollback" not in source, name
