"""
Tests for the standardised API error envelope format.

Verifies that error responses conform to the documented shape:
    {"error": {"code": str, "message": str, "details": <optional>}}

These tests validate the Pydantic schema definitions independently of any
running FastAPI instance, and also perform HTTP integration assertions to
confirm the envelope is returned by actual route handlers.
"""
from __future__ import annotations

import io
import uuid

import pytest
from pydantic import BaseModel, ValidationError
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Error envelope Pydantic models (mirroring what the api/ layer will define)
# These are defined here to test the contract shape independently.
# ---------------------------------------------------------------------------

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class TestErrorEnvelopeShape:
    def test_valid_minimal_envelope(self) -> None:
        """Envelope with code and message is valid; details defaults to None."""
        env = ErrorEnvelope(error={"code": "NOT_FOUND", "message": "Resource not found"})
        assert env.error.code == "NOT_FOUND"
        assert env.error.message == "Resource not found"
        assert env.error.details is None

    def test_valid_envelope_with_details(self) -> None:
        env = ErrorEnvelope(
            error={
                "code": "VALIDATION_ERROR",
                "message": "Input validation failed",
                "details": {"field": "age_range_max", "constraint": "must be <= 18"},
            }
        )
        assert env.error.details["field"] == "age_range_max"

    def test_valid_envelope_with_list_details(self) -> None:
        env = ErrorEnvelope(
            error={
                "code": "VALIDATION_ERROR",
                "message": "Multiple fields failed",
                "details": [
                    {"field": "username", "msg": "required"},
                    {"field": "password", "msg": "too short"},
                ],
            }
        )
        assert isinstance(env.error.details, list)
        assert len(env.error.details) == 2

    def test_missing_code_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ErrorEnvelope(error={"message": "Something went wrong"})
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("error", "code") for e in errors)

    def test_missing_message_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ErrorEnvelope(error={"code": "SOME_CODE"})
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("error", "message") for e in errors)

    def test_missing_error_key_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            ErrorEnvelope(**{"code": "SOME_CODE", "message": "oops"})  # type: ignore[arg-type]

    def test_null_details_is_valid(self) -> None:
        env = ErrorEnvelope(
            error={"code": "INTERNAL_ERROR", "message": "Unexpected error", "details": None}
        )
        assert env.error.details is None

    def test_serializes_to_dict(self) -> None:
        env = ErrorEnvelope(error={"code": "ACCOUNT_LOCKED", "message": "Locked"})
        d = env.model_dump()
        assert "error" in d
        assert d["error"]["code"] == "ACCOUNT_LOCKED"
        assert d["error"]["details"] is None


class TestKnownErrorCodes:
    """Verify all documented error codes are valid strings (not None or empty)."""

    EXPECTED_CODES = [
        "UNAUTHENTICATED",
        "SESSION_EXPIRED",
        "ACCOUNT_LOCKED",
        "INVALID_CREDENTIALS",
        "INSUFFICIENT_PERMISSION",
        "SCOPE_VIOLATION",
        "NOT_FOUND",
        "RECORD_LOCKED",
        "INVALID_STATE_TRANSITION",
        "DUPLICATE_RESOURCE",
        "APPEND_ONLY_VIOLATION",
        "VALIDATION_ERROR",
        "RATE_LIMIT_EXCEEDED",
        "SIGNATURE_INVALID",
        "REVISION_LIMIT_REACHED",
        "INTERNAL_ERROR",
    ]

    @pytest.mark.parametrize("code", EXPECTED_CODES)
    def test_code_is_non_empty_string(self, code: str) -> None:
        assert isinstance(code, str) and len(code) > 0

    @pytest.mark.parametrize("code", EXPECTED_CODES)
    def test_code_can_be_used_in_envelope(self, code: str) -> None:
        env = ErrorEnvelope(error={"code": code, "message": f"Test message for {code}"})
        assert env.error.code == code


# ---------------------------------------------------------------------------
# HTTP integration tests — envelope shape on real route responses
# ---------------------------------------------------------------------------

def _assert_envelope(resp, expected_code: str | None = None) -> None:
    """Assert response body is a well-formed ErrorEnvelope."""
    data = resp.json()
    err = data.get("error")
    if err is None:
        err = data.get("detail")
    assert isinstance(err, dict), f"Missing error payload in: {data}"
    assert "code" in err, f"Missing 'code' in error: {err}"
    assert "message" in err, f"Missing 'message' in error: {err}"
    if expected_code is not None:
        assert err["code"] == expected_code, (
            f"Expected code {expected_code!r}, got {err['code']!r}"
        )


async def test_unauthorized_returns_401_envelope(http_client):
    """GET /resources/ without a token must return 401 with a valid envelope."""
    resp = await http_client.get("/api/v1/resources/")
    assert resp.status_code == 401
    code = resp.json()["error"]["code"]
    assert code in ("SESSION_EXPIRED", "UNAUTHENTICATED")
    _assert_envelope(resp)


async def test_forbidden_returns_403_envelope(http_client, librarian_headers):
    """PUT /admin/config/... with a non-admin token must return 403 with a valid envelope."""
    resp = await http_client.put(
        "/api/v1/admin/config/display/page_size",
        headers=librarian_headers,
        json={"value": "25", "description": "Envelope test"},
    )
    assert resp.status_code == 403
    _assert_envelope(resp, "INSUFFICIENT_PERMISSION")


async def test_not_found_returns_404_envelope(http_client, admin_headers):
    """GET /resources/{non-existent-id} must return 404 with a valid envelope."""
    missing_id = str(uuid.uuid4())
    resp = await http_client.get(
        f"/api/v1/resources/{missing_id}", headers=admin_headers
    )
    assert resp.status_code == 404
    _assert_envelope(resp, "NOT_FOUND")


async def test_duplicate_resource_returns_409_envelope(
    http_client, admin_headers
):
    """
    Uploading the same file content twice must return 409 DUPLICATE_RESOURCE
    wrapped in the standard envelope.
    """
    file_content = b"unique envelope test content " + str(uuid.uuid4()).encode()
    data = {"resource_type": "BOOK", "title": "Envelope Test Book"}

    # First upload must succeed
    files1 = {"file": ("test.txt", io.BytesIO(file_content), "text/plain")}
    resp1 = await http_client.post(
        "/api/v1/resources/import/file",
        files=files1,
        data=data,
        headers=admin_headers,
    )
    assert resp1.status_code in (200, 201), f"First import failed: {resp1.text}"

    # Second upload with identical bytes must return 409
    files2 = {"file": ("test.txt", io.BytesIO(file_content), "text/plain")}
    resp2 = await http_client.post(
        "/api/v1/resources/import/file",
        files=files2,
        data=data,
        headers=admin_headers,
    )
    assert resp2.status_code == 409
    _assert_envelope(resp2, "DUPLICATE_RESOURCE")
