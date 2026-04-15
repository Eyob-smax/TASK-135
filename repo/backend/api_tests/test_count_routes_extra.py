"""
Additional integration tests for /api/v1/inventory/count-sessions/ error branches.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select

from district_console.infrastructure.orm import PermissionORM, RolePermissionORM


async def test_get_count_session_not_found_returns_404(http_client, admin_headers):
    resp = await http_client.get(
        f"/api/v1/inventory/count-sessions/{uuid.uuid4()}",
        headers=admin_headers,
    )
    assert resp.status_code == 404


async def test_get_count_session_success(
    http_client, admin_headers, seeded_warehouse
):
    open_resp = await http_client.post(
        "/api/v1/inventory/count-sessions/",
        headers=admin_headers,
        json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
    )
    session_id = open_resp.json()["session_id"]
    resp = await http_client.get(
        f"/api/v1/inventory/count-sessions/{session_id}",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == session_id
    assert body["status"] == "ACTIVE"
    assert body["lines"] == []


async def test_add_count_line_unknown_session_returns_400(
    http_client, admin_headers, seeded_inventory_item, seeded_location
):
    resp = await http_client.post(
        f"/api/v1/inventory/count-sessions/{uuid.uuid4()}/line",
        headers=admin_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "location_id": seeded_location.id,
            "counted_qty": 10,
            "reason_code": "PHYSICAL_COUNT",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "VALIDATION_ERROR"


async def test_update_count_line_unknown_session_returns_400(
    http_client, admin_headers
):
    resp = await http_client.put(
        f"/api/v1/inventory/count-sessions/{uuid.uuid4()}/lines/{uuid.uuid4()}",
        headers=admin_headers,
        json={"counted_qty": 5},
    )
    assert resp.status_code == 400


async def test_update_count_line_success(
    http_client,
    admin_headers,
    seeded_warehouse,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
):
    open_resp = await http_client.post(
        "/api/v1/inventory/count-sessions/",
        headers=admin_headers,
        json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
    )
    session_id = open_resp.json()["session_id"]
    line_resp = await http_client.post(
        f"/api/v1/inventory/count-sessions/{session_id}/line",
        headers=admin_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "location_id": seeded_location.id,
            "counted_qty": 95,
            "reason_code": "PHYSICAL_COUNT",
        },
    )
    line_id = line_resp.json()["line_id"]

    upd = await http_client.put(
        f"/api/v1/inventory/count-sessions/{session_id}/lines/{line_id}",
        headers=admin_headers,
        json={"counted_qty": 97},
    )
    assert upd.status_code == 200
    assert upd.json()["counted_qty"] == 97


async def test_close_count_session_not_found_returns_400(http_client, admin_headers):
    resp = await http_client.post(
        f"/api/v1/inventory/count-sessions/{uuid.uuid4()}/close",
        headers=admin_headers,
    )
    assert resp.status_code == 400


async def test_approve_count_session_not_found_returns_400(http_client, admin_headers):
    resp = await http_client.post(
        f"/api/v1/inventory/count-sessions/{uuid.uuid4()}/approve",
        headers=admin_headers,
        json={"notes": "ok"},
    )
    assert resp.status_code == 400


async def test_approve_count_session_active_returns_400(
    http_client, admin_headers, seeded_warehouse
):
    open_resp = await http_client.post(
        "/api/v1/inventory/count-sessions/",
        headers=admin_headers,
        json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
    )
    session_id = open_resp.json()["session_id"]
    # Still ACTIVE → approval should fail
    resp = await http_client.post(
        f"/api/v1/inventory/count-sessions/{session_id}/approve",
        headers=admin_headers,
        json={"notes": "nope"},
    )
    assert resp.status_code == 400


async def test_list_count_sessions_filters_by_status(
    http_client, admin_headers, seeded_warehouse
):
    await http_client.post(
        "/api/v1/inventory/count-sessions/",
        headers=admin_headers,
        json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
    )
    resp = await http_client.get(
        "/api/v1/inventory/count-sessions/",
        headers=admin_headers,
        params={"status": "ACTIVE"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1


async def test_blind_mode_hides_expected_qty(
    http_client,
    admin_headers,
    seeded_warehouse,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
):
    open_resp = await http_client.post(
        "/api/v1/inventory/count-sessions/",
        headers=admin_headers,
        json={"mode": "BLIND", "warehouse_id": seeded_warehouse.id},
    )
    session_id = open_resp.json()["session_id"]
    line_resp = await http_client.post(
        f"/api/v1/inventory/count-sessions/{session_id}/line",
        headers=admin_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "location_id": seeded_location.id,
            "counted_qty": 100,
            "reason_code": None,
        },
    )
    assert line_resp.status_code == 201
    # Blind mode must NOT leak expected_qty
    assert line_resp.json()["expected_qty"] is None


async def test_open_count_session_without_scope_returns_403(
    http_client, librarian_headers, seeded_warehouse
):
    resp = await http_client.post(
        "/api/v1/inventory/count-sessions/",
        headers=librarian_headers,
        json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_add_count_line_without_scope_returns_403(
    http_client,
    admin_headers,
    librarian_headers,
    seeded_warehouse,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
):
    open_resp = await http_client.post(
        "/api/v1/inventory/count-sessions/",
        headers=admin_headers,
        json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
    )
    assert open_resp.status_code == 201
    session_id = open_resp.json()["session_id"]

    resp = await http_client.post(
        f"/api/v1/inventory/count-sessions/{session_id}/line",
        headers=librarian_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "location_id": seeded_location.id,
            "counted_qty": 10,
            "reason_code": "PHYSICAL_COUNT",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_update_count_line_without_scope_returns_403(
    http_client,
    admin_headers,
    librarian_headers,
    seeded_warehouse,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
):
    open_resp = await http_client.post(
        "/api/v1/inventory/count-sessions/",
        headers=admin_headers,
        json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
    )
    assert open_resp.status_code == 201
    session_id = open_resp.json()["session_id"]

    line_resp = await http_client.post(
        f"/api/v1/inventory/count-sessions/{session_id}/line",
        headers=admin_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "location_id": seeded_location.id,
            "counted_qty": 10,
            "reason_code": "PHYSICAL_COUNT",
        },
    )
    assert line_resp.status_code == 201
    line_id = line_resp.json()["line_id"]

    resp = await http_client.put(
        f"/api/v1/inventory/count-sessions/{session_id}/lines/{line_id}",
        headers=librarian_headers,
        json={"counted_qty": 9},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_close_count_session_without_scope_returns_403(
    http_client,
    admin_headers,
    librarian_headers,
    seeded_warehouse,
):
    open_resp = await http_client.post(
        "/api/v1/inventory/count-sessions/",
        headers=admin_headers,
        json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
    )
    assert open_resp.status_code == 201
    session_id = open_resp.json()["session_id"]

    resp = await http_client.post(
        f"/api/v1/inventory/count-sessions/{session_id}/close",
        headers=librarian_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_approve_count_session_with_permission_but_no_scope_returns_403(
    db_session,
    http_client,
    admin_headers,
    reviewer_headers,
    seeded_roles,
    seeded_warehouse,
):
    perm = await db_session.execute(
        select(PermissionORM).where(PermissionORM.name == "inventory.approve_count")
    )
    approve_perm = perm.scalar_one()
    existing = await db_session.execute(
        select(RolePermissionORM).where(
            RolePermissionORM.role_id == seeded_roles["REVIEWER"].id,
            RolePermissionORM.permission_id == approve_perm.id,
        )
    )
    if existing.scalar_one_or_none() is None:
        db_session.add(
            RolePermissionORM(
                role_id=seeded_roles["REVIEWER"].id,
                permission_id=approve_perm.id,
            )
        )
        await db_session.flush()

    open_resp = await http_client.post(
        "/api/v1/inventory/count-sessions/",
        headers=admin_headers,
        json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
    )
    assert open_resp.status_code == 201
    session_id = open_resp.json()["session_id"]

    close_resp = await http_client.post(
        f"/api/v1/inventory/count-sessions/{session_id}/close",
        headers=admin_headers,
    )
    assert close_resp.status_code == 200

    approve_resp = await http_client.post(
        f"/api/v1/inventory/count-sessions/{session_id}/approve",
        headers=reviewer_headers,
        json={"notes": "Attempt without scope"},
    )
    assert approve_resp.status_code == 403
    assert approve_resp.json()["error"]["code"] in (
        "SCOPE_VIOLATION",
        "INSUFFICIENT_PERMISSION",
    )
