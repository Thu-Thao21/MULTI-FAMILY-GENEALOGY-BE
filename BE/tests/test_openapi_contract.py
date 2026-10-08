"""The OpenAPI document vs docs/api_contract.md for every implemented endpoint (Mốc G).

Two jobs:
  1. EXPECTED pins the implemented surface: paths, methods, success status, schema names,
     parameters and, per error status, the exact set of documented error codes. Adding,
     removing or changing a route (or its `responses=`) fails here until this table and
     the contract are updated together.
  2. The contract file is parsed and cross-checked: each implemented endpoint has its
     section, the same success status, and every status/code the contract lists for it is
     declared in OpenAPI (the only exceptions are in CONTRACT_NOT_IMPLEMENTED).

The contract text itself is never modified by these tests.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.main import create_app  # noqa: F401  (import check)
from app.main import app

CONTRACT = Path(__file__).resolve().parents[1] / "docs" / "api_contract.md"
PREFIX = "/api/v1"

DB = {"DATABASE_UNAVAILABLE"}
BOOM = {"INTERNAL_ERROR"}
AUTHED_401 = {"UNAUTHENTICATED", "SESSION_INVALID"}
AUTHED_403 = {"ACCOUNT_BLOCKED", "TEMPORARY_PASSWORD_EXPIRED"}
AUTHED_403_FULL = AUTHED_403 | {"PASSWORD_CHANGE_REQUIRED", "FORBIDDEN"}
V422 = {"VALIDATION_ERROR"}

# (method, contract path) -> expectations. Contract path is without /api/v1.
EXPECTED: dict[tuple[str, str], dict] = {
    ("post", "/auth/session"): dict(
        success=201, request="SessionCreateRequest", response="SessionCreateResponse", params=set(),
        errors={401: {"INVALID_ID_TOKEN"}, 403: AUTHED_403,
                422: V422, 500: BOOM, 503: DB | {"PROVIDER_UNAVAILABLE"}},
    ),
    ("get", "/auth/me"): dict(
        success=200, request=None, response="MeResponse", params=set(),
        errors={401: AUTHED_401, 403: AUTHED_403, 500: BOOM, 503: DB},
    ),
    ("post", "/auth/logout"): dict(
        success=204, request=None, response=None, params=set(),
        errors={401: AUTHED_401, 403: AUTHED_403, 500: BOOM, 503: DB},
    ),
    ("post", "/auth/change-password"): dict(
        success=204, request="ChangePasswordRequest", response=None, params=set(),
        errors={401: AUTHED_401 | {"RECENT_LOGIN_REQUIRED"}, 403: AUTHED_403, 422: V422,
                500: BOOM, 503: DB | {"PROVIDER_UNAVAILABLE"}},
    ),
    ("get", "/admin/users"): dict(
        success=200, request=None, response="Page_AdminUserSummary_",
        params={"page", "page_size", "status", "q"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 422: V422, 500: BOOM, 503: DB},
    ),
    ("get", "/admin/users/{user_id}"): dict(
        success=200, request=None, response="AdminUserDetail", params={"user_id"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 404: {"NOT_FOUND"}, 422: V422, 500: BOOM, 503: DB},
    ),
    ("patch", "/admin/users/{user_id}/status"): dict(
        success=200, request="UserStatusUpdateRequest", response="UserStatusUpdateResponse",
        params={"user_id"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 404: {"NOT_FOUND"}, 409: {"STATE_CONFLICT"},
                422: V422, 500: BOOM, 503: DB},
    ),
    ("get", "/clans/{clan_id}/users"): dict(
        success=200, request=None, response="Page_ClanUserItem_",
        params={"clan_id", "page", "page_size", "membership_status"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 404: {"NOT_FOUND"}, 422: V422, 500: BOOM, 503: DB},
    ),
    ("post", "/clans/{clan_id}/admins"): dict(
        success=201, request="FamilyAdminAssignRequest", response="FamilyAdminAssignResponse",
        params={"clan_id"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 404: {"NOT_FOUND"}, 409: {"STATE_CONFLICT"},
                422: V422, 500: BOOM, 503: DB},
    ),
    ("delete", "/clans/{clan_id}/admins/{user_id}"): dict(
        success=204, request=None, response=None, params={"clan_id", "user_id"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 404: {"NOT_FOUND"}, 422: V422,
                500: BOOM, 503: DB},
    ),
    # Mốc E, step E3: public (Guest) endpoints. No authentication, so no 401 and no 403.
    ("get", "/service-plans"): dict(
        success=200, request=None, response="Page_ServicePlanResponse_", params={"page", "page_size"},
        errors={422: V422, 500: BOOM, 503: DB},
    ),
    ("post", "/business-registrations"): dict(
        success=201, request="BusinessRegistrationCreateRequest",
        response="BusinessRegistrationCreateResponse", params=set(),
        errors={409: {"DUPLICATE_RESOURCE"}, 422: V422, 429: {"RATE_LIMITED"}, 500: BOOM, 503: DB},
    ),
    ("post", "/business-registrations/track"): dict(
        success=200, request="BusinessRegistrationTrackRequest",
        response="BusinessRegistrationTrackResponse", params=set(),
        errors={404: {"NOT_FOUND"}, 422: V422, 429: {"RATE_LIMITED"}, 500: BOOM, 503: DB},
    ),
    # Mốc E, step E4: System Admin administration of registrations (authentication required).
    ("get", "/admin/business-registrations"): dict(
        success=200, request=None, response="Page_BusinessRegistrationSummary_",
        params={"page", "page_size", "status", "q", "created_from", "created_to"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 422: V422, 500: BOOM, 503: DB},
    ),
    ("get", "/admin/business-registrations/{registration_id}"): dict(
        success=200, request=None, response="BusinessRegistrationDetail", params={"registration_id"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 404: {"NOT_FOUND"}, 422: V422, 500: BOOM, 503: DB},
    ),
    ("post", "/admin/business-registrations/{registration_id}/review"): dict(
        success=200, request="RegistrationReviewRequest", response="RegistrationReviewResponse",
        params={"registration_id"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 404: {"NOT_FOUND"}, 409: {"STATE_CONFLICT"},
                422: V422, 500: BOOM, 503: DB},
    ),
    # Mốc E, step E5: create the Business of an APPROVED registration (Idempotency-Key required).
    ("post", "/admin/business-registrations/{registration_id}/business"): dict(
        success=201, request="BusinessCreateRequest", response="BusinessCreateResponse",
        params={"registration_id", "Idempotency-Key"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 404: {"NOT_FOUND"},
                409: {"STATE_CONFLICT", "DUPLICATE_RESOURCE", "IDEMPOTENCY_KEY_CONFLICT"},
                422: V422, 500: BOOM, 503: DB},
    ),
    # Mốc E, step E6a: create the Owner of a clan through Firebase, and read a provisioning job.
    ("post", "/admin/clans/{clan_id}/owner"): dict(
        success=201, request="OwnerProvisionRequest", response="OwnerProvisionResponse",
        params={"clan_id", "Idempotency-Key"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 404: {"NOT_FOUND"},
                409: {"STATE_CONFLICT", "DUPLICATE_RESOURCE", "IDEMPOTENCY_KEY_CONFLICT"},
                422: V422, 500: BOOM, 503: DB | {"PROVIDER_UNAVAILABLE"}},
    ),
    ("get", "/admin/provisioning-jobs/{job_id}"): dict(
        success=200, request=None, response="ProvisioningJobResponse", params={"job_id"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 404: {"NOT_FOUND"}, 422: V422, 500: BOOM, 503: DB},
    ),
    # Mốc E, step E6b: list, retry and abandon a job, and reissue the Owner's temporary password.
    ("get", "/admin/provisioning-jobs"): dict(
        success=200, request=None, response="Page_ProvisioningJobResponse_",
        params={"page", "page_size", "clan_id", "status"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 422: V422, 500: BOOM, 503: DB},
    ),
    ("post", "/admin/provisioning-jobs/{job_id}/retry"): dict(
        success=200, request=None, response="OwnerProvisionResponse", params={"job_id"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 404: {"NOT_FOUND"},
                409: {"STATE_CONFLICT", "DUPLICATE_RESOURCE"}, 422: V422, 500: BOOM,
                503: DB | {"PROVIDER_UNAVAILABLE"}},
    ),
    ("post", "/admin/provisioning-jobs/{job_id}/abandon"): dict(
        success=200, request=None, response="ProvisioningJobResponse", params={"job_id"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 404: {"NOT_FOUND"}, 409: {"STATE_CONFLICT"},
                422: V422, 500: BOOM, 503: DB},
    ),
    ("post", "/admin/clans/{clan_id}/owner/temporary-password"): dict(
        success=200, request=None, response="OwnerPasswordResetResponse", params={"clan_id"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 404: {"NOT_FOUND"}, 409: {"STATE_CONFLICT"},
                422: V422, 500: BOOM, 503: DB | {"PROVIDER_UNAVAILABLE"}},
    ),
    ("put", "/clans/{clan_id}/admins/{user_id}/permissions"): dict(
        success=200, request="FamilyAdminPermissionsUpdateRequest",
        response="FamilyAdminPermissionsResponse", params={"clan_id", "user_id"},
        errors={401: AUTHED_401, 403: AUTHED_403_FULL, 404: {"NOT_FOUND"}, 409: {"STATE_CONFLICT"},
                422: V422, 500: BOOM, 503: DB},
    ),
}

# Status/code pairs the contract lists that the code does NOT implement yet (known issues).
CONTRACT_NOT_IMPLEMENTED: dict[tuple[str, str], set[str]] = {
    ("post", "/auth/session"): {"429"},  # KI-06: no rate limiter yet
}

OUTSIDE_CONTRACT = {"/api/health", "/api/health/ready"}


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def ref_name(schema: dict | None) -> str | None:
    if not schema:
        return None
    ref = schema.get("$ref")
    if ref is None:  # an OPTIONAL body is anyOf [model, null]
        options = [o for o in schema.get("anyOf", []) if o.get("type") != "null"]
        if len(options) == 1:
            ref = options[0].get("$ref")
    return ref.split("/")[-1] if ref else None


def declared_errors(operation: dict) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for status, response in operation["responses"].items():
        if not status.isdigit() or int(status) < 400:
            continue
        description = response["description"]
        assert description.startswith("Error codes: "), (status, description)
        out[int(status)] = {c.strip() for c in description.removeprefix("Error codes: ").split(",")}
    return out


# ----- 1. the implemented surface is exactly EXPECTED -----


def test_the_set_of_routes_is_exactly_the_expected_one(spec):
    actual = {
        (method, path.removeprefix(PREFIX))
        for path, ops in spec["paths"].items()
        if path not in OUTSIDE_CONTRACT
        for method in ops
    }
    assert actual == set(EXPECTED)
    assert set(spec["paths"]) - {PREFIX + p for _m, p in EXPECTED} == OUTSIDE_CONTRACT


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_success_status_schemas_and_parameters(spec, key):
    method, path = key
    want = EXPECTED[key]
    op = spec["paths"][PREFIX + path][method]
    successes = [s for s in op["responses"] if s.isdigit() and int(s) < 300]
    assert successes == [str(want["success"])]
    ok = op["responses"][successes[0]]
    assert ref_name(ok.get("content", {}).get("application/json", {}).get("schema")) == want["response"]
    body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
    assert ref_name(body) == want["request"]
    assert {p["name"] for p in op.get("parameters", [])} == want["params"]


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_error_responses_use_the_real_envelope_and_exact_codes(spec, key):
    method, path = key
    op = spec["paths"][PREFIX + path][method]
    assert declared_errors(op) == EXPECTED[key]["errors"]
    for status, response in op["responses"].items():
        if status.isdigit() and int(status) >= 400:
            schema = response["content"]["application/json"]["schema"]
            assert ref_name(schema) == "ErrorResponse", (key, status)


def test_fastapis_default_validation_schema_is_not_used(spec):
    """The default 422 body (HTTPValidationError) is not what the app returns."""
    assert "HTTPValidationError" not in spec["components"]["schemas"]
    assert "ValidationError" not in spec["components"]["schemas"]
    assert "ErrorResponse" in spec["components"]["schemas"]
    for ops in spec["paths"].values():
        for op in ops.values():
            assert "HTTPValidationError" not in str(op["responses"])


def test_every_declared_code_is_a_real_error_code(spec):
    from app.schemas.errors import ERROR_HTTP_STATUS, ErrorCode

    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            for status, codes in declared_errors(op).items():
                for code in codes:
                    assert ERROR_HTTP_STATUS[ErrorCode(code)] == status, (method, path, code)


def test_bearer_scheme_is_declared(spec):
    assert "HTTPBearer" in spec["components"]["securitySchemes"]


# ----- 2. cross-check against docs/api_contract.md -----


def parse_contract() -> dict[tuple[str, str], dict]:
    text = CONTRACT.read_text(encoding="utf-8")
    sections: dict[tuple[str, str], dict] = {}
    for match in re.finditer(r"^### (GET|POST|PUT|PATCH|DELETE) (/\S+)\n(.*?)(?=^#{2,3} |\Z)", text, re.S | re.M):
        method, path, body = match.group(1).lower(), match.group(2), match.group(3)
        success = re.search(r"\*\*Thành công:\*\*\s*`(\d{3})`", body)
        errors = re.search(r"\*\*Lỗi:\*\*(.*)", body)
        sections[(method, path)] = dict(
            success=int(success.group(1)) if success else None,
            errors=errors.group(1) if errors else "",
        )
    return sections


def test_every_implemented_endpoint_has_a_contract_section_with_the_same_success_status():
    contract = parse_contract()
    for key, want in EXPECTED.items():
        assert key in contract, f"{key} has no section in api_contract.md"
        assert contract[key]["success"] == want["success"], key


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_every_status_and_code_the_contract_lists_is_declared(spec, key):
    contract = parse_contract()[key]
    declared = declared_errors(spec["paths"][PREFIX + key[1]][key[0]])
    skipped = CONTRACT_NOT_IMPLEMENTED.get(key, set())
    for status, name in re.findall(r"`(\d{3})(?: ([A-Z_]+))?`", contract["errors"]):
        if status in skipped:
            continue
        assert int(status) in declared, f"{key}: contract lists {status}, OpenAPI does not"
        if name:
            assert name in declared[int(status)], f"{key}: contract lists {status} {name}"


def test_contract_only_gaps_are_the_documented_ones():
    """Anything the contract lists but the code does not declare must be a known issue."""
    contract = parse_contract()
    spec_now = app.openapi()
    gaps = set()
    for key in EXPECTED:
        declared = declared_errors(spec_now["paths"][PREFIX + key[1]][key[0]])
        for status, name in re.findall(r"`(\d{3})(?: ([A-Z_]+))?`", contract[key]["errors"]):
            if int(status) not in declared or (name and name not in declared[int(status)]):
                gaps.add((key, status))
    assert gaps == {(k, s) for k, ss in CONTRACT_NOT_IMPLEMENTED.items() for s in ss}


def test_known_not_implemented_endpoints_are_still_not_in_openapi(spec):
    """Mốc E and reset endpoints are in the contract but must not appear half-built."""
    not_built = {
        "/auth/password-reset/request",
        "/auth/password-reset/confirm",
    }
    for path in not_built:
        assert PREFIX + path not in spec["paths"], path


GUEST_ENDPOINTS = [
    ("get", "/service-plans"),
    ("post", "/business-registrations"),
    ("post", "/business-registrations/track"),
]


@pytest.mark.parametrize("key", GUEST_ENDPOINTS)
def test_the_contract_lists_every_error_status_a_guest_endpoint_declares(spec, key):
    """The other direction of the cross-check: nothing the code can answer is missing from the
    contract (500 and 503 are common to every API and listed once in section 2)."""
    contract = parse_contract()[key]
    listed = {int(status) for status, _name in re.findall(r"`(\d{3})(?: ([A-Z_]+))?`", contract["errors"])}
    declared = set(declared_errors(spec["paths"][PREFIX + key[1]][key[0]])) - {500, 503}
    assert declared <= listed, f"{key}: the contract does not list {sorted(declared - listed)}"
    named = dict(re.findall(r"`(\d{3}) ([A-Z_]+)`", contract["errors"]))
    for status, codes in declared_errors(spec["paths"][PREFIX + key[1]][key[0]]).items():
        if status in (404, 409):
            assert named.get(str(status)) in codes, (key, status)


SA_REGISTRATION_ENDPOINTS = [
    ("get", "/admin/business-registrations"),
    ("get", "/admin/business-registrations/{registration_id}"),
    ("post", "/admin/business-registrations/{registration_id}/review"),
    ("post", "/admin/business-registrations/{registration_id}/business"),
    ("post", "/admin/clans/{clan_id}/owner"),
    ("get", "/admin/provisioning-jobs/{job_id}"),
    ("get", "/admin/provisioning-jobs"),
    ("post", "/admin/provisioning-jobs/{job_id}/retry"),
    ("post", "/admin/provisioning-jobs/{job_id}/abandon"),
    ("post", "/admin/clans/{clan_id}/owner/temporary-password"),
]


@pytest.mark.parametrize("key", SA_REGISTRATION_ENDPOINTS)
def test_the_contract_lists_every_error_status_an_sa_registration_endpoint_declares(spec, key):
    """E4 reverse check: nothing the code can answer is missing from the contract."""
    contract = parse_contract()[key]
    listed = {int(status) for status, _name in re.findall(r"`(\d{3})(?: ([A-Z_]+))?`", contract["errors"])}
    declared = set(declared_errors(spec["paths"][PREFIX + key[1]][key[0]])) - {500, 503}
    assert declared <= listed, f"{key}: the contract does not list {sorted(declared - listed)}"
    named = dict(re.findall(r"`(\d{3}) ([A-Z_]+)`", contract["errors"]))
    for status, codes in declared_errors(spec["paths"][PREFIX + key[1]][key[0]]).items():
        if status in (404, 409):
            assert named.get(str(status)) in codes, (key, status)


@pytest.mark.parametrize("key", SA_REGISTRATION_ENDPOINTS)
def test_sa_registration_endpoints_are_authenticated(spec, key):
    declared = declared_errors(spec["paths"][PREFIX + key[1]][key[0]])
    assert declared[401] == AUTHED_401 and "FORBIDDEN" in declared[403]
    assert 429 not in declared  # not rate limited


def test_the_business_endpoint_requires_the_idempotency_key_header_and_takes_an_optional_body(spec):
    op = spec["paths"][PREFIX + "/admin/business-registrations/{registration_id}/business"]["post"]
    header = next(p for p in op["parameters"] if p["name"] == "Idempotency-Key")
    assert header["in"] == "header" and header["required"] is True
    assert header["schema"]["minLength"] == 8 and header["schema"]["maxLength"] == 128
    assert header["schema"].get("pattern")
    assert op["requestBody"].get("required") is not True  # no body at all means "generate the clan code"
    assert next(p for p in op["parameters"] if p["name"] == "registration_id")["required"] is True
    declared = declared_errors(op)
    assert declared[409] == {"STATE_CONFLICT", "DUPLICATE_RESOURCE", "IDEMPOTENCY_KEY_CONFLICT"}


@pytest.mark.parametrize("key", GUEST_ENDPOINTS)
def test_guest_endpoints_declare_no_authentication_errors(spec, key):
    declared = declared_errors(spec["paths"][PREFIX + key[1]][key[0]])
    assert 401 not in declared and 403 not in declared
