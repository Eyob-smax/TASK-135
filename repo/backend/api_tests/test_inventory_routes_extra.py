"""
Additional integration tests for /api/v1/inventory/ error branches.

Focuses on admin-authorised error paths that existing tests don't exercise:
  - get_item / update_item: not-found + success
  - create_warehouse / create_location: success paths
  - freeze/unfreeze: not-found branches
  - add_adjustment: invalid stock status → 422
  - list_stock / list_ledger with filter variants
"""
from __future__ import annotations

import uuid


async def test_get_item_not_found_returns_404(http_client, admin_headers):
    resp = await http_client.get(
        f"/api/v1/inventory/items/{uuid.uuid4()}",
        headers=admin_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"


async def test_get_item_success_returns_200(
    http_client, admin_headers, seeded_inventory_item
):
    resp = await http_client.get(
        f"/api/v1/inventory/items/{seeded_inventory_item.id}",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sku"] == "TEST-001"


async def test_update_item_not_found_returns_404(http_client, admin_headers):
    resp = await http_client.put(
        f"/api/v1/inventory/items/{uuid.uuid4()}",
        headers=admin_headers,
        json={"name": "X", "description": "y", "unit_cost": "1.00"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"


async def test_update_item_success_changes_fields(
    http_client, admin_headers, seeded_inventory_item
):
    resp = await http_client.put(
        f"/api/v1/inventory/items/{seeded_inventory_item.id}",
        headers=admin_headers,
        json={"name": "Updated", "description": "new desc", "unit_cost": "12.34"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Updated"
    assert body["unit_cost"] == "12.34"


async def test_create_warehouse_returns_201(
    http_client, admin_headers, seeded_school
):
    resp = await http_client.post(
        "/api/v1/inventory/warehouses/",
        headers=admin_headers,
        json={
            "name": "Secondary Warehouse",
            "school_id": seeded_school.id,
            "address": "456 Other St",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Secondary Warehouse"
    assert body["school_id"] == seeded_school.id


async def test_create_location_returns_201(
    http_client, admin_headers, seeded_warehouse
):
    resp = await http_client.post(
        "/api/v1/inventory/locations/",
        headers=admin_headers,
        json={
            "warehouse_id": seeded_warehouse.id,
            "zone": "B",
            "aisle": "02",
            "bin_label": "B-02-01",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["zone"] == "B"
    assert body["bin_label"] == "B-02-01"


async def test_list_locations_filters_by_warehouse(
    http_client, admin_headers, seeded_location, seeded_warehouse
):
    resp = await http_client.get(
        "/api/v1/inventory/locations/",
        headers=admin_headers,
        params={"warehouse_id": seeded_warehouse.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert any(loc["location_id"] == seeded_location.id for loc in body)


async def test_freeze_stock_not_found_returns_404(http_client, admin_headers):
    resp = await http_client.post(
        f"/api/v1/inventory/stock/{uuid.uuid4()}/freeze",
        headers=admin_headers,
        json={"reason": "Audit hold"},
    )
    assert resp.status_code == 404


async def test_unfreeze_stock_not_found_returns_404(http_client, admin_headers):
    resp = await http_client.post(
        f"/api/v1/inventory/stock/{uuid.uuid4()}/unfreeze",
        headers=admin_headers,
    )
    assert resp.status_code == 404


async def test_unfreeze_stock_not_frozen_returns_404(
    http_client, admin_headers, seeded_stock_balance
):
    # A balance that's never been frozen triggers DomainValidationError in service
    resp = await http_client.post(
        f"/api/v1/inventory/stock/{seeded_stock_balance.id}/unfreeze",
        headers=admin_headers,
    )
    assert resp.status_code == 404


async def test_freeze_stock_already_frozen_returns_409(
    http_client, admin_headers, seeded_stock_balance
):
    first = await http_client.post(
        f"/api/v1/inventory/stock/{seeded_stock_balance.id}/freeze",
        headers=admin_headers,
        json={"reason": "Cycle count"},
    )
    assert first.status_code == 200

    second = await http_client.post(
        f"/api/v1/inventory/stock/{seeded_stock_balance.id}/freeze",
        headers=admin_headers,
        json={"reason": "Second freeze"},
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "STOCK_FROZEN"


async def test_add_adjustment_invalid_status_returns_422(
    http_client,
    admin_headers,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
):
    resp = await http_client.post(
        "/api/v1/inventory/ledger/adjustment",
        headers=admin_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "location_id": seeded_location.id,
            "quantity_delta": 1,
            "reason_code": "RESTOCK",
            "status": "NOT_A_REAL_STATUS",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "VALIDATION_ERROR"


async def test_add_adjustment_insufficient_stock_returns_400(
    http_client,
    admin_headers,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
):
    # seeded balance is 100; negative delta larger than that should trip InsufficientStockError
    resp = await http_client.post(
        "/api/v1/inventory/ledger/adjustment",
        headers=admin_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "location_id": seeded_location.id,
            "quantity_delta": -9999,
            "reason_code": "RESTOCK",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "INSUFFICIENT_STOCK"


async def test_add_adjustment_on_frozen_balance_returns_409(
    http_client,
    admin_headers,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
):
    freeze_resp = await http_client.post(
        f"/api/v1/inventory/stock/{seeded_stock_balance.id}/freeze",
        headers=admin_headers,
        json={"reason": "Frozen for audit"},
    )
    assert freeze_resp.status_code == 200

    resp = await http_client.post(
        "/api/v1/inventory/ledger/adjustment",
        headers=admin_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "location_id": seeded_location.id,
            "quantity_delta": 2,
            "reason_code": "RESTOCK",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "STOCK_FROZEN"


async def test_add_correction_on_already_reversed_entry_returns_400(
    http_client,
    admin_headers,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
):
    create_resp = await http_client.post(
        "/api/v1/inventory/ledger/adjustment",
        headers=admin_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "location_id": seeded_location.id,
            "quantity_delta": 5,
            "reason_code": "RESTOCK",
        },
    )
    assert create_resp.status_code == 201
    entry_id = create_resp.json()["entry_id"]

    first_corr = await http_client.post(
        f"/api/v1/inventory/ledger/correction/{entry_id}",
        headers=admin_headers,
        json={"reason_code": "CORRECTION"},
    )
    assert first_corr.status_code == 201

    second_corr = await http_client.post(
        f"/api/v1/inventory/ledger/correction/{entry_id}",
        headers=admin_headers,
        json={"reason_code": "CORRECTION"},
    )
    assert second_corr.status_code == 400
    assert second_corr.json()["detail"]["code"] == "APPEND_ONLY_VIOLATION"


async def test_list_stock_filter_by_item_and_location(
    http_client,
    admin_headers,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
):
    resp = await http_client.get(
        "/api/v1/inventory/stock/",
        headers=admin_headers,
        params={
            "item_id": seeded_inventory_item.id,
            "location_id": seeded_location.id,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1


async def test_list_ledger_filter_by_item(
    http_client,
    admin_headers,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
):
    # Create one ledger entry first so the list isn't empty
    await http_client.post(
        "/api/v1/inventory/ledger/adjustment",
        headers=admin_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "location_id": seeded_location.id,
            "quantity_delta": 5,
            "reason_code": "RESTOCK",
        },
    )
    resp = await http_client.get(
        "/api/v1/inventory/ledger/",
        headers=admin_headers,
        params={
            "item_id": seeded_inventory_item.id,
            "entry_type": "ADJUSTMENT",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
