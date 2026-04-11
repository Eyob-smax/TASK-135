"""
API tests for HMAC-authenticated inbound integration endpoint.

Routes under test: GET /api/v1/integrations/inbound/status
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from district_console.infrastructure.hmac_signer import HmacSigner
from district_console.infrastructure.orm import HmacKeyORM


def _make_hmac_headers(
    client_id: str,
    key_hex: str,
    method: str = "GET",
    path: str = "/api/v1/integrations/inbound/status",
    body: bytes = b"",
    timestamp: str | None = None,
) -> dict:
    """Build X-DC-* headers for a signed request."""
    signer = HmacSigner()
    key_bytes = HmacSigner.key_from_hex(key_hex)
    ts = timestamp if timestamp is not None else str(int(time.time()))
    sig = signer.sign(key_bytes, method, path, ts, body)
    return {
        "X-DC-Client-ID": client_id,
        "X-DC-Timestamp": ts,
        "X-DC-Signature": f"hmac-sha256 {sig}",
    }


async def test_status_without_hmac_headers_returns_401(http_client):
    """Requests missing X-DC-* headers must be rejected with 401."""
    resp = await http_client.get("/api/v1/integrations/inbound/status")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "SIGNATURE_INVALID"


async def test_status_with_invalid_signature_returns_401(http_client, admin_headers):
    """A well-formed but wrong signature must be rejected with 401."""
    # Create a client to get a valid client_id
    create_resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "HmacTest-Bad-Sig", "description": ""},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    client_id = create_resp.json()["client"]["client_id"]

    resp = await http_client.get(
        "/api/v1/integrations/inbound/status",
        headers={
            "X-DC-Client-ID": client_id,
            "X-DC-Timestamp": str(int(time.time())),
            "X-DC-Signature": "hmac-sha256 " + "aa" * 32,  # wrong hex sig
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "SIGNATURE_INVALID"


async def test_status_with_valid_hmac_returns_200(http_client, admin_headers):
    """A correctly signed request returns 200 with status=ok and the client_id."""
    create_resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "HmacTest-Valid", "description": ""},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    data = create_resp.json()
    client_id = data["client"]["client_id"]
    key_hex = data["initial_key"]["key_value"]

    headers = _make_hmac_headers(client_id, key_hex)
    resp = await http_client.get(
        "/api/v1/integrations/inbound/status", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["client_id"] == client_id


async def test_status_rate_limit_exceeded_returns_429(http_client, admin_headers):
    """Exceeding 60 requests per minute must return 429 RATE_LIMIT_EXCEEDED."""
    create_resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "HmacTest-RateLimit", "description": ""},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    data = create_resp.json()
    client_id = data["client"]["client_id"]
    key_hex = data["initial_key"]["key_value"]

    # Send 61 requests; all with the same timestamp to hit the fixed-window counter
    ts = str(int(time.time()))
    last_resp = None
    for _ in range(61):
        headers = _make_hmac_headers(client_id, key_hex, timestamp=ts)
        last_resp = await http_client.get(
            "/api/v1/integrations/inbound/status", headers=headers
        )
        if last_resp.status_code == 429:
            break

    assert last_resp is not None
    assert last_resp.status_code == 429
    assert last_resp.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


async def test_status_with_expired_active_key_returns_401(
    http_client,
    admin_headers,
    db_session,
):
    create_resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "HmacTest-Expired-Key", "description": ""},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    data = create_resp.json()
    client_id = data["client"]["client_id"]
    key_hex = data["initial_key"]["key_value"]

    key_result = await db_session.execute(
        select(HmacKeyORM).where(
            HmacKeyORM.client_id == client_id,
            HmacKeyORM.is_active == True,  # noqa: E712
            HmacKeyORM.is_next == False,  # noqa: E712
        )
    )
    active_key = key_result.scalar_one_or_none()
    assert active_key is not None
    active_key.expires_at = (datetime.utcnow() - timedelta(days=1)).isoformat()
    await db_session.commit()

    headers = _make_hmac_headers(client_id, key_hex)
    resp = await http_client.get("/api/v1/integrations/inbound/status", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "SIGNATURE_INVALID"


async def test_status_with_non_numeric_timestamp_returns_401(http_client, admin_headers):
    """A non-numeric X-DC-Timestamp value must be rejected with 401 SIGNATURE_INVALID."""
    create_resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "HmacTest-NaN-Ts", "description": ""},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    data = create_resp.json()
    client_id = data["client"]["client_id"]
    key_hex = data["initial_key"]["key_value"]

    headers = _make_hmac_headers(client_id, key_hex, timestamp="not-a-number")
    resp = await http_client.get("/api/v1/integrations/inbound/status", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "SIGNATURE_INVALID"


async def test_status_with_stale_timestamp_returns_401(http_client, admin_headers):
    """A timestamp more than 300 s in the past must be rejected with 401 SIGNATURE_INVALID."""
    create_resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "HmacTest-Stale-Ts", "description": ""},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    data = create_resp.json()
    client_id = data["client"]["client_id"]
    key_hex = data["initial_key"]["key_value"]

    stale_ts = str(int(time.time()) - 600)  # 600 s ago — beyond the 300 s replay window
    headers = _make_hmac_headers(client_id, key_hex, timestamp=stale_ts)
    resp = await http_client.get("/api/v1/integrations/inbound/status", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "SIGNATURE_INVALID"
