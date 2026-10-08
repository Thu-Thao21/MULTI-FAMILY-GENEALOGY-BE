"""Mechanical security checks backing docs/security_review.md (Mốc G).

Each test proves one line of the review by test or by reading the code with the standard
library (ast/inspect), not by assumption.
"""

from __future__ import annotations

import ast
import inspect
import re
import uuid
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy.dialects import postgresql

from app.main import app
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository

APP_DIR = Path(__file__).resolve().parents[1] / "app"


# ----- 1. response schemas never expose internal or credential data -----

FORBIDDEN_RESPONSE_FIELDS = {
    "firebase_uid", "token_jti_hash", "tracking_code_hash", "storage_key", "password",
    "password_hash", "new_password", "id_token", "recent_id_token", "oob_code",
    "failed_login_count", "locked_until", "must_change_password",
    "temporary_password_issued_at", "temporary_password_expires_at", "password_changed_at",
    "auth_provider", "revoke_reason", "ip_address", "user_agent", "temporary_password",
}

# The ONLY places a temporary password (and its expiry) leaves the server: the response that creates an Owner
# or retries the job (Mốc E6, one model for both) and the response that reissues the Owner's password (E6b).
# test_the_temporary_password_is_returned_by_exactly_these_responses pins that no third one appears.
ALLOWED_EXCEPTIONS = {
    "OwnerProvisionResponse": {"temporary_password", "temporary_password_expires_at"},
    "OwnerPasswordResetResponse": {"temporary_password", "temporary_password_expires_at"},
}


def _reachable_response_schemas(spec: dict) -> set[str]:
    schemas = spec["components"]["schemas"]
    seen: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if ref and ref.split("/")[-1] not in seen:
                name = ref.split("/")[-1]
                seen.add(name)
                walk(schemas[name])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for ops in spec["paths"].values():
        for op in ops.values():
            for response in op["responses"].values():
                walk(response.get("content", {}))
    return seen


def test_no_response_schema_exposes_sensitive_fields():
    spec = app.openapi()
    names = _reachable_response_schemas(spec)
    assert {"SessionCreateResponse", "MeResponse", "AdminUserDetail", "ClanUserItem"} <= names
    for name in names:
        properties = set(spec["components"]["schemas"][name].get("properties", {})) - ALLOWED_EXCEPTIONS.get(name, set())
        assert properties.isdisjoint(FORBIDDEN_RESPONSE_FIELDS), (name, properties & FORBIDDEN_RESPONSE_FIELDS)


def test_the_temporary_password_is_returned_by_exactly_these_responses():
    spec = app.openapi()
    holders = sorted(
        name
        for name in _reachable_response_schemas(spec)
        if "temporary_password" in spec["components"]["schemas"][name].get("properties", {})
    )
    assert holders == ["OwnerPasswordResetResponse", "OwnerProvisionResponse"]
    assert set(ALLOWED_EXCEPTIONS) == set(holders)

    def routes_returning(model: str) -> list[tuple[str, str]]:
        return sorted(
            (method, path.removeprefix("/api/v1"))
            for path, ops in spec["paths"].items() for method, op in ops.items()
            if model in str(op["responses"].get("200", {})) + str(op["responses"].get("201", {}))
        )

    assert routes_returning("OwnerProvisionResponse") == [
        ("post", "/admin/clans/{clan_id}/owner"), ("post", "/admin/provisioning-jobs/{job_id}/retry")]
    assert routes_returning("OwnerPasswordResetResponse") == [("post", "/admin/clans/{clan_id}/owner/temporary-password")]


def test_the_bearer_token_is_returned_by_exactly_one_response():
    spec = app.openapi()
    holders = [
        name
        for name in _reachable_response_schemas(spec)
        if "access_token" in spec["components"]["schemas"][name].get("properties", {})
    ]
    assert holders == ["SessionCreateResponse"]


# ----- 2. request secrets are SecretStr and never print -----


def _request_models():
    import app.schemas.auth as auth_schemas
    import app.schemas.business as business_schemas
    import app.schemas.users as user_schemas
    from app.schemas.common import RequestModel

    found = {}
    for module in (auth_schemas, business_schemas, user_schemas):
        for name, obj in vars(module).items():
            if inspect.isclass(obj) and issubclass(obj, RequestModel) and obj is not RequestModel:
                found[name] = obj
    return found


SECRET_FIELD = re.compile(r"(token|password|oob_code|secret)", re.I)


def test_every_secret_looking_request_field_is_secretstr():
    models = _request_models()
    assert "SessionCreateRequest" in models and "ChangePasswordRequest" in models
    checked = 0
    for name, model in models.items():
        for field, info in model.model_fields.items():
            if SECRET_FIELD.search(field):
                assert "SecretStr" in str(info.annotation), (name, field, info.annotation)
                checked += 1
    assert checked >= 5  # id_token, recent_id_token, new_password, oob_code, new_password...


def test_secrets_do_not_appear_in_repr_or_validation_errors():
    from pydantic import ValidationError

    from app.schemas.auth import ChangePasswordRequest, SessionCreateRequest

    request = ChangePasswordRequest(new_password="hunter2-secret", recent_id_token="tok-secret-123")
    for text in (repr(request), str(request), request.model_dump_json(), str(request.model_dump())):
        assert "hunter2-secret" not in text and "tok-secret-123" not in text
    assert isinstance(request.new_password, SecretStr)
    with pytest.raises(ValidationError) as exc:
        ChangePasswordRequest(new_password="x", recent_id_token="tok-secret-123", extra="y")
    assert "tok-secret-123" not in str(exc.value)
    assert SessionCreateRequest(id_token="id-secret").id_token.get_secret_value() == "id-secret"


# ----- 3. no hand-built SQL -----


def _python_files():
    return [p for p in APP_DIR.rglob("*.py") if "__pycache__" not in p.parts]


def _text_calls():
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if name in {"text", "exec_driver_sql"}:
                    yield path.name, node


def test_every_text_fragment_is_a_plain_string_literal():
    """text() is used for server defaults and index predicates only, always a constant:
    never an f-string, concatenation, format() or variable that user input could reach."""
    calls = list(_text_calls())
    assert len(calls) >= 10  # the scan sees the entities
    offenders = [
        (name, node.lineno)
        for name, node in calls
        if not (node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str))
    ]
    assert offenders == []


def test_the_only_executed_statement_text_is_the_connectivity_probe():
    statements = [
        (name, node.args[0].value)
        for name, node in _text_calls()
        if re.match(r"\s*(SELECT|INSERT|UPDATE|DELETE|WITH)\b", node.args[0].value, re.I)
    ]
    assert statements == [("postgres.py", "SELECT 1")]


def test_no_sql_is_formatted_from_strings():
    pattern = re.compile(r"""(f|rf|fr)["'](\s*)(SELECT|INSERT|UPDATE|DELETE)\b""", re.I)
    for path in _python_files():
        assert not pattern.search(path.read_text(encoding="utf-8")), path


# ----- 4. logging calls never receive secret-bearing values -----

SENSITIVE_NAMES = {
    "token", "id_token", "recent_id_token", "access_token", "bearer", "password",
    "new_password", "oob_code", "firebase_uid", "uid", "email", "database_url",
    "authorization", "credentials", "service_account_path",
}
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}


def _logging_calls():
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in LOG_METHODS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"logger", "logging"}
            ):
                yield path, node


def _names_in(node: ast.AST) -> set[str]:
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id.lower())
        elif isinstance(child, ast.Attribute):
            names.add(child.attr.lower())
    return names


def test_no_logging_call_takes_a_secret_looking_value():
    calls = list(_logging_calls())
    assert len(calls) >= 8  # the scan really sees the code base
    offenders = []
    for path, node in calls:
        arguments = node.args[1:] if node.args else []  # arg 0 is the message template
        for argument in arguments + [kw.value for kw in node.keywords]:
            hit = _names_in(argument) & SENSITIVE_NAMES
            if hit:
                offenders.append((path.name, node.lineno, sorted(hit)))
    assert offenders == []


def test_log_message_templates_do_not_interpolate_exception_text():
    """Exception messages can embed tokens, SQL parameters or DATABASE_URL."""
    offenders = []
    for path, node in _logging_calls():
        for argument in node.args[1:]:
            # logger.error("...%s", exc) or str(exc) would print the message.
            if isinstance(argument, ast.Name) and argument.id in {"exc", "e", "err", "error"}:
                offenders.append((path.name, node.lineno))
            if (
                isinstance(argument, ast.Call)
                and isinstance(argument.func, ast.Name)
                and argument.func.id in {"str", "repr"}
            ):
                offenders.append((path.name, node.lineno))
    # startup_check's `logger.critical("%s", exc)` is allowed: ConfigurationError text lists
    # variable names only (tests/test_startup_checks.py proves it carries no values).
    assert offenders == [("main.py", offenders[0][1])]


# ----- 5. clan isolation in the repositories -----


class _Result:
    rowcount = 0

    def all(self):
        return []

    def first(self):
        return None

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return None

    def scalar_one(self):
        return 0


class _StubSession:
    def __init__(self) -> None:
        self.statements: list = []

    async def execute(self, stmt, *args, **kwargs):
        self.statements.append(stmt)
        return _Result()

    def add(self, _obj) -> None:
        pass

    async def flush(self) -> None:
        pass


def _argument_for(name: str, annotation) -> object:
    if name.endswith("_ids"):
        return [uuid.uuid4()]
    if name == "codes":
        return ["CODE"]
    if name in {"limit", "offset"}:
        return 10
    if name in {"status", "membership_status", "q", "token_hash", "tracking_code_hash", "code"}:
        return None if name in {"status", "membership_status", "q"} else "x"
    if name == "now":
        import datetime

        return datetime.datetime.now(datetime.timezone.utc)
    return uuid.uuid4()


async def _sql_of(repo_class, method_name: str) -> list[str]:
    session = _StubSession()
    repo = repo_class(session)
    method = getattr(repo, method_name)
    kwargs = {
        name: _argument_for(name, p.annotation)
        for name, p in inspect.signature(method).parameters.items()
        if p.default is inspect.Parameter.empty or name in {"clan_id", "user_ids"}
    }
    await method(**kwargs)
    return [str(s.compile(dialect=postgresql.dialect())) for s in session.statements]


def _public_methods(repo_class) -> list[str]:
    return [
        name
        for name, member in inspect.getmembers(repo_class, inspect.iscoroutinefunction)
        if not name.startswith("_")
    ]


# Methods WITHOUT a clan_id parameter in FamilyRepository, each with the reason it is safe.
# A new method must be added here (with a reason) or take clan_id: this forces a decision.
FAMILY_METHODS_WITHOUT_CLAN_ID = {
    # Global resources, not owned by a clan (registrations exist before any clan).
    "get_registration_by_id": "global: registration",
    "get_registration_by_tracking_hash": "global: looked up by secret hash",
    "list_registrations": "global: SA-only list",
    "list_registration_status_history": "keyed by registration_id (pre-clan)",
    "list_registration_attachments": "keyed by registration_id (pre-clan)",
    "get_plan_by_id": "global catalog",
    "get_plan_by_code": "global catalog",
    "list_active_plans": "global catalog",
    "list_plan_feature_limits": "global catalog",
    # Mốc E step E3: public catalog and Guest registration. No clan exists yet; the only keys
    # are plan ids, the applicant (e-mail and clan name) and the secret tracking-code hash.
    "list_active_plans_page": "global catalog: public, ACTIVE plans only",
    "count_active_plans": "global catalog: public, ACTIVE plans only",
    "list_feature_limits_for_plans": "global catalog: features of the plans on the page",
    "exists_pending_registration": "pre-clan: duplicate check on the applicant, returns a boolean",
    "create_registration": "pre-clan: a Guest registration (no clan yet)",
    "add_registration_status_history": "pre-clan: keyed by registration_id",
    # Mốc E step E4: the System Admin administers registrations, which exist before any clan.
    # Authorization (System Admin only, system scope) is done by require_action before these run.
    "list_registrations_page": "pre-clan: SA-only list of registrations, keyed by filters",
    "count_registrations": "pre-clan: SA-only count, same filters as the list",
    "get_registration_with_plan": "pre-clan: SA-only detail, keyed by registration_id",
    "lock_registration": "pre-clan: the review lock, keyed by registration_id",
    "apply_registration_review": "pre-clan: write on the registration row locked just before",
    # Mốc E step E5: the System Admin creates the Business of a registration (no clan exists yet).
    "create_clan": "creates a clan (the clan_id is generated here); keyed by registration_id, SA only",
    # Mốc E step E7: the System Admin activates a clan; both writes are on rows locked just before.
    "activate_clan": "write on the clan row returned by lock_clan (SA only, clan.activate)",
    "activate_subscription": "write on a subscription row returned by lock_subscriptions(clan_id)",
    "get_clan_by_code": "clan lookup by unique code, returns the clan itself",
    "get_clan_by_registration_id": "clan lookup by unique registration, returns the clan itself",
    "get_invitation_by_token_hash": "entry point by secret hash; caller must check clan_id",
    "get_reset_by_token_hash": "user-scoped secret hash",
    "get_latest_unused_reset": "user-scoped (user_id)",
    "get_email_log": "global log",
    "list_email_logs_for_registration": "global log keyed by registration_id",
    "list_retryable_email_logs": "global log (operator job)",
    "list_email_attempts": "global log keyed by email_id",
    # Caller's OWN memberships: filtered by user_id, used to find the caller's clans.
    "list_active_memberships_for_user": "caller's own memberships (user_id)",
    "list_memberships_with_clans": "caller's own memberships (user_id)",
    # Reached only through an assignment that was already fetched with clan_id + user_id
    # under lock_active_fa_assignments (Mốc F).
    "list_assignment_permission_codes": "keyed by assignment_id from a clan-filtered lock",
    "add_fa_permissions": "write keyed by assignment_id from a clan-filtered lock",
    "delete_fa_permissions": "write keyed by assignment_id from a clan-filtered lock",
}


def test_family_repository_methods_without_clan_id_are_all_accounted_for():
    without = {
        name
        for name in _public_methods(FamilyRepository)
        if "clan_id" not in inspect.signature(getattr(FamilyRepository, name)).parameters
    }
    assert without == set(FAMILY_METHODS_WITHOUT_CLAN_ID)


@pytest.mark.parametrize("repo_class", [FamilyRepository, UserAccessRepository])
async def test_every_query_taking_clan_id_filters_by_it(repo_class):
    checked = []
    for name in _public_methods(repo_class):
        if "clan_id" not in inspect.signature(getattr(repo_class, name)).parameters:
            continue
        statements = await _sql_of(repo_class, name)
        if not statements:  # pure writes via session.add (no query)
            continue
        for sql in statements:
            assert "WHERE" in sql, (repo_class.__name__, name, sql)
            where = sql.split("WHERE", 1)[1]
            assert "clan_id" in where, (repo_class.__name__, name, "no clan_id filter", sql)
        checked.append(name)
    assert len(checked) >= (15 if repo_class is FamilyRepository else 2), checked


def test_listing_queries_for_a_clan_are_never_unfiltered():
    """The two Mốc F list queries bind clan_id as a WHERE condition (not only a join)."""
    import asyncio

    sql = asyncio.run(_sql_of(FamilyRepository, "list_clan_members"))[0]
    assert "clan_memberships.clan_id = " in sql.split("WHERE", 1)[1]
    sql = asyncio.run(_sql_of(UserAccessRepository, "list_clan_role_codes"))[0]
    assert "user_roles.clan_id = " in sql.split("WHERE", 1)[1]
