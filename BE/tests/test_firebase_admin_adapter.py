"""The Firebase Admin adapter of Mốc E6a (create_user / get_user / delete_user), with the SDK replaced by
test doubles: nothing here can reach Firebase.

What is proven: every SDK call goes through asyncio.to_thread and is bounded by the per-call timeout;
create and delete accept only `own-<uuid>` uids and refuse anything else BEFORE the SDK; the adapter has
no lookup or delete by e-mail; SDK errors map to short reasons; the timing settings leave room for three
calls inside the lease."""

from __future__ import annotations

import ast
import asyncio
import time
import uuid
from pathlib import Path

import pytest
from firebase_admin import auth as firebase_auth
from firebase_admin import exceptions as firebase_exceptions
from pydantic import ValidationError

import app.core.firebase as fb
from app.core.config import Settings, settings
from app.core.firebase import (
    FirebaseIdentityProvider,
    PasswordRejected,
    ProviderEmailTaken,
    ProviderInvalidUser,
    ProviderUnavailable,
    ProviderUser,
    ProviderUserExists,
    UnsafeUid,
    own_uid,
    require_own_uid,
)

ROOT = Path(__file__).resolve().parents[1]
JOB = uuid.UUID("3f2b4e5c-0000-4000-8000-000000000001")
UID = f"own-{JOB}"


class Record:
    """What an SDK user record exposes (no password is ever readable from Firebase)."""

    def __init__(self, uid=UID, email="Owner@Example.TEST", display_name="Owner", disabled=False):
        self.uid, self.email, self.display_name, self.disabled = uid, email, display_name, disabled


@pytest.fixture
def provider(monkeypatch) -> FirebaseIdentityProvider:
    p = FirebaseIdentityProvider("test-project", "service-account-that-is-never-read.json", call_timeout_seconds=2)
    monkeypatch.setattr(p, "_get_app", lambda: object())
    return p


@pytest.fixture
def threads(monkeypatch):
    """Records every asyncio.to_thread call the adapter makes."""
    calls: list[str] = []
    real = asyncio.to_thread

    async def recording(function, *args, **kwargs):
        calls.append(getattr(function, "__name__", repr(function)))
        return await real(function, *args, **kwargs)

    monkeypatch.setattr(fb.asyncio, "to_thread", recording)
    return calls


# ------------------------------------------------------------------ uids


@pytest.mark.parametrize("uid", [
    UID, f"own-{uuid.uuid4()}", f"own-{uuid.UUID(int=0)}",
])
def test_an_own_uid_is_accepted(uid):
    assert require_own_uid(uid) == uid


@pytest.mark.parametrize("uid", [
    "", "own-", "own", "own-not-a-uuid", f"OWN-{JOB}", f"own-{str(JOB).upper()}", f"own-{JOB.hex}", f" own-{JOB}",
    f"own-{JOB} ", f"own-{JOB}-extra", f"x-{JOB}", str(JOB), "owner@example.test", "google-uid-123", "own-../etc/passwd",
    None, 123,
])
def test_anything_that_is_not_a_canonical_own_uuid_uid_is_refused(uid):
    with pytest.raises(UnsafeUid):
        require_own_uid(uid)


def test_own_uid_is_the_job_check_value():
    assert own_uid(JOB) == UID


# ------------------------------------------------------------------ create_user


async def test_create_user_sends_exactly_the_planned_fields_and_no_phone(provider, monkeypatch, threads):
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return Record()

    monkeypatch.setattr(firebase_auth, "create_user", create)
    user = await provider.create_user(uid=UID, email="Owner@Example.TEST", display_name="Owner", password="Pw-for-the-test-1")
    assert set(seen) == {"uid", "email", "display_name", "password", "email_verified", "disabled", "app"}
    assert (seen["uid"], seen["email"], seen["display_name"]) == (UID, "Owner@Example.TEST", "Owner")
    assert seen["email_verified"] is False and seen["disabled"] is False and "phone_number" not in seen
    assert user == ProviderUser(uid=UID, email="Owner@Example.TEST", display_name="Owner", disabled=False)
    assert threads == ["create"]  # through asyncio.to_thread


@pytest.mark.parametrize("sdk_error, expected", [
    (firebase_auth.UidAlreadyExistsError("x", None, None), ProviderUserExists),
    (firebase_auth.EmailAlreadyExistsError("x", None, None), ProviderEmailTaken),
    (ValueError("Invalid password string. Password must be a string at least 6 characters long."), PasswordRejected),
    (firebase_exceptions.InvalidArgumentError("WEAK_PASSWORD : Password should be at least 6 characters"), PasswordRejected),
    (firebase_exceptions.InvalidArgumentError("PASSWORD_DOES_NOT_MEET_REQUIREMENTS"), PasswordRejected),
    (ValueError('Malformed email address string: "x".'), ProviderInvalidUser),
    (firebase_exceptions.InvalidArgumentError("INVALID_EMAIL"), ProviderInvalidUser),
    (firebase_exceptions.UnavailableError("backend down"), ProviderUnavailable),
    (firebase_exceptions.FirebaseError("INTERNAL", "boom"), ProviderUnavailable),
])
async def test_create_user_errors_map_to_short_reasons(provider, monkeypatch, sdk_error, expected):
    def create(**kwargs):
        raise sdk_error

    monkeypatch.setattr(firebase_auth, "create_user", create)
    with pytest.raises(expected) as exc:
        await provider.create_user(uid=UID, email="o@example.test", display_name="O", password="Pw-for-the-test-1")
    assert "Pw-for-the-test-1" not in repr(exc.value) and "o@example.test" not in repr(exc.value)


@pytest.mark.parametrize("uid", ["abc", "own-", "owner@example.test", f"own-{str(JOB).upper()}", ""])
async def test_create_user_refuses_a_uid_that_is_not_ours_before_the_sdk(provider, monkeypatch, uid):
    def never(**kwargs):
        raise AssertionError("the SDK must not be reached")

    monkeypatch.setattr(firebase_auth, "create_user", never)
    with pytest.raises(UnsafeUid):
        await provider.create_user(uid=uid, email="o@example.test", display_name="O", password="x" * 16)


# ------------------------------------------------------------------ get_user


async def test_get_user_returns_a_record_without_secrets_or_none(provider, monkeypatch, threads):
    monkeypatch.setattr(firebase_auth, "get_user", lambda uid, app=None: Record(uid=uid))
    user = await provider.get_user(UID)
    assert user == ProviderUser(uid=UID, email="Owner@Example.TEST", display_name="Owner", disabled=False)
    assert not hasattr(user, "password") and not hasattr(user, "password_hash")

    def missing(uid, app=None):
        raise firebase_auth.UserNotFoundError("none")

    monkeypatch.setattr(firebase_auth, "get_user", missing)
    assert await provider.get_user(UID) is None
    assert threads == ["<lambda>", "missing"]


@pytest.mark.parametrize("sdk_error, expected", [
    (firebase_exceptions.UnavailableError("down"), ProviderUnavailable),
    (firebase_exceptions.FirebaseError("INTERNAL", "boom"), ProviderUnavailable),
    (ValueError("Invalid uid"), ProviderInvalidUser),
])
async def test_get_user_errors(provider, monkeypatch, sdk_error, expected):
    def get(uid, app=None):
        raise sdk_error

    monkeypatch.setattr(firebase_auth, "get_user", get)
    with pytest.raises(expected):
        await provider.get_user(UID)


# ------------------------------------------------------------------ delete_user


async def test_delete_user_deletes_an_own_uid_and_says_whether_there_was_one(provider, monkeypatch, threads):
    deleted = []
    monkeypatch.setattr(firebase_auth, "delete_user", lambda uid, app=None: deleted.append(uid))
    assert await provider.delete_user(UID) is True and deleted == [UID]

    def missing(uid, app=None):
        raise firebase_auth.UserNotFoundError("none")

    monkeypatch.setattr(firebase_auth, "delete_user", missing)
    assert await provider.delete_user(UID) is False  # "there was none" is a success for a clean-up
    assert threads == ["<lambda>", "missing"]


@pytest.mark.parametrize("uid", [
    "abc", "", "own-", "owner@example.test", "google-uid-123", str(JOB), f"OWN-{JOB}", f"own-{str(JOB).upper()}",
    "own-not-a-uuid", "own-" + "a" * 200, None,
])
async def test_delete_user_refuses_every_uid_that_is_not_an_own_uuid_before_the_sdk(provider, monkeypatch, uid):
    def never(*a, **k):
        raise AssertionError("the SDK must not be reached")

    monkeypatch.setattr(firebase_auth, "delete_user", never)
    with pytest.raises(UnsafeUid):
        await provider.delete_user(uid)


async def test_delete_user_errors_map_to_unavailable(provider, monkeypatch):
    def down(uid, app=None):
        raise firebase_exceptions.UnavailableError("down")

    monkeypatch.setattr(firebase_auth, "delete_user", down)
    with pytest.raises(ProviderUnavailable):
        await provider.delete_user(UID)


# ------------------------------------------------------------------ no admin API: nothing is sent


async def test_without_a_service_account_every_admin_call_is_refused_without_touching_the_sdk(monkeypatch):
    p = FirebaseIdentityProvider("test-project", "")
    for name in ("create_user", "get_user", "delete_user", "update_user"):
        monkeypatch.setattr(firebase_auth, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError("SDK reached")))
    assert p.admin_api_enabled is False
    with pytest.raises(ProviderUnavailable) as exc:
        await p.create_user(uid=UID, email="o@example.test", display_name="O", password="x" * 16)
    assert exc.value.reason == "admin_api_not_configured"
    with pytest.raises(ProviderUnavailable):
        await p.get_user(UID)
    with pytest.raises(ProviderUnavailable):
        await p.delete_user(UID)


# ------------------------------------------------------------------ A: every SDK call through asyncio.to_thread


def test_every_sdk_call_goes_through_the_one_bounded_helper():
    """No `firebase_auth.<function>(...)` is CALLED directly in the adapter: each is only passed to
    self._call(...), which wraps it in asyncio.to_thread and the timeout."""
    tree = ast.parse((ROOT / "app" / "core" / "firebase.py").read_text(encoding="utf-8"))
    direct = [
        f"{node.func.attr} (line {node.lineno})"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "firebase_auth"
    ]
    assert direct == []
    passed = {
        node.args[0].attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_call"
        and node.args and isinstance(node.args[0], ast.Attribute)
    }
    assert passed == {"verify_id_token", "update_user", "revoke_refresh_tokens", "get_user", "create_user", "delete_user"}
    source = (ROOT / "app" / "core" / "firebase.py").read_text(encoding="utf-8")
    assert "run_in_threadpool" not in source and "asyncio.to_thread" in source


async def test_the_existing_calls_use_to_thread_too(provider, monkeypatch, threads):
    monkeypatch.setattr(firebase_auth, "update_user", lambda uid, **kw: None)
    monkeypatch.setattr(firebase_auth, "revoke_refresh_tokens", lambda uid, app=None: None)
    monkeypatch.setattr(firebase_auth, "verify_id_token", lambda token, **kw: {"uid": "u", "auth_time": 1})
    await provider.set_password("u", "x" * 16)
    await provider.verify_id_token("t")
    assert threads == ["<lambda>", "<lambda>", "<lambda>"]


# ------------------------------------------------------------------ B: the timeout of each call


async def test_a_call_that_takes_longer_than_the_timeout_is_provider_unavailable_and_returns_in_time(monkeypatch):
    p = FirebaseIdentityProvider("test-project", "service-account-that-is-never-read.json", call_timeout_seconds=0.2)
    monkeypatch.setattr(p, "_get_app", lambda: object())

    def slow(uid, app=None):
        time.sleep(1.0)
        return Record()

    monkeypatch.setattr(firebase_auth, "get_user", slow)
    started = time.monotonic()
    with pytest.raises(ProviderUnavailable) as exc:
        await p.get_user(UID)
    assert exc.value.reason == "timeout" and time.monotonic() - started < 0.8


def test_the_default_timeout_comes_from_the_settings():
    p = FirebaseIdentityProvider("test-project", "x.json")
    assert p._call_timeout == settings.FIREBASE_CALL_TIMEOUT_SECONDS == 15


def test_the_sdk_app_gets_the_same_http_timeout(monkeypatch):
    captured = {}

    def init(credential, options=None, name=None):
        captured.update(options=options, name=name)
        return object()

    def no_app(name):
        raise ValueError("none yet")

    monkeypatch.setattr(fb.firebase_admin, "initialize_app", init)
    monkeypatch.setattr(fb.firebase_admin, "get_app", no_app)
    FirebaseIdentityProvider("test-project", "", call_timeout_seconds=7)._get_app()
    assert captured["options"] == {"projectId": "test-project", "httpTimeout": 7.0}


def test_three_calls_always_fit_inside_the_lease():
    assert 3 * settings.FIREBASE_CALL_TIMEOUT_SECONDS < settings.PROVISIONING_LEASE_SECONDS
    assert (settings.FIREBASE_CALL_TIMEOUT_SECONDS, settings.PROVISIONING_LEASE_SECONDS) == (15, 90)


@pytest.mark.parametrize("timeout, lease, ok", [(15, 90, True), (29, 90, True), (30, 90, False), (31, 90, False), (15, 45, False), (15, 46, True)])
def test_settings_refuse_a_lease_that_cannot_hold_three_calls(timeout, lease, ok):
    kwargs = dict(_env_file=None, DATABASE_URL="postgresql://u:p@h/db", FIREBASE_CALL_TIMEOUT_SECONDS=timeout, PROVISIONING_LEASE_SECONDS=lease)
    if ok:
        assert Settings(**kwargs).PROVISIONING_LEASE_SECONDS == lease
    else:
        with pytest.raises(ValidationError) as exc:
            Settings(**kwargs)
        assert "postgresql://" not in str(exc.value)  # the connection string is never echoed


@pytest.mark.parametrize("name", ["FIREBASE_CALL_TIMEOUT_SECONDS", "PROVISIONING_LEASE_SECONDS", "PROVISIONING_MAX_ATTEMPTS", "OWNER_TEMP_PASSWORD_TTL_HOURS"])
def test_settings_refuse_zero_and_negative_values(name):
    for value in (0, -1):
        extra = {"PROVISIONING_LEASE_SECONDS": 1000} if name == "FIREBASE_CALL_TIMEOUT_SECONDS" else {}
        with pytest.raises(ValidationError):
            Settings(_env_file=None, DATABASE_URL="postgresql://u:p@h/db", **{**extra, name: value})


def test_the_planned_defaults():
    assert (settings.PROVISIONING_MAX_ATTEMPTS, settings.OWNER_TEMP_PASSWORD_TTL_HOURS, settings.OWNER_TEMP_PASSWORD_REQUIRE_SYMBOL) == (5, 72, False)


# ------------------------------------------------------------------ the adapter can only ever act by uid


def test_nothing_in_the_application_looks_up_or_deletes_a_firebase_user_by_e_mail():
    forbidden = ("get_user_by_email", "get_user_by_phone_number", "delete_users", "list_users", "get_users", "get_user_by_provider_uid")
    for path in (ROOT / "app").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # the Firebase SDK module (`auth` / `firebase_auth`) or a name imported from it
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in ("auth", "firebase_auth"):
                assert node.attr not in forbidden, f"{path.relative_to(ROOT)} uses {node.attr}"
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("firebase_admin"):
                assert not {a.name for a in node.names} & set(forbidden), f"{path.relative_to(ROOT)} imports a lookup by e-mail"


def test_the_adapter_has_no_method_that_takes_an_e_mail_to_find_or_delete():
    methods = [n for n in dir(FirebaseIdentityProvider) if not n.startswith("_")]
    assert sorted(methods) == sorted(["admin_api_enabled", "create_user", "delete_user", "get_user", "set_password", "verify_id_token"])
    import inspect

    for name in ("get_user", "delete_user"):
        assert list(inspect.signature(getattr(FirebaseIdentityProvider, name)).parameters) == ["self", "uid"]


# ------------------------------------------------------------------ the guard that keeps every test off the real Firebase


def test_the_real_sdk_admin_functions_cannot_be_reached_by_accident():
    """conftest replaces them with functions that fail the test: a unit test that forgot to fake the provider
    cannot send a request to Firebase."""
    for name in ("create_user", "get_user", "delete_user", "update_user", "revoke_refresh_tokens", "get_user_by_email"):
        with pytest.raises(AssertionError, match="REAL FIREBASE"):
            getattr(firebase_auth, name)("anything")
