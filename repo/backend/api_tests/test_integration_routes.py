"""
API tests for integration client routes (/api/v1/integrations).
"""
from __future__ import annotations

import pytest


async def test_list_clients_requires_auth(http_client):
    resp = await http_client.get("/api/v1/integrations/")
    assert resp.status_code == 401


async def test_list_clients_with_auth_returns_200(http_client, admin_headers):
    resp = await http_client.get("/api/v1/integrations/", headers=admin_headers)
    assert resp.status_code == 200


async def test_list_clients_non_admin_returns_403(http_client, librarian_headers):
    resp = await http_client.get("/api/v1/integrations/", headers=librarian_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSION"


async def test_create_client_requires_admin_permission(http_client, librarian_headers):
    resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "Test Client", "description": ""},
        headers=librarian_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSION"


async def test_create_client_with_admin_returns_201(http_client, admin_headers):
    resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "ERP Integration", "description": "ERP sync"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["client"]["name"] == "ERP Integration"
    assert "initial_key" in data
    assert len(data["initial_key"]["key_value"]) == 64


async def test_rotate_key_requires_admin(http_client, librarian_headers, admin_headers):
    # Create client as admin
    create_resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "KeyRotTest", "description": ""},
        headers=admin_headers,
    )
    client_id = create_resp.json()["client"]["client_id"]

    # Rotate as librarian — should be denied
    resp = await http_client.post(
        f"/api/v1/integrations/{client_id}/rotate-key",
        headers=librarian_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSION"


async def test_rotate_and_commit_key_succeeds_as_admin(http_client, admin_headers):
    create_resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "RotateCommit", "description": ""},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    client_id = create_resp.json()["client"]["client_id"]

    rotate_resp = await http_client.post(
        f"/api/v1/integrations/{client_id}/rotate-key", headers=admin_headers
    )
    assert rotate_resp.status_code == 200

    commit_resp = await http_client.post(
        f"/api/v1/integrations/{client_id}/commit-rotation", headers=admin_headers
    )
    assert commit_resp.status_code == 200


async def test_list_outbound_events_returns_paginated(http_client, admin_headers):
    resp = await http_client.get("/api/v1/integrations/events/", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data


async def test_emit_event_with_admin_returns_201(http_client, admin_headers):
    create_resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "Emitter", "description": ""},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    client_id = create_resp.json()["client"]["client_id"]

    emit_resp = await http_client.post(
        f"/api/v1/integrations/events/{client_id}/emit",
        headers=admin_headers,
        json={"event_type": "resource.imported", "payload": {"resource_id": "abc"}},
    )
    assert emit_resp.status_code == 201
    data = emit_resp.json()
    assert data["client_id"] == client_id
    assert data["event_type"] == "resource.imported"
    assert data["status"] in ("PENDING", "DELIVERED")


async def test_emit_event_requires_admin_permission(http_client, librarian_headers, admin_headers):
    create_resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "EmitterProtected", "description": ""},
        headers=admin_headers,
    )
    client_id = create_resp.json()["client"]["client_id"]

    resp = await http_client.post(
        f"/api/v1/integrations/events/{client_id}/emit",
        headers=librarian_headers,
        json={"event_type": "resource.imported", "payload": {"resource_id": "abc"}},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSION"


async def test_deactivate_client_with_admin_returns_204(http_client, admin_headers):
    """DELETE /integrations/{id} soft-deactivates the integration client."""
    create_resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "DeactivateMe", "description": ""},
        headers=admin_headers,
    )
    client_id = create_resp.json()["client"]["client_id"]

    delete_resp = await http_client.delete(
        f"/api/v1/integrations/{client_id}",
        headers=admin_headers,
    )
    assert delete_resp.status_code == 204


async def test_deactivate_client_requires_admin(http_client, librarian_headers, admin_headers):
    create_resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "Protected", "description": ""},
        headers=admin_headers,
    )
    client_id = create_resp.json()["client"]["client_id"]
    resp = await http_client.delete(
        f"/api/v1/integrations/{client_id}",
        headers=librarian_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSION"


async def test_retry_events_returns_result(http_client, admin_headers):
    """POST /integrations/events/retry processes pending events (returns a dict)."""
    resp = await http_client.post(
        "/api/v1/integrations/events/retry",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


async def test_list_events_requires_admin_permission(http_client, librarian_headers):
    """GET /integrations/events/ requires admin.manage_config."""
    resp = await http_client.get(
        "/api/v1/integrations/events/",
        headers=librarian_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSION"


async def test_create_client_empty_name_returns_422(http_client, admin_headers):
    """Empty name must fail Pydantic validation."""
    resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "", "description": ""},
        headers=admin_headers,
    )
    assert resp.status_code in (400, 422)


async def test_rotate_key_response_has_expected_fields(http_client, admin_headers):
    """Rotated key response includes key_id, key_value, is_next=True."""
    create_resp = await http_client.post(
        "/api/v1/integrations/",
        json={"name": "FieldCheck", "description": ""},
        headers=admin_headers,
    )
    client_id = create_resp.json()["client"]["client_id"]

    rotate_resp = await http_client.post(
        f"/api/v1/integrations/{client_id}/rotate-key",
        headers=admin_headers,
    )
    assert rotate_resp.status_code == 200
    data = rotate_resp.json()
    assert "key_id" in data
    assert "key_value" in data
    assert data["is_next"] is True
    assert data["is_active"] is False
