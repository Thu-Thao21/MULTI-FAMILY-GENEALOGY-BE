"""GET /service-plans (Mốc E, step E3): the public catalog, on fake repositories."""

from __future__ import annotations

import pytest

from tests.guest_harness import PREFIX, GuestWorld, code_of

PLAN_KEYS = {
    "plan_id", "code", "name", "description", "price", "billing_period_months",
    "max_members", "max_family_admins", "storage_mb", "features",
}
FEATURE_KEYS = {"feature_code", "enabled", "limit_value"}


@pytest.fixture
def w() -> GuestWorld:
    world = GuestWorld()
    world.family.plans.clear()  # the harness adds one plan for registrations; start empty here
    return world


def get(w, query: str = ""):
    return w.client.get(f"{PREFIX}/service-plans{query}")


def test_an_empty_catalog_is_an_empty_page(w):
    r = get(w)
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


def test_only_active_plans_are_listed_cheapest_first_then_by_code(w):
    w.family.add_plan("B-STANDARD", price="199000.00")
    w.family.add_plan("A-STANDARD", price="199000.00")
    w.family.add_plan("C-TRIAL", price="0.00")
    w.family.add_plan("D-OLD", price="1.00", status="INACTIVE")
    w.family.add_plan("E-GONE", price="2.00", status="RETIRED")
    body = get(w).json()
    assert [p["code"] for p in body["items"]] == ["C-TRIAL", "A-STANDARD", "B-STANDARD"]
    assert body["total"] == 3


def test_each_plan_shows_exactly_the_public_fields_and_the_price_as_a_decimal_string(w):
    w.family.add_plan(
        "STANDARD", price="199000.00", max_members=200, max_family_admins=5, storage_mb=2048,
        features=[("TREE_VIEW_3D", True, None), ("MAX_PERSONS", True, 5000), ("AI_ASSISTANT", False, None)],
    )
    [plan] = get(w).json()["items"]
    assert set(plan) == PLAN_KEYS
    assert plan["price"] == "199000.00" and isinstance(plan["price"], str)
    assert plan["billing_period_months"] == 12 and plan["max_members"] == 200
    assert plan["max_family_admins"] == 5 and plan["storage_mb"] == 2048
    features = {f["feature_code"]: f for f in plan["features"]}
    assert set(features) == {"TREE_VIEW_3D", "MAX_PERSONS", "AI_ASSISTANT"}
    assert all(set(f) == FEATURE_KEYS for f in plan["features"])
    assert features["MAX_PERSONS"]["limit_value"] == "5000" and features["TREE_VIEW_3D"]["limit_value"] is None
    assert features["AI_ASSISTANT"]["enabled"] is False  # a disabled feature is still shown, as disabled
    assert [f["feature_code"] for f in plan["features"]] == sorted(features)


def test_nothing_internal_is_exposed(w):
    w.family.add_plan("STANDARD", price="1.00", features=[("X", True, None)])
    text = get(w).text
    for hidden in ("metadata", "status", "created_at", "updated_at", "plan_feature_id"):
        assert hidden not in text, hidden


def test_features_belong_to_their_own_plan(w):
    a = w.family.add_plan("A", price="1.00", features=[("ONLY_A", True, None)])
    b = w.family.add_plan("B", price="2.00", features=[("ONLY_B", True, None)])
    by_code = {p["code"]: p for p in get(w).json()["items"]}
    assert [f["feature_code"] for f in by_code["A"]["features"]] == ["ONLY_A"]
    assert [f["feature_code"] for f in by_code["B"]["features"]] == ["ONLY_B"]
    assert a.plan_id != b.plan_id


def test_a_plan_without_features_has_an_empty_list(w):
    w.family.add_plan("BARE", price="0.00")
    assert get(w).json()["items"][0]["features"] == []


def test_paging_and_the_total(w):
    for i in range(5):
        w.family.add_plan(f"P{i}", price=f"{i}.00")
    first = get(w, "?page=1&page_size=2").json()
    second = get(w, "?page=2&page_size=2").json()
    last = get(w, "?page=3&page_size=2").json()
    beyond = get(w, "?page=9&page_size=2").json()
    assert [p["code"] for p in first["items"]] == ["P0", "P1"]
    assert [p["code"] for p in second["items"]] == ["P2", "P3"]
    assert [p["code"] for p in last["items"]] == ["P4"]
    assert beyond["items"] == []
    assert {first["total"], second["total"], last["total"], beyond["total"]} == {5}
    assert (second["page"], second["page_size"]) == (2, 2)


@pytest.mark.parametrize("query", ["?page=0", "?page=-1", "?page_size=0", "?page_size=101", "?page=x", "?page_size=1.5"])
def test_bad_paging_is_422(w, query):
    r = get(w, query)
    assert (r.status_code, code_of(r)) == (422, "VALIDATION_ERROR")


def test_the_largest_page_is_accepted(w):
    assert get(w, "?page_size=100").status_code == 200


def test_a_page_costs_three_queries_however_many_plans_it_holds(w):
    """One for the plans, one for the total, one for ALL their features: no query per plan."""
    for i in range(12):
        w.family.add_plan(f"P{i:02d}", price=f"{i}.00", features=[("A", True, None), ("B", True, 3)])
    w.family.calls.clear()
    assert len(get(w, "?page_size=12").json()["items"]) == 12
    assert w.family.calls == ["list_active_plans_page", "count_active_plans", "list_feature_limits_for_plans"]


def test_no_account_is_needed_a_bearer_header_is_ignored_and_nothing_is_written(w):
    w.family.add_plan("STANDARD", price="1.00")
    r = w.client.get(f"{PREFIX}/service-plans", headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 200 and len(r.json()["items"]) == 1
    assert w.db.commits == 0 and w.repo.audit == []


def test_the_catalog_is_not_rate_limited(w):
    w.family.add_plan("STANDARD", price="1.00")
    for _ in range(60):
        assert get(w).status_code == 200


def test_the_response_carries_the_request_id_header(w):
    assert get(w).headers["x-request-id"]
