"""FirebaseIdentityProvider: fail closed, error mapping, no unsigned-token path.

No test reaches the network or a real Firebase project: SDK calls are replaced, and
the "real SDK" tests use forged tokens the SDK rejects before fetching certificates
(google.oauth2.id_token.verify_token is booby-trapped to prove it).
"""

from __future__ import annotations

import base64
import json
import time

import pytest
from firebase_admin import auth as firebase_auth
from firebase_admin import exceptions as firebase_exceptions

from app.core import firebase as fb
from app.core.firebase import (
    FirebaseIdentityProvider,
    InvalidIdToken,
    PasswordRejected,
    ProviderUnavailable,
)

PROJECT = "test-project"


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def forged_token(header: dict, *, project: str = PROJECT) -> str:
    now = int(time.time())
    claims = {
        "iss": f"https://securetoken.google.com/{project}",
        "aud": project,
        "sub": "attacker-chosen-uid",
        "iat": now - 10,
        "exp": now + 3600,
        "auth_time": now - 10,
    }
    return f"{_b64(header)}.{_b64(claims)}.{'' if header.get('alg') == 'none' else 'c2ln'}"


@pytest.fixture
def no_network(monkeypatch):
    import google.oauth2.id_token

    def boom(*_a, **_k):
        raise AssertionError("signature verification tried to reach the network")

    monkeypatch.setattr(google.oauth2.id_token, "verify_token", boom)


@pytest.fixture
def sdk_verify(monkeypatch):
    """Replace the SDK verify call; returns a dict to configure it and inspect calls."""
    state: dict = {"result": None, "error": None, "calls": []}

    def fake_verify(token, app=None, check_revoked=False, clock_skew_seconds=0):
        state["calls"].append({"check_revoked": check_revoked, "skew": clock_skew_seconds})
        if state["error"] is not None:
            raise state["error"]
        return state["result"]

    monkeypatch.setattr(firebase_auth, "verify_id_token", fake_verify)
    return state


def claims(**overrides) -> dict:
    base = {
        "uid": "uid-1",
        "sub": "uid-1",
        "email": "a@example.test",
        "email_verified": True,
        "auth_time": 1_790_000_000,
        "firebase": {"sign_in_provider": "google.com"},
    }
    base.update(overrides)
    return base


# ----- fail closed on configuration -----


async def test_missing_project_id_fails_closed(sdk_verify):
    with pytest.raises(ProviderUnavailable) as exc:
        await FirebaseIdentityProvider("").verify_id_token("anything")
    assert exc.value.reason == "project_id_not_configured"
    assert sdk_verify["calls"] == []


async def test_service_account_path_set_but_missing_fails_closed(sdk_verify, tmp_path):
    provider = FirebaseIdentityProvider(PROJECT, str(tmp_path / "nope.json"))
    with pytest.raises(ProviderUnavailable) as exc:
        await provider.verify_id_token("anything")
    assert exc.value.reason == "service_account_not_found"
    assert sdk_verify["calls"] == []


async def test_emulator_env_is_refused(sdk_verify, monkeypatch):
    monkeypatch.setenv(fb.EMULATOR_ENV, "localhost:9099")
    with pytest.raises(ProviderUnavailable) as exc:
        await FirebaseIdentityProvider(PROJECT).verify_id_token("anything")
    assert exc.value.reason == "emulator_mode_refused"
    assert sdk_verify["calls"] == []


async def test_set_password_without_service_account_is_refused(monkeypatch):
    def must_not_run(*_a, **_k):
        raise AssertionError("Admin API must not be called")

    monkeypatch.setattr(firebase_auth, "update_user", must_not_run)
    with pytest.raises(ProviderUnavailable) as exc:
        await FirebaseIdentityProvider(PROJECT).set_password("uid-1", "new-password")
    assert exc.value.reason == "admin_api_not_configured"


# ----- the real SDK rejects forged / unsigned tokens, offline -----


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "none", "typ": "JWT"},
        {"alg": "HS256", "typ": "JWT", "kid": "forged"},
        {"alg": "RS256", "typ": "JWT"},  # no kid
    ],
    ids=["alg-none", "hs256", "rs256-without-kid"],
)
async def test_real_sdk_rejects_forged_tokens(no_network, header):
    with pytest.raises(InvalidIdToken):
        await FirebaseIdentityProvider(PROJECT).verify_id_token(forged_token(header))


async def test_real_sdk_always_reaches_signature_check(monkeypatch):
    """A well-formed RS256 token is handed to Google's signature verification against
    the Firebase certificates; a bad signature ends as InvalidIdToken."""
    import google.oauth2.id_token

    seen = []

    def fake_verify_token(token, request, audience=None, certs_url=None, **_kw):
        seen.append({"audience": audience, "certs_url": certs_url})
        raise ValueError("Could not verify token signature.")

    monkeypatch.setattr(google.oauth2.id_token, "verify_token", fake_verify_token)
    token = forged_token({"alg": "RS256", "typ": "JWT", "kid": "some-key-id"})
    with pytest.raises(InvalidIdToken):
        await FirebaseIdentityProvider(PROJECT).verify_id_token(token)
    assert len(seen) == 1
    assert seen[0]["audience"] == PROJECT
    assert "securetoken" in seen[0]["certs_url"]


async def test_real_sdk_rejects_token_for_another_project(no_network):
    token = forged_token({"alg": "RS256", "typ": "JWT", "kid": "k"}, project="someone-else")
    with pytest.raises(InvalidIdToken):
        await FirebaseIdentityProvider(PROJECT).verify_id_token(token)


async def test_real_sdk_rejects_garbage(no_network):
    for token in ("", "not-a-jwt", "a.b.c"):
        with pytest.raises(InvalidIdToken):
            await FirebaseIdentityProvider(PROJECT).verify_id_token(token)


# ----- SDK error mapping -----


@pytest.mark.parametrize(
    "error, expected, reason",
    [
        (firebase_auth.InvalidIdTokenError("x"), InvalidIdToken, "invalid"),
        (firebase_auth.ExpiredIdTokenError("x", None), InvalidIdToken, "expired"),
        (firebase_auth.RevokedIdTokenError("x"), InvalidIdToken, "revoked"),
        (firebase_auth.UserDisabledError("x"), InvalidIdToken, "user_disabled"),
        (ValueError("x"), InvalidIdToken, "invalid"),
        (firebase_auth.CertificateFetchError("x", None), ProviderUnavailable, "certificate_fetch_failed"),
        (firebase_exceptions.UnavailableError("x"), ProviderUnavailable, "firebase_error"),
    ],
)
async def test_sdk_errors_are_mapped(sdk_verify, error, expected, reason):
    sdk_verify["error"] = error
    with pytest.raises(expected) as exc:
        await FirebaseIdentityProvider(PROJECT).verify_id_token("token")
    assert exc.value.reason == reason
    # Our exception never carries the SDK message (it may quote the token).
    assert str(exc.value) == reason


async def test_claims_are_mapped(sdk_verify):
    sdk_verify["result"] = claims()
    identity = await FirebaseIdentityProvider(PROJECT).verify_id_token("token")
    assert identity.uid == "uid-1"
    assert identity.email == "a@example.test" and identity.email_verified is True
    assert identity.auth_time.timestamp() == 1_790_000_000
    assert identity.auth_time.tzinfo is not None
    assert identity.sign_in_provider == "google.com"


async def test_missing_auth_time_is_invalid(sdk_verify):
    sdk_verify["result"] = claims(auth_time=None)
    with pytest.raises(InvalidIdToken):
        await FirebaseIdentityProvider(PROJECT).verify_id_token("token")


async def test_revocation_check_only_with_service_account(sdk_verify, monkeypatch):
    sdk_verify["result"] = claims()
    await FirebaseIdentityProvider(PROJECT).verify_id_token("token")

    with_admin = FirebaseIdentityProvider(PROJECT, "configured.json")
    monkeypatch.setattr(with_admin, "_get_app", lambda: object())
    await with_admin.verify_id_token("token")

    assert [c["check_revoked"] for c in sdk_verify["calls"]] == [False, True]
    assert all(c["skew"] == fb.CLOCK_SKEW_SECONDS for c in sdk_verify["calls"])


# ----- set_password mapping (Admin API replaced) -----


@pytest.fixture
def admin_provider(monkeypatch):
    provider = FirebaseIdentityProvider(PROJECT, "configured.json")
    monkeypatch.setattr(provider, "_get_app", lambda: object())
    return provider


async def test_set_password_updates_then_revokes_refresh_tokens(admin_provider, monkeypatch):
    calls = []
    monkeypatch.setattr(firebase_auth, "update_user", lambda uid, **kw: calls.append(("update", uid)))
    monkeypatch.setattr(
        firebase_auth, "revoke_refresh_tokens", lambda uid, **kw: calls.append(("revoke", uid))
    )
    await admin_provider.set_password("uid-1", "new-password")
    assert calls == [("update", "uid-1"), ("revoke", "uid-1")]


@pytest.mark.parametrize(
    "error, expected",
    [
        (ValueError("weak"), PasswordRejected),
        (firebase_exceptions.InvalidArgumentError("policy"), PasswordRejected),
        (firebase_exceptions.UnavailableError("down"), ProviderUnavailable),
    ],
)
async def test_set_password_errors(admin_provider, monkeypatch, error, expected):
    def raise_(*_a, **_k):
        raise error

    monkeypatch.setattr(firebase_auth, "update_user", raise_)
    with pytest.raises(expected):
        await admin_provider.set_password("uid-1", "new-password")


async def test_revoke_failure_after_update_is_provider_unavailable(admin_provider, monkeypatch):
    monkeypatch.setattr(firebase_auth, "update_user", lambda *a, **k: None)

    def raise_(*_a, **_k):
        raise firebase_exceptions.UnavailableError("down")

    monkeypatch.setattr(firebase_auth, "revoke_refresh_tokens", raise_)
    with pytest.raises(ProviderUnavailable):
        await admin_provider.set_password("uid-1", "new-password")
