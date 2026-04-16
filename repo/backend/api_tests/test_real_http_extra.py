"""
Additional true no-mock HTTP tests.

These tests extend real TCP coverage beyond the base smoke set in
`test_real_http.py` by exercising endpoint classes that were previously
covered only through in-process ASGI transport.
"""
from __future__ import annotations

import hashlib
import io
import json
import time
import uuid
import zipfile

import httpx
from sqlalchemy import select

from district_console.infrastructure.hmac_signer import HmacSigner
from district_console.infrastructure.orm import UserORM


def _make_hmac_headers(
    client_id: str,
    key_hex: str,
    method: str,
    path: str,
    body: bytes = b"",
    timestamp: str | None = None,
) -> dict[str, str]:
    signer = HmacSigner()
    ts = timestamp if timestamp is not None else str(int(time.time()))
    signature = signer.sign(HmacSigner.key_from_hex(key_hex), method, path, ts, body)
    return {
        "X-DC-Client-ID": client_id,
        "X-DC-Timestamp": ts,
        "X-DC-Signature": f"hmac-sha256 {signature}",
    }


def _make_zip_bytes(version: str) -> bytes:
    payload = b"{}"
    checksum = hashlib.sha256(payload).hexdigest()
    manifest = {
        "version": version,
        "build_id": f"build-{version}",
        "file_list": ["data/config.json"],
        "checksums": {"data/config.json": checksum},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("data/config.json", payload)
    return buf.getvalue()


async def _user_id_by_username(db_session, username: str) -> str:
    result = await db_session.execute(
        select(UserORM.id).where(UserORM.username == username)
    )
    user_id = result.scalar_one_or_none()
    assert user_id is not None
    return user_id


async def test_resource_mutation_workflow_via_real_http(
    real_http_url,
    db_session,
    admin_headers,
    librarian_headers,
    reviewer_headers,
):
    reviewer_id = await _user_id_by_username(db_session, "reviewer_user")

    async with httpx.AsyncClient(base_url=real_http_url) as client:
        create_resp = await client.post(
            "/api/v1/resources/",
            headers=admin_headers,
            json={"title": "TCP Mutation Resource", "resource_type": "BOOK"},
        )
        assert create_resp.status_code == 201
        resource_id = create_resp.json()["resource_id"]

        update_resp = await client.put(
            f"/api/v1/resources/{resource_id}",
            headers=admin_headers,
            json={"title": "TCP Updated Resource"},
        )
        assert update_resp.status_code == 200

        classify_resp = await client.post(
            f"/api/v1/resources/{resource_id}/classify",
            headers=admin_headers,
            json={"min_age": 8, "max_age": 12, "timeliness_type": "EVERGREEN"},
        )
        assert classify_resp.status_code == 204

        allocation_resp = await client.post(
            f"/api/v1/resources/{resource_id}/request-allocation",
            headers=admin_headers,
        )
        assert allocation_resp.status_code == 204

        submit_resp = await client.post(
            f"/api/v1/resources/{resource_id}/submit-review",
            headers=admin_headers,
            json={"reviewer_id": reviewer_id},
        )
        assert submit_resp.status_code == 200

        publish_resp = await client.post(
            f"/api/v1/resources/{resource_id}/publish",
            headers=reviewer_headers,
            json={"reviewer_notes": "TCP publish"},
        )
        assert publish_resp.status_code == 200

        unpublish_resp = await client.post(
            f"/api/v1/resources/{resource_id}/unpublish",
            headers=reviewer_headers,
            json={"reviewer_notes": "TCP unpublish"},
        )
        assert unpublish_resp.status_code == 200

        revisions_resp = await client.get(
            f"/api/v1/resources/{resource_id}/revisions",
            headers=admin_headers,
        )
        assert revisions_resp.status_code == 200
        assert isinstance(revisions_resp.json(), list)


async def test_inventory_mutation_workflow_via_real_http(
    real_http_url,
    admin_headers,
    seeded_school,
    seeded_warehouse,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
):
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        get_item_resp = await client.get(
            f"/api/v1/inventory/items/{seeded_inventory_item.id}",
            headers=admin_headers,
        )
        assert get_item_resp.status_code == 200

        update_item_resp = await client.put(
            f"/api/v1/inventory/items/{seeded_inventory_item.id}",
            headers=admin_headers,
            json={"name": "TCP Item Name", "description": "tcp", "unit_cost": "7.77"},
        )
        assert update_item_resp.status_code == 200

        warehouse_resp = await client.post(
            "/api/v1/inventory/warehouses/",
            headers=admin_headers,
            json={
                "name": "TCP Warehouse",
                "school_id": seeded_school.id,
                "address": "TCP Address",
            },
        )
        assert warehouse_resp.status_code == 201
        warehouse_id = warehouse_resp.json()["warehouse_id"]

        create_location_resp = await client.post(
            "/api/v1/inventory/locations/",
            headers=admin_headers,
            json={
                "warehouse_id": warehouse_id,
                "zone": "T",
                "aisle": "01",
                "bin_label": "T-01-01",
            },
        )
        assert create_location_resp.status_code == 201

        list_locations_resp = await client.get(
            "/api/v1/inventory/locations/",
            headers=admin_headers,
            params={"warehouse_id": seeded_warehouse.id},
        )
        assert list_locations_resp.status_code == 200

        stock_resp = await client.get(
            "/api/v1/inventory/stock/",
            headers=admin_headers,
        )
        assert stock_resp.status_code == 200

        freeze_resp = await client.post(
            f"/api/v1/inventory/stock/{seeded_stock_balance.id}/freeze",
            headers=admin_headers,
            json={"reason": "TCP hold"},
        )
        assert freeze_resp.status_code == 200

        unfreeze_resp = await client.post(
            f"/api/v1/inventory/stock/{seeded_stock_balance.id}/unfreeze",
            headers=admin_headers,
        )
        assert unfreeze_resp.status_code == 200

        adjust_resp = await client.post(
            "/api/v1/inventory/ledger/adjustment",
            headers=admin_headers,
            json={
                "item_id": seeded_inventory_item.id,
                "location_id": seeded_location.id,
                "quantity_delta": 3,
                "reason_code": "RESTOCK",
            },
        )
        assert adjust_resp.status_code == 201
        entry_id = adjust_resp.json()["entry_id"]

        ledger_resp = await client.get(
            "/api/v1/inventory/ledger/",
            headers=admin_headers,
            params={"item_id": seeded_inventory_item.id},
        )
        assert ledger_resp.status_code == 200

        correction_resp = await client.post(
            f"/api/v1/inventory/ledger/correction/{entry_id}",
            headers=admin_headers,
            json={"reason_code": "CORRECTION"},
        )
        assert correction_resp.status_code == 201


async def test_count_and_relocation_workflow_via_real_http(
    real_http_url,
    admin_headers,
    seeded_warehouse,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
):
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        list_count_resp = await client.get(
            "/api/v1/inventory/count-sessions/",
            headers=admin_headers,
        )
        assert list_count_resp.status_code == 200

        open_resp = await client.post(
            "/api/v1/inventory/count-sessions/",
            headers=admin_headers,
            json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
        )
        assert open_resp.status_code == 201
        session_id = open_resp.json()["session_id"]

        add_line_resp = await client.post(
            f"/api/v1/inventory/count-sessions/{session_id}/line",
            headers=admin_headers,
            json={
                "item_id": seeded_inventory_item.id,
                "location_id": seeded_location.id,
                "counted_qty": 99,
                "reason_code": "PHYSICAL_COUNT",
            },
        )
        assert add_line_resp.status_code == 201
        line_id = add_line_resp.json()["line_id"]

        update_line_resp = await client.put(
            f"/api/v1/inventory/count-sessions/{session_id}/lines/{line_id}",
            headers=admin_headers,
            json={"counted_qty": 98},
        )
        assert update_line_resp.status_code == 200

        get_count_resp = await client.get(
            f"/api/v1/inventory/count-sessions/{session_id}",
            headers=admin_headers,
        )
        assert get_count_resp.status_code == 200

        close_resp = await client.post(
            f"/api/v1/inventory/count-sessions/{session_id}/close",
            headers=admin_headers,
        )
        assert close_resp.status_code == 200

        approve_resp = await client.post(
            f"/api/v1/inventory/count-sessions/{session_id}/approve",
            headers=admin_headers,
            json={"notes": "TCP approval"},
        )
        assert approve_resp.status_code == 200

        new_location_resp = await client.post(
            "/api/v1/inventory/locations/",
            headers=admin_headers,
            json={
                "warehouse_id": seeded_warehouse.id,
                "zone": "R",
                "aisle": "02",
                "bin_label": "R-02-01",
            },
        )
        assert new_location_resp.status_code == 201
        to_location_id = new_location_resp.json()["location_id"]

        relocate_resp = await client.post(
            "/api/v1/inventory/relocations/",
            headers=admin_headers,
            json={
                "item_id": seeded_inventory_item.id,
                "from_location_id": seeded_location.id,
                "to_location_id": to_location_id,
                "quantity": 1,
                "device_source": "MANUAL",
            },
        )
        assert relocate_resp.status_code == 201

        list_relocations_resp = await client.get(
            "/api/v1/inventory/relocations/",
            headers=admin_headers,
        )
        assert list_relocations_resp.status_code == 200


async def test_integrations_hmac_and_events_via_real_http(real_http_url, admin_headers):
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        create_resp = await client.post(
            "/api/v1/integrations/",
            headers=admin_headers,
            json={"name": f"tcp-integration-{uuid.uuid4().hex[:6]}", "description": "tcp"},
        )
        assert create_resp.status_code == 201
        create_body = create_resp.json()
        client_id = create_body["client"]["client_id"]
        key_hex = create_body["initial_key"]["key_value"]

        inbound_headers = _make_hmac_headers(
            client_id=client_id,
            key_hex=key_hex,
            method="GET",
            path="/api/v1/integrations/inbound/status",
        )
        inbound_resp = await client.get(
            "/api/v1/integrations/inbound/status",
            headers=inbound_headers,
        )
        assert inbound_resp.status_code == 200

        rotate_resp = await client.post(
            f"/api/v1/integrations/{client_id}/rotate-key",
            headers=admin_headers,
        )
        assert rotate_resp.status_code == 200

        commit_resp = await client.post(
            f"/api/v1/integrations/{client_id}/commit-rotation",
            headers=admin_headers,
        )
        assert commit_resp.status_code == 200

        events_resp = await client.get(
            "/api/v1/integrations/events/",
            headers=admin_headers,
        )
        assert events_resp.status_code == 200

        emit_resp = await client.post(
            f"/api/v1/integrations/events/{client_id}/emit",
            headers=admin_headers,
            json={"event_type": "resource.imported", "payload": {"id": "tcp"}},
        )
        assert emit_resp.status_code == 201

        retry_resp = await client.post(
            "/api/v1/integrations/events/retry",
            headers=admin_headers,
        )
        assert retry_resp.status_code == 200

        delete_resp = await client.delete(
            f"/api/v1/integrations/{client_id}",
            headers=admin_headers,
        )
        assert delete_resp.status_code == 204


async def test_admin_config_taxonomy_updates_and_audit_misc_via_real_http(
    real_http_url,
    admin_headers,
):
    suffix = uuid.uuid4().hex[:6]

    async with httpx.AsyncClient(base_url=real_http_url) as client:
        cfg_resp = await client.put(
            f"/api/v1/admin/config/runtime/tcp-delete-{suffix}",
            headers=admin_headers,
            json={"value": "1", "description": "delete target"},
        )
        assert cfg_resp.status_code == 200
        entry_id = cfg_resp.json()["entry_id"]

        wf_create_resp = await client.post(
            "/api/v1/admin/config/workflow-nodes/",
            headers=admin_headers,
            json={
                "workflow_name": f"tcp_wf_{suffix}",
                "from_state": "A",
                "to_state": "B",
                "required_role": "REVIEWER",
                "condition_json": None,
            },
        )
        assert wf_create_resp.status_code == 201
        node_id = wf_create_resp.json()["node_id"]

        wf_delete_resp = await client.delete(
            f"/api/v1/admin/config/workflow-nodes/{node_id}",
            headers=admin_headers,
        )
        assert wf_delete_resp.status_code == 204

        delete_cfg_resp = await client.delete(
            f"/api/v1/admin/config/{entry_id}",
            headers=admin_headers,
        )
        assert delete_cfg_resp.status_code == 204

        cat_create_resp = await client.post(
            "/api/v1/admin/taxonomy/categories/",
            headers=admin_headers,
            json={"name": f"TcpCategory{suffix}"},
        )
        assert cat_create_resp.status_code == 201
        category_id = cat_create_resp.json()["category_id"]

        cat_update_resp = await client.put(
            f"/api/v1/admin/taxonomy/categories/{category_id}",
            headers=admin_headers,
            json={"name": f"TcpCategoryRenamed{suffix}"},
        )
        assert cat_update_resp.status_code == 200

        cat_delete_resp = await client.delete(
            f"/api/v1/admin/taxonomy/categories/{category_id}",
            headers=admin_headers,
        )
        assert cat_delete_resp.status_code == 204

        rule_create_resp = await client.post(
            "/api/v1/admin/taxonomy/rules/",
            headers=admin_headers,
            json={
                "field": "title",
                "rule_type": "max_length",
                "rule_value": "200",
                "description": "tcp rule",
            },
        )
        assert rule_create_resp.status_code == 201
        rule_id = rule_create_resp.json()["rule_id"]

        rule_delete_resp = await client.delete(
            f"/api/v1/admin/taxonomy/rules/{rule_id}",
            headers=admin_headers,
        )
        assert rule_delete_resp.status_code == 204

        import_v1_resp = await client.post(
            "/api/v1/admin/updates/import",
            headers=admin_headers,
            files={"file": ("tcp_v1.zip", _make_zip_bytes("7.1.0"), "application/zip")},
        )
        assert import_v1_resp.status_code == 201
        v1_id = import_v1_resp.json()["package_id"]

        apply_v1_resp = await client.post(
            f"/api/v1/admin/updates/{v1_id}/apply",
            headers=admin_headers,
        )
        assert apply_v1_resp.status_code == 200

        import_v2_resp = await client.post(
            "/api/v1/admin/updates/import",
            headers=admin_headers,
            files={"file": ("tcp_v2.zip", _make_zip_bytes("7.2.0"), "application/zip")},
        )
        assert import_v2_resp.status_code == 201
        v2_id = import_v2_resp.json()["package_id"]

        apply_v2_resp = await client.post(
            f"/api/v1/admin/updates/{v2_id}/apply",
            headers=admin_headers,
        )
        assert apply_v2_resp.status_code == 200

        rollback_resp = await client.post(
            f"/api/v1/admin/updates/{v2_id}/rollback",
            headers=admin_headers,
        )
        assert rollback_resp.status_code == 200

        security_events_resp = await client.get(
            "/api/v1/admin/audit/events/security/",
            headers=admin_headers,
        )
        assert security_events_resp.status_code == 200

        approval_queue_resp = await client.get(
            "/api/v1/admin/audit/approval-queue/",
            headers=admin_headers,
        )
        assert approval_queue_resp.status_code == 200
