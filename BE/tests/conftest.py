"""Test-wide environment. Loaded before any test module imports app code.

Firebase and CORS settings are forced here so no test depends on BE/.env and no test can
reach the real Firebase project or service account. DATABASE_URL still comes from
.env (unit tests never connect; integration tests need the real branch).
"""

import os

os.environ["FIREBASE_PROJECT_ID"] = "test-project"
os.environ["FRONTEND_ORIGINS"] = "http://localhost:5173,http://localhost:8080"
os.environ["FIREBASE_SERVICE_ACCOUNT_PATH"] = ""
os.environ.pop("FIREBASE_AUTH_EMULATOR_HOST", None)
os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_firebase(monkeypatch):
    """No test may reach the real Firebase (E6): the SDK's Admin functions fail the test instead.

    A test that needs one of them replaces it with its own double (monkeypatch applies after this
    fixture), so forgetting to fake the provider is an immediate failure, never a request.
    """
    from firebase_admin import auth

    def refuse(name):
        def guard(*args, **kwargs):
            raise AssertionError(f"REAL FIREBASE CALLED: auth.{name}")

        return guard

    # (verify_id_token is not here: tests exercise the real SDK verification with google.oauth2 mocked)
    for name in ("create_user", "get_user", "delete_user", "update_user", "revoke_refresh_tokens",
                 "get_user_by_email", "delete_users", "list_users"):
        monkeypatch.setattr(auth, name, refuse(name))
