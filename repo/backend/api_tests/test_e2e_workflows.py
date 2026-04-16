"""
Cross-feature API workflow tests that exercise end-to-end behavior through
real FastAPI request handling and database persistence.

These tests intentionally avoid mocking the transport or service layer.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select

from district_console.infrastructure.orm import LocationORM, ResourceORM, UserORM


async def _user_id_by_username(db_session, username: str) -> str:
    result = await db_session.execute(
        select(UserORM.id).where(UserORM.username == username)
    )
    user_id = result.scalar_one_or_none()
    assert user_id is not None, f"Expected seeded user '{username}' to exist"
    return user_id


async def test_resource_lifecycle_workflow_persists_across_routes(
    http_client,
    db_session,
    librarian_headers,
    admin_headers,
    reviewer_headers,
):
    """
    Validate DRAFT -> IN_REVIEW -> PUBLISHED -> UNPUBLISHED across real routes
    and verify persistence via list/detail/revisions reads.
    """
    create_resp = await http_client.post(
        "/api/v1/resources/",
        headers=librarian_headers,
        json={"title": "Workflow Resource", "resource_type": "BOOK"},
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    resource_id = created["resource_id"]
    assert created["status"] == "DRAFT"

    reviewer_id = await _user_id_by_username(db_session, "reviewer_user")
    submit_resp = await http_client.post(
        f"/api/v1/resources/{resource_id}/submit-review",
        headers=admin_headers,
        json={"reviewer_id": reviewer_id},
    )
    assert submit_resp.status_code == 200
    assert submit_resp.json()["status"] == "IN_REVIEW"

    publish_resp = await http_client.post(
        f"/api/v1/resources/{resource_id}/publish",
        headers=admin_headers,
        json={"reviewer_notes": "Validated end-to-end"},
    )
    assert publish_resp.status_code == 200
    assert publish_resp.json()["status"] == "PUBLISHED"

    detail_resp = await http_client.get(
        f"/api/v1/resources/{resource_id}",
        headers=admin_headers,
    )
    assert detail_resp.status_code == 200
    assert detail_resp.json()["resource_id"] == resource_id
    assert detail_resp.json()["status"] == "PUBLISHED"

    revisions_resp = await http_client.get(
        f"/api/v1/resources/{resource_id}/revisions",
        headers=admin_headers,
    )
    assert revisions_resp.status_code == 200
    revisions = revisions_resp.json()
    assert len(revisions) >= 1
    assert revisions[0]["revision_number"] == 1

    unpublish_resp = await http_client.post(
        f"/api/v1/resources/{resource_id}/unpublish",
        headers=admin_headers,
        json={"reviewer_notes": "Retired"},
    )
    assert unpublish_resp.status_code == 200
    assert unpublish_resp.json()["status"] == "UNPUBLISHED"

    # Verify persistence directly in DB to confirm workflow state was committed.
    query = await db_session.execute(
        select(ResourceORM.status).where(ResourceORM.id == resource_id)
    )
    assert query.scalar_one() == "UNPUBLISHED"


async def test_inventory_count_and_relocation_workflow_updates_balances(
    http_client,
    db_session,
    admin_headers,
    seeded_warehouse,
    seeded_location,
):
    """
    Validate inventory flow through API boundaries:
      create item -> adjust stock -> count session close/approve -> relocate.
    """
    sku = f"WF-{uuid.uuid4().hex[:8].upper()}"
    create_item_resp = await http_client.post(
        "/api/v1/inventory/items/",
        headers=admin_headers,
        json={
            "sku": sku,
            "name": "Workflow Item",
            "description": "End-to-end inventory workflow",
            "unit_cost": "12.50",
        },
    )
    assert create_item_resp.status_code == 201
    item_id = create_item_resp.json()["item_id"]

    adjust_resp = await http_client.post(
        "/api/v1/inventory/ledger/adjustment",
        headers=admin_headers,
        json={
            "item_id": item_id,
            "location_id": seeded_location.id,
            "quantity_delta": 25,
            "reason_code": "RECEIPT",
        },
    )
    assert adjust_resp.status_code == 201
    assert adjust_resp.json()["quantity_after"] == 25

    open_count_resp = await http_client.post(
        "/api/v1/inventory/count-sessions/",
        headers=admin_headers,
        json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
    )
    assert open_count_resp.status_code == 201
    session_id = open_count_resp.json()["session_id"]

    add_line_resp = await http_client.post(
        f"/api/v1/inventory/count-sessions/{session_id}/line",
        headers=admin_headers,
        json={
            "item_id": item_id,
            "location_id": seeded_location.id,
            "counted_qty": 22,
            "reason_code": "PHYSICAL_COUNT",
        },
    )
    assert add_line_resp.status_code == 201
    count_line = add_line_resp.json()
    assert count_line["expected_qty"] == 25
    assert count_line["variance_qty"] == -3

    close_resp = await http_client.post(
        f"/api/v1/inventory/count-sessions/{session_id}/close",
        headers=admin_headers,
    )
    assert close_resp.status_code == 200
    assert close_resp.json()["status"] == "CLOSED"

    approve_resp = await http_client.post(
        f"/api/v1/inventory/count-sessions/{session_id}/approve",
        headers=admin_headers,
        json={"notes": "Approved after review"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "APPROVED"

    destination = LocationORM(
        id=str(uuid.uuid4()),
        warehouse_id=seeded_warehouse.id,
        zone="WF",
        aisle="01",
        bin_label="WF-01-01",
        is_active=True,
    )
    db_session.add(destination)
    await db_session.flush()

    relocate_resp = await http_client.post(
        "/api/v1/inventory/relocations/",
        headers=admin_headers,
        json={
            "item_id": item_id,
            "from_location_id": seeded_location.id,
            "to_location_id": destination.id,
            "quantity": 4,
            "device_source": "MANUAL",
        },
    )
    assert relocate_resp.status_code == 201
    relocation = relocate_resp.json()
    assert relocation["item_id"] == item_id
    assert relocation["from_location_id"] == seeded_location.id
    assert relocation["to_location_id"] == destination.id
    assert relocation["quantity"] == 4


async def test_config_template_descriptor_workflow(http_client, admin_headers, auth_headers):
    """
    Full config-centre workflow:
      1. Upsert a generic config entry
      2. Upsert a notification template (exercises the now-fixed PUT /templates/{name} route)
      3. Upsert a district descriptor (exercises PUT /descriptors/{key})
      4. Verify all three are visible in the respective list endpoints
      5. Delete the config entry and confirm 204
    """
    # 1. Create a config entry
    cfg_resp = await http_client.put(
        "/api/v1/admin/config/e2e/workflow_setting",
        json={"value": "enabled", "description": "E2E workflow test"},
        headers=admin_headers,
    )
    assert cfg_resp.status_code == 200
    entry_id = cfg_resp.json()["entry_id"]
    assert cfg_resp.json()["value"] == "enabled"

    # 2. Upsert a notification template
    tmpl_resp = await http_client.put(
        "/api/v1/admin/config/templates/e2e_notify",
        json={
            "name": "e2e_notify",
            "event_type": "workflow.complete",
            "subject_template": "Workflow done",
            "body_template": "Your workflow completed at {{time}}.",
            "is_active": True,
        },
        headers=admin_headers,
    )
    assert tmpl_resp.status_code == 200
    assert tmpl_resp.json()["event_type"] == "workflow.complete"

    # 3. Upsert a district descriptor
    desc_resp = await http_client.put(
        "/api/v1/admin/config/descriptors/e2e_district",
        json={"value": "E2E District", "description": "End-to-end district", "region": "west"},
        headers=admin_headers,
    )
    assert desc_resp.status_code == 200
    assert desc_resp.json()["value"] == "E2E District"
    assert desc_resp.json()["region"] == "west"

    # 4. Verify persistence in list endpoints
    cfg_list = await http_client.get("/api/v1/admin/config/", headers=auth_headers)
    entry_ids = [c["entry_id"] for c in cfg_list.json()["items"]]
    assert entry_id in entry_ids

    tmpl_list = await http_client.get("/api/v1/admin/config/templates/", headers=auth_headers)
    tmpl_names = [t["name"] for t in tmpl_list.json()]
    assert "e2e_notify" in tmpl_names

    desc_list = await http_client.get("/api/v1/admin/config/descriptors/", headers=auth_headers)
    desc_keys = [d["key"] for d in desc_list.json()]
    assert "e2e_district" in desc_keys

    # 5. Delete the config entry
    del_resp = await http_client.delete(
        f"/api/v1/admin/config/{entry_id}",
        headers=admin_headers,
    )
    assert del_resp.status_code == 204

    # Confirm entry is gone from list
    cfg_list2 = await http_client.get("/api/v1/admin/config/", headers=auth_headers)
    entry_ids2 = [c["entry_id"] for c in cfg_list2.json()["items"]]
    assert entry_id not in entry_ids2
