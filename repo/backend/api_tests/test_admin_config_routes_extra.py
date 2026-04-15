"""
Additional integration tests for /api/v1/admin/config/* (the admin config router).

Hits the workflow-node, template, and descriptor branches that the existing
test_config_routes.py does not cover.
"""
from __future__ import annotations


async def test_list_workflow_nodes_returns_200(http_client, admin_headers):
    resp = await http_client.get(
        "/api/v1/admin/config/workflow-nodes/", headers=admin_headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_workflow_node_returns_201(http_client, admin_headers):
    resp = await http_client.post(
        "/api/v1/admin/config/workflow-nodes/",
        headers=admin_headers,
        json={
            "workflow_name": "resource_review",
            "from_state": "DRAFT",
            "to_state": "IN_REVIEW",
            "required_role": "REVIEWER",
            "condition_json": None,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["workflow_name"] == "resource_review"


async def test_list_workflow_nodes_filter_by_name(http_client, admin_headers):
    # Seed one node with a known workflow_name
    await http_client.post(
        "/api/v1/admin/config/workflow-nodes/",
        headers=admin_headers,
        json={
            "workflow_name": "filter_wf",
            "from_state": "A",
            "to_state": "B",
            "required_role": "REVIEWER",
            "condition_json": None,
        },
    )
    resp = await http_client.get(
        "/api/v1/admin/config/workflow-nodes/",
        headers=admin_headers,
        params={"workflow_name": "filter_wf"},
    )
    assert resp.status_code == 200
    names = {n["workflow_name"] for n in resp.json()}
    assert names == {"filter_wf"}


async def test_delete_workflow_node_returns_204(http_client, admin_headers):
    created = await http_client.post(
        "/api/v1/admin/config/workflow-nodes/",
        headers=admin_headers,
        json={
            "workflow_name": "wf_to_delete",
            "from_state": "X",
            "to_state": "Y",
            "required_role": "ADMINISTRATOR",
            "condition_json": None,
        },
    )
    node_id = created.json()["node_id"]

    deleted = await http_client.delete(
        f"/api/v1/admin/config/workflow-nodes/{node_id}",
        headers=admin_headers,
    )
    assert deleted.status_code == 204


async def test_list_templates_returns_200(http_client, admin_headers):
    resp = await http_client.get(
        "/api/v1/admin/config/templates/", headers=admin_headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_list_descriptors_returns_200(http_client, admin_headers):
    resp = await http_client.get(
        "/api/v1/admin/config/descriptors/", headers=admin_headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_upsert_template_with_admin_returns_200(http_client, admin_headers):
    resp = await http_client.put(
        "/api/v1/admin/config/templates/welcome_email",
        headers=admin_headers,
        json={
            "name": "welcome_email",
            "event_type": "user.created",
            "subject_template": "Welcome, {{name}}!",
            "body_template": "Hello {{name}}, your account is ready.",
            "is_active": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "welcome_email"
    assert body["event_type"] == "user.created"
    assert body["is_active"] is True


async def test_upsert_template_requires_admin_permission(http_client, librarian_headers):
    resp = await http_client.put(
        "/api/v1/admin/config/templates/blocked_template",
        headers=librarian_headers,
        json={
            "name": "blocked_template",
            "event_type": "test.event",
            "subject_template": "Subject",
            "body_template": "Body",
            "is_active": False,
        },
    )
    assert resp.status_code == 403


async def test_upsert_descriptor_with_admin_returns_200(http_client, admin_headers):
    resp = await http_client.put(
        "/api/v1/admin/config/descriptors/school_name",
        headers=admin_headers,
        json={
            "value": "Springfield Elementary",
            "description": "Official school name",
            "region": "district-1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "school_name"
    assert body["value"] == "Springfield Elementary"
    assert body["region"] == "district-1"


async def test_upsert_descriptor_requires_admin_permission(http_client, librarian_headers):
    resp = await http_client.put(
        "/api/v1/admin/config/descriptors/blocked_key",
        headers=librarian_headers,
        json={"value": "denied", "description": "", "region": None},
    )
    assert resp.status_code == 403
