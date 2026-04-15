"""
API tests for admin config routes (/api/v1/admin/config).
"""
from __future__ import annotations

import pytest


async def test_list_config_requires_auth(http_client):
    resp = await http_client.get("/api/v1/admin/config/")
    assert resp.status_code == 401


async def test_list_config_with_auth_returns_200(http_client, auth_headers):
    resp = await http_client.get("/api/v1/admin/config/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data


async def test_upsert_config_requires_admin_permission(http_client, librarian_headers):
    resp = await http_client.put(
        "/api/v1/admin/config/general/timeout",
        json={"value": "300", "description": "Session timeout"},
        headers=librarian_headers,
    )
    assert resp.status_code == 403


async def test_upsert_config_with_admin_creates_entry(http_client, admin_headers):
    resp = await http_client.put(
        "/api/v1/admin/config/display/page_size",
        json={"value": "25", "description": "Items per page"},
        headers=admin_headers,
    )
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["category"] == "display"
    assert data["key"] == "page_size"
    assert data["value"] == "25"


async def test_upsert_config_empty_value_returns_422(http_client, admin_headers):
    resp = await http_client.put(
        "/api/v1/admin/config/display/bad",
        json={"value": "   ", "description": ""},
        headers=admin_headers,
    )
    assert resp.status_code == 422


async def test_list_workflow_nodes_with_auth_returns_200(http_client, auth_headers):
    resp = await http_client.get("/api/v1/admin/config/workflow-nodes/", headers=auth_headers)
    assert resp.status_code == 200


async def test_delete_config_with_admin_returns_204(http_client, admin_headers):
    create_resp = await http_client.put(
        "/api/v1/admin/config/runtime/temp_key",
        json={"value": "1", "description": "temp"},
        headers=admin_headers,
    )
    assert create_resp.status_code in (200, 201)
    entry_id = create_resp.json()["entry_id"]

    delete_resp = await http_client.delete(
        f"/api/v1/admin/config/{entry_id}",
        headers=admin_headers,
    )
    assert delete_resp.status_code == 204
