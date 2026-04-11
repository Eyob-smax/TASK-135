"""
API integration tests for /api/v1/inventory/count-sessions/ endpoints.
"""
from __future__ import annotations

import uuid


class TestCountRoutes:
    async def test_open_count_session_returns_201(
        self, http_client, admin_headers, seeded_warehouse
    ):
        response = await http_client.post(
            "/api/v1/inventory/count-sessions/",
            headers=admin_headers,
            json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "ACTIVE"
        assert body["mode"] == "OPEN"
        assert "expires_at" in body

    async def test_add_count_line_returns_variance(
        self, http_client, admin_headers,
        seeded_warehouse, seeded_inventory_item, seeded_location, seeded_stock_balance
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
        assert line_resp.status_code == 201
        body = line_resp.json()
        assert body["variance_qty"] == -5
        assert body["expected_qty"] == 100  # OPEN mode shows expected

    async def test_close_session_transitions_status(
        self, http_client, admin_headers, seeded_warehouse
    ):
        open_resp = await http_client.post(
            "/api/v1/inventory/count-sessions/",
            headers=admin_headers,
            json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
        )
        session_id = open_resp.json()["session_id"]

        close_resp = await http_client.post(
            f"/api/v1/inventory/count-sessions/{session_id}/close",
            headers=admin_headers,
        )
        assert close_resp.status_code == 200
        assert close_resp.json()["status"] == "CLOSED"

    async def test_approve_session_requires_admin_role(
        self, http_client, librarian_headers, admin_headers, seeded_warehouse
    ):
        open_resp = await http_client.post(
            "/api/v1/inventory/count-sessions/",
            headers=admin_headers,
            json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
        )
        session_id = open_resp.json()["session_id"]
        await http_client.post(
            f"/api/v1/inventory/count-sessions/{session_id}/close",
            headers=admin_headers,
        )

        # Librarian should NOT be able to approve (missing inventory.approve_count)
        approve_resp = await http_client.post(
            f"/api/v1/inventory/count-sessions/{session_id}/approve",
            headers=librarian_headers,
            json={"notes": "Looks good"},
        )
        assert approve_resp.status_code == 403

    async def test_approve_session_with_admin_succeeds(
        self, http_client, admin_headers, seeded_warehouse
    ):
        open_resp = await http_client.post(
            "/api/v1/inventory/count-sessions/",
            headers=admin_headers,
            json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
        )
        session_id = open_resp.json()["session_id"]
        await http_client.post(
            f"/api/v1/inventory/count-sessions/{session_id}/close",
            headers=admin_headers,
        )
        approve_resp = await http_client.post(
            f"/api/v1/inventory/count-sessions/{session_id}/approve",
            headers=admin_headers,
            json={"notes": "Variance approved"},
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "APPROVED"

    async def test_get_session_includes_count_lines(
        self, http_client, admin_headers,
        seeded_warehouse, seeded_inventory_item, seeded_location, seeded_stock_balance
    ):
        open_resp = await http_client.post(
            "/api/v1/inventory/count-sessions/",
            headers=admin_headers,
            json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
        )
        session_id = open_resp.json()["session_id"]

        await http_client.post(
            f"/api/v1/inventory/count-sessions/{session_id}/line",
            headers=admin_headers,
            json={
                "item_id": seeded_inventory_item.id,
                "location_id": seeded_location.id,
                "counted_qty": 80,
                "reason_code": "PHYSICAL_COUNT",
            },
        )

        get_resp = await http_client.get(
            f"/api/v1/inventory/count-sessions/{session_id}",
            headers=admin_headers,
        )
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert "lines" in body
        assert len(body["lines"]) == 1

    async def test_blind_mode_masks_expected_qty(
        self, http_client, admin_headers,
        seeded_warehouse, seeded_inventory_item, seeded_location, seeded_stock_balance
    ):
        """BLIND mode count sessions must return expected_qty=null in API responses."""
        open_resp = await http_client.post(
            "/api/v1/inventory/count-sessions/",
            headers=admin_headers,
            json={"mode": "BLIND", "warehouse_id": seeded_warehouse.id},
        )
        assert open_resp.status_code == 201
        session_id = open_resp.json()["session_id"]
        assert open_resp.json()["mode"] == "BLIND"

        line_resp = await http_client.post(
            f"/api/v1/inventory/count-sessions/{session_id}/line",
            headers=admin_headers,
            json={
                "item_id": seeded_inventory_item.id,
                "location_id": seeded_location.id,
                "counted_qty": 90,
                "reason_code": "PHYSICAL_COUNT",
            },
        )
        assert line_resp.status_code == 201
        line_body = line_resp.json()
        # Blind mode must not reveal expected_qty to the counter
        assert line_body["expected_qty"] is None

    async def test_open_mode_reveals_expected_qty(
        self, http_client, admin_headers,
        seeded_warehouse, seeded_inventory_item, seeded_location, seeded_stock_balance
    ):
        """OPEN mode count sessions must return the actual expected_qty."""
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
        line_body = line_resp.json()
        # seeded_stock_balance has quantity=100 → expected_qty=100
        assert line_body["expected_qty"] == 100

    async def test_update_count_line(
        self, http_client, admin_headers,
        seeded_warehouse, seeded_inventory_item, seeded_location, seeded_stock_balance
    ):
        """PUT on count line recalculates variance."""
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
                "counted_qty": 80,
                "reason_code": "PHYSICAL_COUNT",
            },
        )
        line_id = line_resp.json()["line_id"]

        update_resp = await http_client.put(
            f"/api/v1/inventory/count-sessions/{session_id}/lines/{line_id}",
            headers=admin_headers,
            json={"counted_qty": 98},
        )
        assert update_resp.status_code == 200
        body = update_resp.json()
        assert body["counted_qty"] == 98
        assert body["variance_qty"] == -2  # 100 expected - 98 counted

    async def test_get_count_session_not_found_returns_404(
        self, http_client, admin_headers
    ):
        import uuid
        resp = await http_client.get(
            f"/api/v1/inventory/count-sessions/{uuid.uuid4()}",
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_open_count_session_requires_count_permission(
        self, http_client, auth_headers, seeded_warehouse
    ):
        """A user without inventory.count must be rejected with 403."""
        resp = await http_client.post(
            "/api/v1/inventory/count-sessions/",
            headers=auth_headers,
            json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
        )
        assert resp.status_code == 403
