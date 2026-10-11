from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import auth as auth_dependency
from app.main import app
from app.models.postgres import Account


def test_openapi_declares_firebase_bearer_security_scheme():
    openapi = app.openapi()

    assert openapi["components"]["securitySchemes"]["FirebaseBearer"] == {
        "type": "http",
        "description": "Nhập Firebase ID token (không thêm tiền tố Bearer).",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }

    for method in ("get",):
        operation = openapi["paths"]["/api/auth/me"][method]
        assert operation["security"] == [{"FirebaseBearer": []}]
        assert all(
            parameter.get("name", "").lower() != "authorization"
            for parameter in operation.get("parameters", [])
        )

    register = openapi["paths"]["/api/auth/register"]["post"]
    assert register["security"] == [{"FirebaseBearer": []}]


@pytest.mark.asyncio
async def test_auth_me_without_token_returns_401():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert "Thiếu Authorization header" in response.json()["detail"]


@pytest.mark.asyncio
async def test_bearer_token_reaches_me_and_register(monkeypatch):
    received_tokens: list[str] = []
    token = "firebase-id-token-from-authorize"
    account = Account(
        id="security-test-user",
        firebase_uid="firebase-security-test-user",
        email="security-test@example.test",
        display_name="Security Test",
        status="ACTIVE",
        email_verified=True,
        phone_verified=False,
        first_login_required=False,
    )
    account.roles = []

    def verify_token(id_token: str):
        received_tokens.append(id_token)
        return {"uid": account.firebase_uid}

    async def find_account(_db, firebase_uid: str):
        assert firebase_uid == account.firebase_uid
        return account

    monkeypatch.setattr(auth_dependency, "verify_firebase_token", verify_token)
    monkeypatch.setattr(
        auth_dependency, "get_account_by_firebase_uid", find_account
    )

    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        me_response = await client.get("/api/auth/me", headers=headers)
        register_response = await client.post(
            "/api/auth/register", headers=headers
        )

    assert me_response.status_code == 200
    assert register_response.status_code == 200
    assert received_tokens == [token, token]
