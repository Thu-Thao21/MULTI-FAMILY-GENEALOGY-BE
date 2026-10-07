"""The DEV service plans of scripts/seed_dev.py (Mốc E, step E3): their definitions and the
refusal to run without ALLOW_DEV_SEED. No database. The behaviour against PostgreSQL (idempotent,
never overwrites, cleanup keeps referenced plans) is in tests/integration/test_seed_plans.py."""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

BE_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def seed_dev():
    spec = importlib.util.spec_from_file_location("seed_dev_definition_test", BE_DIR / "scripts" / "seed_dev.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_there_are_exactly_three_dev_plans_with_the_planned_codes(seed_dev):
    assert [p["code"] for p in seed_dev.PLANS] == ["DEV-TRIAL", "DEV-STANDARD", "DEV-LEGACY"]
    assert seed_dev.PLAN_PREFIX == "DEV-"


def test_every_plan_code_carries_the_dev_prefix_so_cleanup_can_never_reach_a_real_plan(seed_dev):
    assert all(p["code"].startswith(seed_dev.PLAN_PREFIX) for p in seed_dev.PLANS)


def test_two_plans_are_active_and_the_legacy_plan_is_inactive(seed_dev):
    status = {p["code"]: p["status"] for p in seed_dev.PLANS}
    assert status == {"DEV-TRIAL": "ACTIVE", "DEV-STANDARD": "ACTIVE", "DEV-LEGACY": "INACTIVE"}


def test_the_prices_and_periods_respect_the_database_checks(seed_dev):
    prices = {p["code"]: Decimal(p["price"]) for p in seed_dev.PLANS}
    assert prices == {"DEV-TRIAL": Decimal("0.00"), "DEV-STANDARD": Decimal("199000.00"), "DEV-LEGACY": Decimal("99000.00")}
    for plan in seed_dev.PLANS:
        assert Decimal(plan["price"]) >= 0  # subscription_plans_price_check
        assert plan["billing_period_months"] > 0  # subscription_plans_billing_period_months_check
        assert plan["status"] in {"ACTIVE", "INACTIVE", "RETIRED"}  # subscription_plans_status_check


def test_the_values_fit_their_columns(seed_dev):
    for plan in seed_dev.PLANS:
        assert len(plan["code"]) <= 50 and len(plan["name"]) <= 150
        for feature_code, enabled, limit in plan["features"]:
            assert len(feature_code) <= 100 and isinstance(enabled, bool)
            assert limit is None or Decimal(str(limit)) >= 0


def test_every_plan_has_features_and_no_feature_repeats_inside_a_plan(seed_dev):
    """plan_feature_limits is unique on (plan_id, feature_code): a repeat would fail the seed."""
    for plan in seed_dev.PLANS:
        codes = [f[0] for f in plan["features"]]
        assert codes and len(codes) == len(set(codes)), plan["code"]
    assert sum(len(p["features"]) for p in seed_dev.PLANS) == 6


def test_the_plans_are_dev_data_and_say_so(seed_dev):
    for plan in seed_dev.PLANS:
        assert "không phải gói thật" in plan["description"] or "ngừng bán" in plan["description"]


def test_the_seed_refuses_to_run_without_the_flag_for_every_mode(seed_dev, monkeypatch, capsys):
    monkeypatch.delenv(seed_dev.ENV_FLAG, raising=False)
    for argv in (["--plans-only"], ["--plans-only", "--cleanup"], [], ["--cleanup"]):
        assert seed_dev.main(argv) == 2, argv
    assert "ALLOW_DEV_SEED=1" in capsys.readouterr().out
