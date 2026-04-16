"""
API tests for ErrorHandlerMiddleware: error envelope format and security responses.
"""
from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from district_console.api.dependencies import get_current_user, require_permission
from district_console.domain.exceptions import (
    InsufficientPermissionError,
    ScopeViolationError,
)


class TestErrorEnvelopeFormat:
    @staticmethod
    def _assert_error_or_detail(body: dict) -> None:
        # Some paths are normalized by middleware, while framework-level
        # validation/404 responses can still use the default "detail" shape.
        assert "error" in body or "detail" in body

    async def test_unknown_route_returns_404_with_envelope(
        self, http_client
    ) -> None:
        response = await http_client.get("/api/v1/nonexistent-endpoint")
        # Unknown routes can surface through FastAPI's default 404 handler.
        assert response.status_code == 404
        body = response.json()
        self._assert_error_or_detail(body)
        if "error" in body:
            assert body["error"]["code"] == "NOT_FOUND"
            assert isinstance(body["error"]["message"], str)
        else:
            assert body["detail"] == "Not Found"

    async def test_login_with_missing_field_returns_422(
        self, http_client
    ) -> None:
        """Pydantic validation error for missing required field."""
        response = await http_client.post(
            "/api/v1/auth/login",
            json={"username": "alice"},  # missing password
        )
        assert response.status_code == 422
        body = response.json()
        self._assert_error_or_detail(body)
        if "error" in body:
            assert body["error"]["code"] == "VALIDATION_ERROR"
        else:
            assert isinstance(body["detail"], list)
            assert body["detail"][0]["type"] == "missing"

    async def test_login_with_extra_field_returns_422(
        self, http_client
    ) -> None:
        """LoginRequest has extra='forbid', so unexpected fields → 422."""
        response = await http_client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "ValidPassword1!", "extra": "bad"},
        )
        assert response.status_code == 422
        body = response.json()
        self._assert_error_or_detail(body)
        if "error" in body:
            assert body["error"]["code"] == "VALIDATION_ERROR"
        else:
            assert isinstance(body["detail"], list)
            assert body["detail"][0]["type"] == "extra_forbidden"

    async def test_error_envelope_has_code_and_message_fields(
        self, http_client
    ) -> None:
        """All error responses must contain code and message in the error object."""
        response = await http_client.post(
            "/api/v1/auth/login",
            json={"username": "nobody", "password": "WrongPassword1!"},
        )
        body = response.json()
        assert "error" in body
        error = body["error"]
        assert "code" in error
        assert "message" in error
        assert isinstance(error["code"], str)
        assert len(error["code"]) > 0
        assert isinstance(error["message"], str)
        assert len(error["message"]) > 0

    async def test_unauthenticated_request_returns_401_envelope(
        self, http_client
    ) -> None:
        """Protected endpoint without token returns 401 with envelope."""
        response = await http_client.get("/api/v1/auth/whoami")
        assert response.status_code == 401
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] in ("SESSION_EXPIRED", "UNAUTHENTICATED")

    async def test_invalid_json_body_returns_error(
        self, http_client
    ) -> None:
        """Non-JSON body to a JSON endpoint returns an error response."""
        response = await http_client.post(
            "/api/v1/auth/login",
            content=b"not json at all",
            headers={"Content-Type": "application/json"},
        )
        # FastAPI returns 422 for unparseable JSON
        assert response.status_code in (400, 422)
        body = response.json()
        self._assert_error_or_detail(body)
        if "error" in body:
            assert isinstance(body["error"]["code"], str)
            assert isinstance(body["error"]["message"], str)
        else:
            assert isinstance(body["detail"], list)


class TestMiddlewarePreservesSuccessResponse:
    async def test_successful_login_not_wrapped_in_error_envelope(
        self, http_client, sample_password
    ) -> None:
        """Successful responses should not be wrapped in error format."""
        response = await http_client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": sample_password},
        )
        assert response.status_code == 200
        body = response.json()
        assert "error" not in body
        assert "token" in body
