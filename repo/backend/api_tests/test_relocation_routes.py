"""
API tests for relocation routes (/api/v1/inventory/relocations/).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from district_console.application.auth_service import AuthService
from district_console.infrastructure.orm import (
    LocationORM,
    SchoolORM,
    ScopeAssignmentORM,
    StockBalanceORM,
    UserORM,
    UserRoleORM,
    WarehouseORM,
)
from district_console.infrastructure.repositories import RoleRepository, UserRepository


async def _create_user_with_role_and_scope(
    db_session,
    http_client,
    username: str,
    password: str,
    role_orm,
    seeded_user_orm,
    scope_type: str,
    scope_ref_id: str,
) -> dict:
    auth = AuthService(UserRepository(), RoleRepository())
    password_hash = auth.hash_password(password)
    now = datetime.utcnow().isoformat()

    user = UserORM(
        id=str(uuid.uuid4()),
        username=username,
        password_hash=password_hash,
        is_active=True,
        failed_attempts=0,
        locked_until=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(user)
    await db_session.flush()

    user_role = UserRoleORM(
        user_id=user.id,
        role_id=role_orm.id,
        assigned_by=seeded_user_orm.id,
        assigned_at=now,
    )
    db_session.add(user_role)

    scope = ScopeAssignmentORM(
        id=str(uuid.uuid4()),
        user_id=user.id,
        scope_type=scope_type,
        scope_ref_id=scope_ref_id,
        granted_by=seeded_user_orm.id,
        granted_at=now,
    )
    db_session.add(scope)
    await db_session.flush()

    resp = await http_client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


async def _create_location(db_session, warehouse_id: str, bin_label: str) -> LocationORM:
    location = LocationORM(
        id=str(uuid.uuid4()),
        warehouse_id=warehouse_id,
        zone="Z",
        aisle="01",
        bin_label=bin_label,
        is_active=True,
    )
    db_session.add(location)
    await db_session.flush()
    return location


async def test_create_relocation_requires_auth(http_client):
    resp = await http_client.post(
        "/api/v1/inventory/relocations/",
        json={
            "item_id": str(uuid.uuid4()),
            "from_location_id": str(uuid.uuid4()),
            "to_location_id": str(uuid.uuid4()),
            "quantity": 1,
            "device_source": "MANUAL",
        },
    )
    assert resp.status_code == 401


async def test_create_relocation_without_scope_returns_403(
    db_session,
    http_client,
    librarian_headers,
    seeded_inventory_item,
    seeded_location,
    seeded_warehouse,
):
    dest = await _create_location(db_session, seeded_warehouse.id, "Z-01-99")
    resp = await http_client.post(
        "/api/v1/inventory/relocations/",
        headers=librarian_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "from_location_id": seeded_location.id,
            "to_location_id": dest.id,
            "quantity": 1,
            "device_source": "MANUAL",
        },
    )
    assert resp.status_code == 403


async def test_create_relocation_with_admin_returns_201(
    db_session,
    http_client,
    admin_headers,
    seeded_inventory_item,
    seeded_location,
    seeded_warehouse,
    seeded_stock_balance,
):
    dest = await _create_location(db_session, seeded_warehouse.id, "Z-01-98")
    resp = await http_client.post(
        "/api/v1/inventory/relocations/",
        headers=admin_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "from_location_id": seeded_location.id,
            "to_location_id": dest.id,
            "quantity": 5,
            "device_source": "MANUAL",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["quantity"] == 5
    assert body["from_location_id"] == seeded_location.id
    assert body["to_location_id"] == dest.id


async def test_create_relocation_with_partition_fields_returns_201(
    db_session,
    http_client,
    admin_headers,
    seeded_inventory_item,
    seeded_location,
    seeded_warehouse,
):
    from district_console.infrastructure.orm import StockBalanceORM

    db_session.add(
        StockBalanceORM(
            id=str(uuid.uuid4()),
            item_id=seeded_inventory_item.id,
            location_id=seeded_location.id,
            batch_id="LOT-99",
            serial_id=None,
            status="AVAILABLE",
            quantity=12,
            is_frozen=False,
            freeze_reason=None,
            frozen_by=None,
            frozen_at=None,
        )
    )
    await db_session.flush()

    dest = await _create_location(db_session, seeded_warehouse.id, "Z-01-96")
    resp = await http_client.post(
        "/api/v1/inventory/relocations/",
        headers=admin_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "from_location_id": seeded_location.id,
            "to_location_id": dest.id,
            "quantity": 4,
            "device_source": "MANUAL",
            "status": "AVAILABLE",
            "batch_id": "LOT-99",
        },
    )
    assert resp.status_code == 201


async def test_create_relocation_cross_warehouse_returns_400(
    db_session,
    http_client,
    admin_headers,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
):
    other_school = SchoolORM(
        id=str(uuid.uuid4()),
        name="Cross Warehouse School",
        district_code="DIST-777",
        is_active=True,
    )
    db_session.add(other_school)
    await db_session.flush()

    other_warehouse = WarehouseORM(
        id=str(uuid.uuid4()),
        name="Cross Warehouse",
        school_id=other_school.id,
        address="Other Address",
        is_active=True,
    )
    db_session.add(other_warehouse)
    await db_session.flush()

    outside_dest = await _create_location(db_session, other_warehouse.id, "OUT-99-01")

    resp = await http_client.post(
        "/api/v1/inventory/relocations/",
        headers=admin_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "from_location_id": seeded_location.id,
            "to_location_id": outside_dest.id,
            "quantity": 2,
            "device_source": "MANUAL",
        },
    )
    assert resp.status_code == 400
    payload = resp.json()
    err = payload.get("error") or payload.get("detail") or {}
    assert err.get("code") == "VALIDATION_ERROR"


async def test_create_relocation_with_scoped_librarian_returns_201(
    db_session,
    http_client,
    seeded_roles,
    sample_password,
    seeded_user_orm,
    seeded_school,
    seeded_inventory_item,
    seeded_location,
    seeded_warehouse,
    seeded_stock_balance,
):
    scoped_headers = await _create_user_with_role_and_scope(
        db_session,
        http_client,
        username="scoped_relocator",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=seeded_school.id,
    )
    dest = await _create_location(db_session, seeded_warehouse.id, "Z-01-97")

    resp = await http_client.post(
        "/api/v1/inventory/relocations/",
        headers=scoped_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "from_location_id": seeded_location.id,
            "to_location_id": dest.id,
            "quantity": 3,
            "device_source": "MANUAL",
        },
    )
    assert resp.status_code == 201


async def test_create_relocation_requires_both_locations_in_scope(
    db_session,
    http_client,
    seeded_roles,
    sample_password,
    seeded_user_orm,
    seeded_school,
    seeded_inventory_item,
    seeded_location,
):
    scoped_headers = await _create_user_with_role_and_scope(
        db_session,
        http_client,
        username="scoped_relocator_strict",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=seeded_school.id,
    )

    other_school = SchoolORM(
        id=str(uuid.uuid4()),
        name="Other School",
        district_code="DIST-999",
        is_active=True,
    )
    db_session.add(other_school)
    await db_session.flush()

    other_warehouse = WarehouseORM(
        id=str(uuid.uuid4()),
        name="Other Warehouse",
        school_id=other_school.id,
        address="Other Address",
        is_active=True,
    )
    db_session.add(other_warehouse)
    await db_session.flush()

    outside_dest = await _create_location(db_session, other_warehouse.id, "OUT-01-01")

    resp = await http_client.post(
        "/api/v1/inventory/relocations/",
        headers=scoped_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "from_location_id": seeded_location.id,
            "to_location_id": outside_dest.id,
            "quantity": 2,
            "device_source": "MANUAL",
        },
    )
    assert resp.status_code == 403


async def test_list_relocations_without_scope_returns_403(http_client, librarian_headers):
    resp = await http_client.get(
        "/api/v1/inventory/relocations/",
        headers=librarian_headers,
    )
    assert resp.status_code == 403


async def test_list_relocations_with_scoped_user_filters_results(
    db_session,
    http_client,
    admin_headers,
    seeded_roles,
    sample_password,
    seeded_user_orm,
    seeded_school,
    seeded_inventory_item,
    seeded_location,
    seeded_warehouse,
    seeded_stock_balance,
):
    scoped_headers = await _create_user_with_role_and_scope(
        db_session,
        http_client,
        username="scoped_relocator_list",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=seeded_school.id,
    )

    # In-scope relocation
    in_scope_dest = await _create_location(db_session, seeded_warehouse.id, "Z-01-96")
    in_scope_resp = await http_client.post(
        "/api/v1/inventory/relocations/",
        headers=admin_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "from_location_id": seeded_location.id,
            "to_location_id": in_scope_dest.id,
            "quantity": 1,
            "device_source": "MANUAL",
        },
    )
    assert in_scope_resp.status_code == 201
    in_scope_id = in_scope_resp.json()["relocation_id"]

    # Out-of-scope relocation (different school)
    other_school = SchoolORM(
        id=str(uuid.uuid4()),
        name="Other School List",
        district_code="DIST-998",
        is_active=True,
    )
    db_session.add(other_school)
    await db_session.flush()

    other_warehouse = WarehouseORM(
        id=str(uuid.uuid4()),
        name="Other Warehouse List",
        school_id=other_school.id,
        address="Other Address",
        is_active=True,
    )
    db_session.add(other_warehouse)
    await db_session.flush()

    other_from = await _create_location(db_session, other_warehouse.id, "OUT-01-02")
    other_to = await _create_location(db_session, other_warehouse.id, "OUT-01-03")

    other_balance = StockBalanceORM(
        id=str(uuid.uuid4()),
        item_id=seeded_inventory_item.id,
        location_id=other_from.id,
        batch_id=None,
        serial_id=None,
        status="AVAILABLE",
        quantity=10,
        is_frozen=False,
        freeze_reason=None,
        frozen_by=None,
        frozen_at=None,
    )
    db_session.add(other_balance)
    await db_session.flush()

    out_scope_resp = await http_client.post(
        "/api/v1/inventory/relocations/",
        headers=admin_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "from_location_id": other_from.id,
            "to_location_id": other_to.id,
            "quantity": 1,
            "device_source": "MANUAL",
        },
    )
    assert out_scope_resp.status_code == 201

    list_resp = await http_client.get(
        "/api/v1/inventory/relocations/",
        headers=scoped_headers,
    )
    assert list_resp.status_code == 200
    data = list_resp.json()
    ids = {item["relocation_id"] for item in data["items"]}
    assert in_scope_id in ids
    assert len(ids) == 1
