"""
API integration tests for /api/v1/inventory/ endpoints.
"""
from __future__ import annotations

import uuid


class TestInventoryRoutes:
    async def test_create_inventory_item_returns_201(self, http_client, admin_headers):
        response = await http_client.post(
            "/api/v1/inventory/items/",
            headers=admin_headers,
            json={"sku": "NEW-001", "name": "New Widget", "description": "", "unit_cost": "5.99"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["sku"] == "NEW-001"
        assert body["unit_cost"] == "5.99"

    async def test_list_items_returns_paginated(
        self, http_client, admin_headers, seeded_inventory_item
    ):
        response = await http_client.get(
            "/api/v1/inventory/items/", headers=admin_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert "items" in body
        assert body["total"] >= 1

    async def test_create_item_duplicate_sku_returns_409(
        self, http_client, admin_headers, seeded_inventory_item
    ):
        # seeded_inventory_item has sku="TEST-001"
        response = await http_client.post(
            "/api/v1/inventory/items/",
            headers=admin_headers,
            json={"sku": "TEST-001", "name": "Duplicate", "description": "", "unit_cost": "1.00"},
        )
        assert response.status_code == 409

    async def test_freeze_stock_requires_reason(
        self, http_client, admin_headers, seeded_stock_balance
    ):
        balance_id = seeded_stock_balance.id
        response = await http_client.post(
            f"/api/v1/inventory/stock/{balance_id}/freeze",
            headers=admin_headers,
            json={},  # missing 'reason'
        )
        assert response.status_code == 422

    async def test_freeze_and_unfreeze_stock(
        self, http_client, admin_headers, seeded_stock_balance
    ):
        balance_id = seeded_stock_balance.id
        freeze_resp = await http_client.post(
            f"/api/v1/inventory/stock/{balance_id}/freeze",
            headers=admin_headers,
            json={"reason": "Audit hold"},
        )
        assert freeze_resp.status_code == 200
        assert freeze_resp.json()["is_frozen"] is True

        unfreeze_resp = await http_client.post(
            f"/api/v1/inventory/stock/{balance_id}/unfreeze",
            headers=admin_headers,
        )
        assert unfreeze_resp.status_code == 200
        assert unfreeze_resp.json()["is_frozen"] is False

    async def test_add_adjustment_creates_ledger_entry(
        self, http_client, admin_headers,
        seeded_inventory_item, seeded_location, seeded_stock_balance
    ):
        response = await http_client.post(
            "/api/v1/inventory/ledger/adjustment",
            headers=admin_headers,
            json={
                "item_id": seeded_inventory_item.id,
                "location_id": seeded_location.id,
                "quantity_delta": 10,
                "reason_code": "RESTOCK",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["quantity_delta"] == 10
        assert body["entry_type"] == "ADJUSTMENT"

    async def test_add_adjustment_respects_batch_partition(
        self,
        http_client,
        admin_headers,
        seeded_inventory_item,
        seeded_location,
        seeded_stock_balance,
    ):
        batch_a_1 = await http_client.post(
            "/api/v1/inventory/ledger/adjustment",
            headers=admin_headers,
            json={
                "item_id": seeded_inventory_item.id,
                "location_id": seeded_location.id,
                "quantity_delta": 5,
                "reason_code": "RESTOCK",
                "batch_id": "BATCH-A",
            },
        )
        batch_b_1 = await http_client.post(
            "/api/v1/inventory/ledger/adjustment",
            headers=admin_headers,
            json={
                "item_id": seeded_inventory_item.id,
                "location_id": seeded_location.id,
                "quantity_delta": 7,
                "reason_code": "RESTOCK",
                "batch_id": "BATCH-B",
            },
        )
        batch_a_2 = await http_client.post(
            "/api/v1/inventory/ledger/adjustment",
            headers=admin_headers,
            json={
                "item_id": seeded_inventory_item.id,
                "location_id": seeded_location.id,
                "quantity_delta": 3,
                "reason_code": "RESTOCK",
                "batch_id": "BATCH-A",
            },
        )

        assert batch_a_1.status_code == 201
        assert batch_b_1.status_code == 201
        assert batch_a_2.status_code == 201

        assert batch_a_1.json()["quantity_after"] == 5
        assert batch_b_1.json()["quantity_after"] == 7
        assert batch_a_2.json()["quantity_after"] == 8

    async def test_add_correction_reverses_entry(
        self, http_client, admin_headers,
        seeded_inventory_item, seeded_location, seeded_stock_balance
    ):
        adj_resp = await http_client.post(
            "/api/v1/inventory/ledger/adjustment",
            headers=admin_headers,
            json={
                "item_id": seeded_inventory_item.id,
                "location_id": seeded_location.id,
                "quantity_delta": 20,
                "reason_code": "RECEIPT",
            },
        )
        entry_id = adj_resp.json()["entry_id"]
        corr_resp = await http_client.post(
            f"/api/v1/inventory/ledger/correction/{entry_id}",
            headers=admin_headers,
            json={"reason_code": "CORRECTION"},
        )
        assert corr_resp.status_code == 201
        assert corr_resp.json()["reversal_of_id"] == entry_id

    async def test_list_warehouses_returns_paginated_envelope(
        self, http_client, admin_headers, seeded_warehouse
    ):
        """GET /warehouses/ must return a paginated envelope with items/total keys.

        This contract is consumed by the count-session UI screen (count_session.py),
        which calls data.get('items', []) on the response. A plain list response would
        silently return an empty list and prevent sessions from opening.
        """
        response = await http_client.get(
            "/api/v1/inventory/warehouses/", headers=admin_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert "items" in body, "Response must be a paginated envelope with an 'items' key"
        assert "total" in body, "Response must include 'total' count"
        assert body["total"] >= 1
        first = body["items"][0]
        assert "warehouse_id" in first
        assert "name" in first
        assert "school_id" in first
        assert "is_active" in first

    async def test_list_stock_returns_paginated(
        self, http_client, admin_headers, seeded_stock_balance
    ):
        response = await http_client.get(
            "/api/v1/inventory/stock/", headers=admin_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert "items" in body
        assert body["total"] >= 1
