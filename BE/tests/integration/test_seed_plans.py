"""The DEV service plans of scripts/seed_dev.py on the real PostgreSQL branch (Mốc E, E3).

Rolled back per test. The seeded DEV-TRIAL, DEV-STANDARD and DEV-LEGACY plans of the dev branch
are NEVER deleted or modified here:
  * every cleanup test passes its own prefix (DEV-ITEST-<tag>-) so it can only reach plans the
    test created itself;
  * the one test that runs the default seed only checks that existing DEV-* rows are untouched.
The default cleanup (prefix DEV-) is never called by a test.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.models.family.entities import ClanSubscription, PlanFeatureLimit, SubscriptionPlan
from tests.integration.factory import now

BE_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def seed_dev():
    spec = importlib.util.spec_from_file_location("seed_dev_plans_under_test", BE_DIR / "scripts" / "seed_dev.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tag() -> str:
    return uuid.uuid4().hex[:8]


def specs_for(prefix: str) -> list[dict]:
    return [
        dict(code=f"{prefix}ONE", name="Seed test one", status="ACTIVE", price="199000.00", billing_period_months=12,
             description="d", max_members=10, max_family_admins=2, storage_mb=512,
             features=[("MAX_PERSONS", True, 5000), ("TREE_VIEW_3D", False, None)]),
        dict(code=f"{prefix}TWO", name="Seed test two", status="INACTIVE", price="0.00", billing_period_months=1,
             description=None, features=[("DATA_EXPORT", True, None)]),
    ]


async def plan_row(session, code):
    return (await session.execute(select(SubscriptionPlan).where(SubscriptionPlan.code == code))).scalar_one_or_none()


async def features_of(session, plan_id):
    rows = await session.execute(select(PlanFeatureLimit).where(PlanFeatureLimit.plan_id == plan_id))
    return {f.feature_code: f for f in rows.scalars().all()}


async def count_features(session, plan_id) -> int:
    return (await session.execute(
        select(func.count()).select_from(PlanFeatureLimit).where(PlanFeatureLimit.plan_id == plan_id))).scalar_one()


# ------------------------------------------------------------------ seed_plans


async def test_the_seed_creates_the_plans_and_their_features_with_the_specified_values(session, seed_dev):
    prefix = f"DEV-ITEST-{tag()}-"
    made, had = await seed_dev.seed_plans(session, specs_for(prefix))
    assert dict(made) == {"subscription_plans": 2, "plan_feature_limits": 3} and dict(had) == {}
    one, two = await plan_row(session, f"{prefix}ONE"), await plan_row(session, f"{prefix}TWO")
    assert (one.status, one.price, one.billing_period_months) == ("ACTIVE", Decimal("199000.00"), 12)
    assert (one.max_members, one.max_family_admins, one.storage_mb, one.description) == (10, 2, 512, "d")
    assert (two.status, two.price, two.billing_period_months, two.max_members) == ("INACTIVE", Decimal("0.00"), 1, None)
    features = await features_of(session, one.plan_id)
    assert set(features) == {"MAX_PERSONS", "TREE_VIEW_3D"}
    assert features["MAX_PERSONS"].enabled is True and features["MAX_PERSONS"].limit_value == Decimal("5000")
    assert features["TREE_VIEW_3D"].enabled is False and features["TREE_VIEW_3D"].limit_value is None
    assert set(await features_of(session, two.plan_id)) == {"DATA_EXPORT"}


async def test_running_the_seed_again_creates_no_row_at_all(session, seed_dev):
    prefix = f"DEV-ITEST-{tag()}-"
    specs = specs_for(prefix)
    await seed_dev.seed_plans(session, specs)
    before = (await session.execute(text("SELECT count(*) FROM subscription_plans"))).scalar_one()
    features_before = (await session.execute(text("SELECT count(*) FROM plan_feature_limits"))).scalar_one()
    made, had = await seed_dev.seed_plans(session, specs)
    assert sum(made.values()) == 0
    assert dict(had) == {"subscription_plans": 2, "plan_feature_limits": 3}
    assert (await session.execute(text("SELECT count(*) FROM subscription_plans"))).scalar_one() == before
    assert (await session.execute(text("SELECT count(*) FROM plan_feature_limits"))).scalar_one() == features_before


async def test_the_seed_never_overwrites_what_exists(session, seed_dev):
    """A hand edit of a plan or of a feature survives a re-run."""
    prefix = f"DEV-ITEST-{tag()}-"
    specs = specs_for(prefix)
    await seed_dev.seed_plans(session, specs)
    one = await plan_row(session, f"{prefix}ONE")
    one.name, one.price, one.status, one.max_members = "Edited by hand", Decimal("1.23"), "RETIRED", 7
    features = await features_of(session, one.plan_id)
    features["MAX_PERSONS"].enabled, features["MAX_PERSONS"].limit_value = False, Decimal("42")
    await session.flush()

    made, _had = await seed_dev.seed_plans(session, specs)
    assert sum(made.values()) == 0
    await session.refresh(one)
    assert (one.name, one.price, one.status, one.max_members) == ("Edited by hand", Decimal("1.23"), "RETIRED", 7)
    kept = await features_of(session, one.plan_id)
    assert kept["MAX_PERSONS"].enabled is False and kept["MAX_PERSONS"].limit_value == Decimal("42")


async def test_a_missing_feature_is_added_and_the_existing_ones_are_left_alone(session, seed_dev):
    prefix = f"DEV-ITEST-{tag()}-"
    specs = specs_for(prefix)
    await seed_dev.seed_plans(session, specs)
    one = await plan_row(session, f"{prefix}ONE")
    await session.execute(text("DELETE FROM plan_feature_limits WHERE plan_id = :p AND feature_code = 'TREE_VIEW_3D'"),
                          {"p": one.plan_id})
    made, had = await seed_dev.seed_plans(session, specs)
    assert dict(made) == {"plan_feature_limits": 1}
    assert had["subscription_plans"] == 2 and had["plan_feature_limits"] == 2
    assert set(await features_of(session, one.plan_id)) == {"MAX_PERSONS", "TREE_VIEW_3D"}


async def test_the_default_seed_leaves_every_existing_dev_plan_exactly_as_it_is(session, seed_dev):
    """Get-or-create on the real DEV-* plans: whatever is there already is not touched."""
    def snapshot():
        return text(
            "SELECT p.code, p.name, p.status, p.price, p.billing_period_months, p.max_members, "
            "p.max_family_admins, p.storage_mb, p.description, "
            "(SELECT string_agg(f.feature_code || ':' || f.enabled::text || ':' || coalesce(f.limit_value::text, '-'), ',' "
            "ORDER BY f.feature_code) FROM plan_feature_limits f WHERE f.plan_id = p.plan_id) AS features "
            "FROM subscription_plans p WHERE p.code LIKE 'DEV-%' ORDER BY p.code")

    before = {r[0]: tuple(r) for r in (await session.execute(snapshot())).all()}
    await seed_dev.seed_plans(session)
    after = {r[0]: tuple(r) for r in (await session.execute(snapshot())).all()}
    for code, row in before.items():
        assert after[code] == row, f"{code} was modified by the seed"
    assert {"DEV-TRIAL", "DEV-STANDARD", "DEV-LEGACY"} <= set(after)  # present now (created if they were missing)


async def test_the_full_seed_includes_the_plans_and_is_idempotent(session, seed_dev):
    await seed_dev.seed(session)
    again = await seed_dev.seed(session)
    assert sum(again.values()) == 0  # nothing new on the second run: users, clans and plans alike
    for code in ("DEV-TRIAL", "DEV-STANDARD", "DEV-LEGACY"):
        assert await plan_row(session, code) is not None


# ------------------------------------------------------------------ cleanup_plans


async def test_cleanup_deletes_unreferenced_prefixed_plans_and_keeps_referenced_or_foreign_ones(session, world, seed_dev):
    t = tag()
    prefix = f"DEV-ITEST-{t}-"
    free, by_registration, by_subscription = (
        await world.plan(), await world.plan(), await world.plan())
    for plan, name in ((free, "FREE"), (by_registration, "REG"), (by_subscription, "SUB")):
        plan.code = f"{prefix}{name}"
        session.add(PlanFeatureLimit(plan_feature_id=uuid.uuid4(), plan_id=plan.plan_id, feature_code="F",
                                     enabled=True, feature_metadata={}))
    foreign = await world.plan()
    foreign.code = f"ITEST-{t}-NOT-DEV"  # unreferenced, but not a DEV- plan: must survive
    await session.flush()
    await world.registration(by_registration)
    clan = await world.clan()
    session.add(ClanSubscription(subscription_id=uuid.uuid4(), clan_id=clan.clan_id, plan_id=by_subscription.plan_id,
                                 starts_at=now(), ends_at=now() + timedelta(days=30), status="ACTIVE", auto_renew=False))
    await session.flush()

    deleted, kept = await seed_dev.cleanup_plans(session, prefix)
    assert (deleted, kept) == (1, 2)
    assert await plan_row(session, f"{prefix}FREE") is None
    assert await count_features(session, free.plan_id) == 0  # its features went with it
    assert await plan_row(session, f"{prefix}REG") is not None and await count_features(session, by_registration.plan_id) == 1
    assert await plan_row(session, f"{prefix}SUB") is not None and await count_features(session, by_subscription.plan_id) == 1
    assert await plan_row(session, f"ITEST-{t}-NOT-DEV") is not None


async def test_cleanup_with_nothing_to_delete_does_nothing(session, seed_dev):
    assert await seed_dev.cleanup_plans(session, f"DEV-ITEST-{tag()}-") == (0, 0)


async def test_cleanup_matches_the_prefix_literally_not_as_a_like_pattern(session, world, seed_dev):
    """An underscore in a prefix must not act as the LIKE wildcard that matches any character."""
    t = tag()
    literal, lookalike = await world.plan(), await world.plan()
    literal.code = f"DEV-ITEST{t}_B"
    lookalike.code = f"DEV-ITEST{t}-A"  # '_' as a wildcard would match this '-'
    await session.flush()
    deleted, kept = await seed_dev.cleanup_plans(session, f"DEV-ITEST{t}_")
    assert (deleted, kept) == (1, 0)
    assert await plan_row(session, f"DEV-ITEST{t}_B") is None
    assert await plan_row(session, f"DEV-ITEST{t}-A") is not None


async def test_cleanup_cannot_reach_a_plan_that_does_not_start_with_its_prefix(session, world, seed_dev):
    t = tag()
    other = await world.plan()
    other.code = f"DEV-OTHER-{t}"
    await session.flush()
    assert await seed_dev.cleanup_plans(session, f"DEV-ITEST-{t}-") == (0, 0)
    assert await plan_row(session, f"DEV-OTHER-{t}") is not None


async def test_the_default_prefix_is_dev_and_nothing_else(seed_dev):
    assert seed_dev.PLAN_PREFIX == "DEV-"
    import inspect

    assert inspect.signature(seed_dev.cleanup_plans).parameters["prefix"].default == "DEV-"
