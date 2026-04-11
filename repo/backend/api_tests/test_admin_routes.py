"""
API tests for admin audit routes (/api/v1/admin/audit)
and taxonomy routes (/api/v1/admin/taxonomy).
"""
from __future__ import annotations

import pytest


# ------------------------------------------------------------------
# Audit routes
# ------------------------------------------------------------------

async def test_list_audit_events_requires_auth(http_client):
    resp = await http_client.get("/api/v1/admin/audit/events/")
    assert resp.status_code == 401


async def test_list_audit_events_without_admin_returns_403(http_client, librarian_headers):
    resp = await http_client.get("/api/v1/admin/audit/events/", headers=librarian_headers)
    assert resp.status_code == 403


async def test_list_audit_events_with_admin_returns_200(http_client, admin_headers):
    resp = await http_client.get("/api/v1/admin/audit/events/", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data


async def test_list_security_events_with_admin_returns_200(http_client, admin_headers):
    resp = await http_client.get("/api/v1/admin/audit/events/security/", headers=admin_headers)
    assert resp.status_code == 200


async def test_list_checkpoints_with_admin_returns_200(http_client, admin_headers):
    resp = await http_client.get("/api/v1/admin/audit/checkpoints/", headers=admin_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ------------------------------------------------------------------
# Taxonomy routes
# ------------------------------------------------------------------

async def test_list_categories_requires_auth(http_client):
    resp = await http_client.get("/api/v1/admin/taxonomy/categories/")
    assert resp.status_code == 401


async def test_list_categories_with_auth_returns_200(http_client, auth_headers):
    resp = await http_client.get("/api/v1/admin/taxonomy/categories/", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_category_requires_admin(http_client, librarian_headers):
    resp = await http_client.post(
        "/api/v1/admin/taxonomy/categories/",
        json={"name": "Fiction"},
        headers=librarian_headers,
    )
    assert resp.status_code == 403


async def test_create_category_with_admin_returns_201(http_client, admin_headers):
    resp = await http_client.post(
        "/api/v1/admin/taxonomy/categories/",
        json={"name": "Science"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Science"
    assert data["depth"] == 0
    assert data["path_slug"] == "science"


# ------------------------------------------------------------------
# Taxonomy category extended operations
# ------------------------------------------------------------------

async def test_update_category_with_admin_returns_200(http_client, admin_headers):
    """PUT /categories/{id} renames the category and recomputes path_slug."""
    create_resp = await http_client.post(
        "/api/v1/admin/taxonomy/categories/",
        json={"name": "OldName"},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    category_id = create_resp.json()["category_id"]

    update_resp = await http_client.put(
        f"/api/v1/admin/taxonomy/categories/{category_id}",
        json={"name": "NewName"},
        headers=admin_headers,
    )
    assert update_resp.status_code == 200
    data = update_resp.json()
    assert data["name"] == "NewName"
    assert data["path_slug"] == "newname"


async def test_update_category_requires_admin(http_client, librarian_headers, admin_headers):
    create_resp = await http_client.post(
        "/api/v1/admin/taxonomy/categories/",
        json={"name": "ToUpdate"},
        headers=admin_headers,
    )
    category_id = create_resp.json()["category_id"]
    resp = await http_client.put(
        f"/api/v1/admin/taxonomy/categories/{category_id}",
        json={"name": "Denied"},
        headers=librarian_headers,
    )
    assert resp.status_code == 403


async def test_deactivate_category_with_admin_returns_204(http_client, admin_headers):
    """DELETE /categories/{id} soft-deletes the category (is_active=False)."""
    create_resp = await http_client.post(
        "/api/v1/admin/taxonomy/categories/",
        json={"name": "ToDelete"},
        headers=admin_headers,
    )
    category_id = create_resp.json()["category_id"]

    delete_resp = await http_client.delete(
        f"/api/v1/admin/taxonomy/categories/{category_id}",
        headers=admin_headers,
    )
    assert delete_resp.status_code == 204


async def test_deactivate_category_requires_admin(http_client, librarian_headers, admin_headers):
    create_resp = await http_client.post(
        "/api/v1/admin/taxonomy/categories/",
        json={"name": "Protected"},
        headers=admin_headers,
    )
    category_id = create_resp.json()["category_id"]
    resp = await http_client.delete(
        f"/api/v1/admin/taxonomy/categories/{category_id}",
        headers=librarian_headers,
    )
    assert resp.status_code == 403


async def test_create_child_category_increments_depth(http_client, admin_headers):
    """Child categories have depth = parent.depth + 1."""
    parent_resp = await http_client.post(
        "/api/v1/admin/taxonomy/categories/",
        json={"name": "Parent"},
        headers=admin_headers,
    )
    parent_id = parent_resp.json()["category_id"]

    child_resp = await http_client.post(
        "/api/v1/admin/taxonomy/categories/",
        json={"name": "Child", "parent_id": parent_id},
        headers=admin_headers,
    )
    assert child_resp.status_code == 201
    assert child_resp.json()["depth"] == 1
    assert child_resp.json()["parent_id"] == parent_id


async def test_list_categories_flat_returns_all(http_client, admin_headers):
    """?flat=true returns all categories regardless of parent."""
    await http_client.post(
        "/api/v1/admin/taxonomy/categories/",
        json={"name": "FlatA"},
        headers=admin_headers,
    )
    await http_client.post(
        "/api/v1/admin/taxonomy/categories/",
        json={"name": "FlatB"},
        headers=admin_headers,
    )
    resp = await http_client.get(
        "/api/v1/admin/taxonomy/categories/?flat=true",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert "FlatA" in names
    assert "FlatB" in names


# ------------------------------------------------------------------
# Taxonomy validation rules
# ------------------------------------------------------------------

async def test_list_taxonomy_rules_with_auth_returns_200(http_client, auth_headers):
    resp = await http_client.get(
        "/api/v1/admin/taxonomy/rules/",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_taxonomy_rule_with_admin_returns_201(http_client, admin_headers):
    resp = await http_client.post(
        "/api/v1/admin/taxonomy/rules/",
        json={
            "field": "isbn",
            "rule_type": "regex",
            "rule_value": r"^\d{13}$",
            "description": "ISBN-13 format",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["field"] == "isbn"
    assert data["rule_type"] == "regex"


async def test_create_taxonomy_rule_requires_admin(http_client, librarian_headers):
    resp = await http_client.post(
        "/api/v1/admin/taxonomy/rules/",
        json={"field": "isbn", "rule_type": "regex", "rule_value": r".*"},
        headers=librarian_headers,
    )
    assert resp.status_code == 403


async def test_delete_taxonomy_rule_with_admin_returns_204(http_client, admin_headers):
    create_resp = await http_client.post(
        "/api/v1/admin/taxonomy/rules/",
        json={"field": "title", "rule_type": "max_length", "rule_value": "200"},
        headers=admin_headers,
    )
    rule_id = create_resp.json()["rule_id"]

    delete_resp = await http_client.delete(
        f"/api/v1/admin/taxonomy/rules/{rule_id}",
        headers=admin_headers,
    )
    assert delete_resp.status_code == 204
