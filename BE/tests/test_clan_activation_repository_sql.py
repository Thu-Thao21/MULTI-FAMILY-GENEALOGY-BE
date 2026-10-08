"""The real SQL and field writes of the E7 repository methods, compiled without a database: the subscription
lock, the two activation writes and the latest-job read. The same methods run on PostgreSQL in the
integration tests."""

from __future__ import annotations

import inspect
import re
import uuid
from datetime import datetime, timedelta, timezone

from app.models.family.entities import Clan, ClanSubscription
from app.models.family.provisioning_repository import ProvisioningRepository
from app.models.family.repository import FamilyRepository
from tests.test_public_repository_sql import RecordingSession, compiled

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
CLAN = uuid.uuid4()


def test_the_subscriptions_of_a_clan_are_locked_for_no_key_update_in_a_fixed_order():
    import asyncio

    session = RecordingSession()
    asyncio.run(FamilyRepository(session).lock_subscriptions(CLAN))
    sql, params = compiled(session)
    assert sql.endswith("FOR NO KEY UPDATE") and "FOR UPDATE" not in sql.replace("FOR NO KEY UPDATE", "")
    assert "clan_subscriptions.clan_id = " in sql.split("WHERE", 1)[1] and CLAN in params.values()
    assert "ORDER BY clan_subscriptions.subscription_id" in sql  # a fixed order: two lockers never cross
    assert "JOIN" not in sql and not re.search(r"\busers\b", sql)
    assert session.statements[0].get_execution_options().get("populate_existing") is True


def test_the_clan_is_activated_by_writing_the_row_it_was_given_and_only_flushing():
    import asyncio

    session = RecordingSession()
    clan = Clan(clan_id=CLAN, clan_code="C", name="N", status="PENDING", created_at=NOW - timedelta(days=3), updated_at=NOW - timedelta(days=3))
    asyncio.run(FamilyRepository(session).activate_clan(clan, now=NOW))
    assert (clan.status, clan.activated_at, clan.updated_at, clan.suspended_at) == ("ACTIVE", NOW, NOW, None)
    assert session.flushes == 1 and session.statements == []  # the ORM writes the change at the flush


def test_the_subscription_is_activated_with_the_dates_it_was_given_and_only_flushed():
    import asyncio

    session = RecordingSession()
    sub = ClanSubscription(subscription_id=uuid.uuid4(), clan_id=CLAN, plan_id=uuid.uuid4(), status="PENDING",
                           starts_at=NOW - timedelta(days=3), ends_at=NOW + timedelta(days=360), auto_renew=False)
    ends = NOW + timedelta(days=365)
    asyncio.run(FamilyRepository(session).activate_subscription(sub, starts_at=NOW, ends_at=ends))
    assert (sub.status, sub.starts_at, sub.ends_at, sub.auto_renew) == ("ACTIVE", NOW, ends, False)
    assert session.flushes == 1 and session.statements == []


def test_the_newest_job_of_a_clan_is_read_without_a_lock():
    import asyncio

    session = RecordingSession()
    asyncio.run(ProvisioningRepository(session).latest_for_clan(CLAN))
    sql, params = compiled(session)
    assert "provisioning_jobs.clan_id = " in sql and CLAN in params.values()
    assert "ORDER BY provisioning_jobs.created_at DESC, provisioning_jobs.job_id" in sql and "LIMIT" in sql
    assert "FOR " not in sql


def test_the_e7_repository_methods_never_commit():
    for cls, names in ((FamilyRepository, ("lock_subscriptions", "activate_clan", "activate_subscription")),
                       (ProvisioningRepository, ("latest_for_clan",))):
        for name in names:
            assert not re.search(r"\.(commit|rollback)\(", inspect.getsource(getattr(cls, name))), name


def test_the_activation_use_case_locks_the_clan_before_the_subscriptions_and_never_locks_users():
    """The order is read from the source: lock_clan, then lock_subscriptions, and no users lock."""
    from app.controllers.family_management import clan_admin_use_cases

    source = inspect.getsource(clan_admin_use_cases.activate_clan)
    assert source.index("family.lock_clan(") < source.index("family.lock_subscriptions(")
    assert "get_user_for_update" not in source and "lock_active" not in source
