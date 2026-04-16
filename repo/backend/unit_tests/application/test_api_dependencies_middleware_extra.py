"""
Extra tests for api.dependencies and api.middleware to raise backend coverage.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
import uuid

import pytest
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from pydantic import BaseModel, ValidationError
from starlette.requests import Request

from district_console.api import dependencies as deps
from district_console.api.middleware import ErrorHandlerMiddleware, _make_error_response
from district_console.domain.exceptions import IntegrationSigningError


class _FakeRequest:
    def __init__(self, headers: dict[str, str], body: bytes = b"", key_hex: str | None = None):
        self.headers = headers
        self._body = body
        self.method = "GET"
        self.url = SimpleNamespace(path="/api/v1/integrations/inbound/status")
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                container=SimpleNamespace(
                    config=SimpleNamespace(
                        key_encryption_key=key_hex
                        or "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                    )
                )
            )
        )

    async def body(self) -> bytes:
        return self._body


def _req_with_container(container) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=container)))


@pytest.mark.asyncio
async def test_service_accessors_return_container_members():
    container = SimpleNamespace(
        auth_service=object(),
        rbac_service=object(),
        resource_service=object(),
        inventory_service=object(),
        count_session_service=object(),
        relocation_service=object(),
        config_service=object(),
        taxonomy_service=object(),
        integration_service=object(),
        update_service=object(),
        audit_service=object(),
    )
    req = _req_with_container(container)

    assert deps.get_auth_service(req) is container.auth_service
    assert deps.get_rbac_service(req) is container.rbac_service
    assert deps.get_resource_service(req) is container.resource_service
    assert deps.get_inventory_service(req) is container.inventory_service
    assert deps.get_count_session_service(req) is container.count_session_service
    assert deps.get_relocation_service(req) is container.relocation_service
    assert deps.get_config_service(req) is container.config_service
    assert deps.get_taxonomy_service(req) is container.taxonomy_service
    assert deps.get_integration_service(req) is container.integration_service
    assert deps.get_update_service(req) is container.update_service
    assert deps.get_audit_service(req) is container.audit_service


@pytest.mark.asyncio
async def test_get_current_user_with_scope_loads_scopes(monkeypatch):
    fake_scopes = [SimpleNamespace(scope_type=SimpleNamespace(value="SCHOOL"), scope_ref_id="abc")]

    async def _fake_get_user_scopes(session, user_id):
        return fake_scopes

    monkeypatch.setattr(deps.ScopeRepository, "get_user_scopes", _fake_get_user_scopes)

    uid = uuid.uuid4()
    roles = [object()]
    result = await deps.get_current_user_with_scope((uid, roles), object())

    assert result == (uid, roles, fake_scopes)


@pytest.mark.asyncio
async def test_verify_hmac_auth_invalid_client_uuid_raises():
    req = _FakeRequest(
        headers={
            "X-DC-Client-ID": "not-a-uuid",
            "X-DC-Signature": "hmac-sha256 deadbeef",
            "X-DC-Timestamp": "1700000000",
        }
    )
    with pytest.raises(IntegrationSigningError):
        await deps.verify_hmac_auth(req, object())


@pytest.mark.asyncio
async def test_verify_hmac_auth_unknown_client_raises(monkeypatch):
    client_id = str(uuid.uuid4())
    req = _FakeRequest(
        headers={
            "X-DC-Client-ID": client_id,
            "X-DC-Signature": "hmac-sha256 deadbeef",
            "X-DC-Timestamp": "1700000000",
        }
    )

    class _Repo:
        async def get_client(self, session, client_uuid):
            return None

    monkeypatch.setattr(deps, "IntegrationRepository", lambda: _Repo())

    with pytest.raises(IntegrationSigningError):
        await deps.verify_hmac_auth(req, object())


@pytest.mark.asyncio
async def test_verify_hmac_auth_expired_or_missing_keys_fails(monkeypatch):
    client_id = str(uuid.uuid4())
    req = _FakeRequest(
        headers={
            "X-DC-Client-ID": client_id,
            "X-DC-Signature": "hmac-sha256 deadbeef",
            "X-DC-Timestamp": "1700000000",
        }
    )

    class _Repo:
        async def get_client(self, session, client_uuid):
            return SimpleNamespace(is_active=True)

        async def get_active_key_for_client(self, session, client_uuid):
            return SimpleNamespace(
                expires_at=datetime.utcnow() - timedelta(days=1),
                key_encrypted="enc",
            )

        async def get_next_key_for_client(self, session, client_uuid):
            return None

    monkeypatch.setattr(deps, "IntegrationRepository", lambda: _Repo())

    with pytest.raises(IntegrationSigningError):
        await deps.verify_hmac_auth(req, object())


@pytest.mark.asyncio
async def test_verify_hmac_auth_success_calls_rate_limiter(monkeypatch):
    client_id = str(uuid.uuid4())
    req = _FakeRequest(
        headers={
            "X-DC-Client-ID": client_id,
            "X-DC-Signature": "hmac-sha256 deadbeef",
            "X-DC-Timestamp": "1700000000",
        },
        body=b"{}",
    )

    class _Repo:
        async def get_client(self, session, client_uuid):
            return SimpleNamespace(is_active=True)

        async def get_active_key_for_client(self, session, client_uuid):
            return SimpleNamespace(
                expires_at=datetime.utcnow() + timedelta(days=1),
                key_encrypted="enc",
            )

        async def get_next_key_for_client(self, session, client_uuid):
            return None

    called = {"checked": False}

    class _RateLimiter:
        def __init__(self, repo):
            pass

        async def check_and_record(self, session, cid, now):
            called["checked"] = True

    monkeypatch.setattr(deps, "IntegrationRepository", lambda: _Repo())
    monkeypatch.setattr(deps, "RateLimiter", _RateLimiter)
    monkeypatch.setattr(deps, "decrypt_hmac_key", lambda enc, master: "ab" * 32)
    monkeypatch.setattr(deps.HmacSigner, "verify", lambda self, *args, **kwargs: True)

    returned = await deps.verify_hmac_auth(req, object())
    assert returned == client_id
    assert called["checked"] is True


@pytest.mark.asyncio
async def test_verify_hmac_auth_rotates_from_active_to_next_key(monkeypatch):
    client_id = str(uuid.uuid4())
    req = _FakeRequest(
        headers={
            "X-DC-Client-ID": client_id,
            "X-DC-Signature": "hmac-sha256 deadbeef",
            "X-DC-Timestamp": "1700000000",
        },
        body=b"{}",
    )

    class _Repo:
        async def get_client(self, session, client_uuid):
            return SimpleNamespace(is_active=True)

        async def get_active_key_for_client(self, session, client_uuid):
            return SimpleNamespace(
                expires_at=datetime.utcnow() + timedelta(days=1),
                key_encrypted="active",
            )

        async def get_next_key_for_client(self, session, client_uuid):
            return SimpleNamespace(
                expires_at=datetime.utcnow() + timedelta(days=1),
                key_encrypted="next",
            )

    class _RateLimiter:
        def __init__(self, repo):
            pass

        async def check_and_record(self, session, cid, now):
            return None

    verify_results = iter([False, True])

    def _verify(self, *args, **kwargs):
        return next(verify_results)

    monkeypatch.setattr(deps, "IntegrationRepository", lambda: _Repo())
    monkeypatch.setattr(deps, "RateLimiter", _RateLimiter)
    monkeypatch.setattr(deps, "decrypt_hmac_key", lambda enc, master: "cd" * 32)
    monkeypatch.setattr(deps.HmacSigner, "verify", _verify)

    returned = await deps.verify_hmac_auth(req, object())
    assert returned == client_id


def _starlette_request() -> Request:
    async def _receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
    }
    return Request(scope, _receive)


def test_make_error_response_includes_details_when_present():
    resp = _make_error_response("VALIDATION_ERROR", "bad request", details=[{"field": "x"}])
    assert resp.status_code == 422
    assert b'"details"' in resp.body


@pytest.mark.asyncio
async def test_middleware_wraps_http_exception_with_dict_detail():
    mw = ErrorHandlerMiddleware(app=lambda scope, receive, send: None)
    req = _starlette_request()

    async def _next(_):
        raise FastAPIHTTPException(
            status_code=418,
            detail={"code": "TEAPOT", "message": "short and stout", "details": {"k": "v"}},
        )

    resp = await mw.dispatch(req, _next)
    assert resp.status_code == 418
    assert b'TEAPOT' in resp.body
    assert b'"details"' in resp.body


@pytest.mark.asyncio
async def test_middleware_wraps_http_exception_with_non_dict_detail():
    mw = ErrorHandlerMiddleware(app=lambda scope, receive, send: None)
    req = _starlette_request()

    async def _next(_):
        raise FastAPIHTTPException(status_code=400, detail="plain message")

    resp = await mw.dispatch(req, _next)
    assert resp.status_code == 400
    assert b'INTERNAL_ERROR' in resp.body


@pytest.mark.asyncio
async def test_middleware_http_exception_dict_without_details():
    mw = ErrorHandlerMiddleware(app=lambda scope, receive, send: None)
    req = _starlette_request()

    async def _next(_):
        raise FastAPIHTTPException(status_code=409, detail={"code": "CONFLICT", "message": "duplicate"})

    resp = await mw.dispatch(req, _next)
    assert resp.status_code == 409
    assert b'CONFLICT' in resp.body
    assert b'"details"' not in resp.body


@pytest.mark.asyncio
async def test_middleware_maps_validation_error_to_envelope():
    mw = ErrorHandlerMiddleware(app=lambda scope, receive, send: None)
    req = _starlette_request()

    class _Model(BaseModel):
        x: int

    async def _next(_):
        try:
            _Model(x="not-an-int")
        except ValidationError as exc:
            raise exc

    resp = await mw.dispatch(req, _next)
    assert resp.status_code == 422
    assert b'VALIDATION_ERROR' in resp.body


@pytest.mark.asyncio
async def test_middleware_maps_unhandled_exception_to_internal_error():
    mw = ErrorHandlerMiddleware(app=lambda scope, receive, send: None)
    req = _starlette_request()

    async def _next(_):
        raise RuntimeError("boom")

    resp = await mw.dispatch(req, _next)
    assert resp.status_code == 500
    assert b'INTERNAL_ERROR' in resp.body
