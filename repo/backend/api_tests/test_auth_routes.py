"""
API tests for authentication endpoints: login, logout, whoami.

Uses the http_client fixture (httpx AsyncClient + ASGI transport) so no
real HTTP server is started.
"""
from __future__ import annotations

import pytest


class TestLogin:
    async def test_login_valid_credentials_returns_200_with_token(
        self, http_client, sample_password
    ) -> None:
        response = await http_client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": sample_password},
        )
        assert response.status_code == 200
        body = response.json()
        assert "token" in body
        assert "user_id" in body
        assert "roles" in body
        assert "expires_at" in body
        assert len(body["token"]) > 20

    async def test_login_invalid_password_returns_401(
        self, http_client
    ) -> None:
        response = await http_client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": "WrongPassword1!"},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["code"] == "INVALID_CREDENTIALS"

    async def test_login_unknown_user_returns_401(
        self, http_client
    ) -> None:
        response = await http_client.post(
            "/api/v1/auth/login",
            json={"username": "nobody", "password": "SomePassword1!"},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["code"] == "INVALID_CREDENTIALS"

    async def test_login_locked_account_returns_423(
        self, http_client, db_session, seeded_user_orm
    ) -> None:
        from datetime import datetime, timedelta
        # Lock the account by setting locked_until to the future
        future = datetime.utcnow() + timedelta(minutes=10)
        seeded_user_orm.locked_until = future.isoformat()
        seeded_user_orm.failed_attempts = 5
        await db_session.flush()
        await db_session.commit()

        response = await http_client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": "AnyPassword1!"},
        )
        assert response.status_code == 423
        body = response.json()
        assert body["error"]["code"] == "ACCOUNT_LOCKED"

    async def test_login_response_has_error_envelope_on_failure(
        self, http_client
    ) -> None:
        response = await http_client.post(
            "/api/v1/auth/login",
            json={"username": "ghost", "password": "WrongPassword1!"},
        )
        body = response.json()
        assert "error" in body
        assert "code" in body["error"]
        assert "message" in body["error"]


class TestLogout:
    async def test_logout_valid_session_returns_204(
        self, http_client, auth_headers
    ) -> None:
        response = await http_client.post(
            "/api/v1/auth/logout",
            headers=auth_headers,
        )
        assert response.status_code == 204

    async def test_logout_without_token_returns_401(
        self, http_client
    ) -> None:
        response = await http_client.post("/api/v1/auth/logout")
        assert response.status_code == 401


class TestWhoAmI:
    async def test_whoami_valid_token_returns_200_with_user_info(
        self, http_client, auth_headers
    ) -> None:
        response = await http_client.get(
            "/api/v1/auth/whoami",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert "user_id" in body
        assert "roles" in body
        assert "scopes" in body

    async def test_whoami_no_token_returns_401(
        self, http_client
    ) -> None:
        response = await http_client.get("/api/v1/auth/whoami")
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["code"] in ("SESSION_EXPIRED", "UNAUTHENTICATED")

    async def test_whoami_invalid_token_returns_401(
        self, http_client
    ) -> None:
        response = await http_client.get(
            "/api/v1/auth/whoami",
            headers={"Authorization": "Bearer not-a-valid-token"},
        )
        assert response.status_code == 401

    async def test_whoami_after_logout_returns_401(
        self, http_client, auth_headers
    ) -> None:
        """After logging out, the token should be invalidated."""
        await http_client.post("/api/v1/auth/logout", headers=auth_headers)
        response = await http_client.get("/api/v1/auth/whoami", headers=auth_headers)
        assert response.status_code == 401
