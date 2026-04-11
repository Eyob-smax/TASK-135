"""
API tests for data-scope isolation on list_resources and list_items routes.

Tests:
  1. list_resources without scope → 403
  2. list_resources with scope   → 200
  3. list_items without scope    → 403
  4. list_items with scope       → 200
  5. admin bypasses scope check  → 200
  6. scoped resource hidden from user with a different scope → filtered out from list
  7. scoped resource visible to user whose scope matches the resource owner → returned in list
  8. scoped resource returns 403 on GET /{id} for user with a different scope
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from district_console.application.auth_service import AuthService
from district_console.infrastructure.orm import (
    ClassORM,
    DepartmentORM,
    IndividualORM,
    InventoryItemORM,
    LocationORM,
    PermissionORM,
    ResourceORM,
    RolePermissionORM,
    StockBalanceORM,
    SchoolORM,
    ScopeAssignmentORM,
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
    """Create a user with the given role and one scope assignment; return auth headers."""
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


async def _create_school_with_warehouse_and_location(db_session, suffix: str) -> tuple[SchoolORM, WarehouseORM, LocationORM]:
    school = SchoolORM(
        id=str(uuid.uuid4()),
        name=f"Scoped School {suffix}",
        district_code=f"DIST-{suffix}",
        is_active=True,
    )
    db_session.add(school)
    await db_session.flush()

    warehouse = WarehouseORM(
        id=str(uuid.uuid4()),
        name=f"Scoped Warehouse {suffix}",
        school_id=school.id,
        address=f"Address {suffix}",
        is_active=True,
    )
    db_session.add(warehouse)
    await db_session.flush()

    location = LocationORM(
        id=str(uuid.uuid4()),
        warehouse_id=warehouse.id,
        zone="S",
        aisle="01",
        bin_label=f"S-01-{suffix}",
        is_active=True,
    )
    db_session.add(location)
    await db_session.flush()
    return school, warehouse, location


async def _create_scope_hierarchy(db_session, school_id: str, suffix: str) -> tuple[DepartmentORM, ClassORM, IndividualORM]:
    department = DepartmentORM(
        id=str(uuid.uuid4()),
        school_id=school_id,
        name=f"Dept {suffix}",
        is_active=True,
    )
    db_session.add(department)
    await db_session.flush()

    class_orm = ClassORM(
        id=str(uuid.uuid4()),
        department_id=department.id,
        name=f"Class {suffix}",
        teacher_id=None,
        is_active=True,
    )
    db_session.add(class_orm)
    await db_session.flush()

    individual = IndividualORM(
        id=str(uuid.uuid4()),
        class_id=class_orm.id,
        display_name=f"Individual {suffix}",
        user_id=None,
    )
    db_session.add(individual)
    await db_session.flush()
    return department, class_orm, individual


async def test_list_resources_without_scope_returns_403(
    http_client, librarian_headers
):
    """A LIBRARIAN user with no scope assignments must receive 403 on GET /resources/."""
    resp = await http_client.get("/api/v1/resources/", headers=librarian_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_list_resources_with_scope_returns_200(
    db_session, http_client, seeded_roles, sample_password, seeded_user_orm, seeded_school
):
    """A LIBRARIAN user with a SCHOOL scope assignment must receive 200 on GET /resources/."""
    headers = await _create_user_with_role_and_scope(
        db_session, http_client,
        username="scoped_librarian",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=seeded_school.id,
    )
    resp = await http_client.get("/api/v1/resources/", headers=headers)
    assert resp.status_code == 200


async def test_list_items_without_scope_returns_403(
    http_client, librarian_headers
):
    """A LIBRARIAN user with no scope assignments must receive 403 on GET /inventory/items/."""
    resp = await http_client.get("/api/v1/inventory/items/", headers=librarian_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_list_items_with_scope_returns_200(
    db_session, http_client, seeded_roles, sample_password, seeded_user_orm, seeded_school
):
    """A LIBRARIAN user with a SCHOOL scope must receive 200 on GET /inventory/items/."""
    headers = await _create_user_with_role_and_scope(
        db_session, http_client,
        username="scoped_librarian_inv",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=seeded_school.id,
    )
    resp = await http_client.get("/api/v1/inventory/items/", headers=headers)
    assert resp.status_code == 200


async def test_admin_list_resources_bypasses_scope(
    http_client, admin_headers
):
    """An ADMINISTRATOR user with no explicit scope must still receive 200 on GET /resources/."""
    resp = await http_client.get("/api/v1/resources/", headers=admin_headers)
    assert resp.status_code == 200


async def test_list_count_sessions_without_scope_returns_403(http_client, librarian_headers):
    resp = await http_client.get("/api/v1/inventory/count-sessions/", headers=librarian_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_list_count_sessions_with_department_scope_returns_200(
    db_session,
    http_client,
    admin_headers,
    seeded_roles,
    sample_password,
    seeded_user_orm,
    seeded_school,
    seeded_warehouse,
):
    await _create_scope_hierarchy(db_session, seeded_school.id, "D1")

    open_resp = await http_client.post(
        "/api/v1/inventory/count-sessions/",
        headers=admin_headers,
        json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
    )
    assert open_resp.status_code == 201

    dept, _, _ = await _create_scope_hierarchy(db_session, seeded_school.id, "D2")
    headers = await _create_user_with_role_and_scope(
        db_session,
        http_client,
        username="dept_scope_librarian",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="DEPARTMENT",
        scope_ref_id=dept.id,
    )

    resp = await http_client.get("/api/v1/inventory/count-sessions/", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


async def test_list_count_sessions_with_class_scope_returns_200(
    db_session,
    http_client,
    admin_headers,
    seeded_roles,
    sample_password,
    seeded_user_orm,
    seeded_school,
    seeded_warehouse,
):
    open_resp = await http_client.post(
        "/api/v1/inventory/count-sessions/",
        headers=admin_headers,
        json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
    )
    assert open_resp.status_code == 201

    _, class_orm, _ = await _create_scope_hierarchy(db_session, seeded_school.id, "C1")
    headers = await _create_user_with_role_and_scope(
        db_session,
        http_client,
        username="class_scope_librarian",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="CLASS",
        scope_ref_id=class_orm.id,
    )

    resp = await http_client.get("/api/v1/inventory/count-sessions/", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


async def test_list_count_sessions_with_individual_scope_returns_200(
    db_session,
    http_client,
    admin_headers,
    seeded_roles,
    sample_password,
    seeded_user_orm,
    seeded_school,
    seeded_warehouse,
):
    open_resp = await http_client.post(
        "/api/v1/inventory/count-sessions/",
        headers=admin_headers,
        json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
    )
    assert open_resp.status_code == 201

    _, _, individual = await _create_scope_hierarchy(db_session, seeded_school.id, "I1")
    headers = await _create_user_with_role_and_scope(
        db_session,
        http_client,
        username="individual_scope_librarian",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="INDIVIDUAL",
        scope_ref_id=individual.id,
    )

    resp = await http_client.get("/api/v1/inventory/count-sessions/", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


async def test_get_count_session_outside_scope_returns_403(
    db_session,
    http_client,
    admin_headers,
    seeded_roles,
    sample_password,
    seeded_user_orm,
    seeded_warehouse,
):
    open_resp = await http_client.post(
        "/api/v1/inventory/count-sessions/",
        headers=admin_headers,
        json={"mode": "OPEN", "warehouse_id": seeded_warehouse.id},
    )
    assert open_resp.status_code == 201
    session_id = open_resp.json()["session_id"]

    other_school, _, _ = await _create_school_with_warehouse_and_location(db_session, "201")
    scoped_headers = await _create_user_with_role_and_scope(
        db_session,
        http_client,
        username="count_scope_librarian",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=other_school.id,
    )

    resp = await http_client.get(
        f"/api/v1/inventory/count-sessions/{session_id}",
        headers=scoped_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_list_ledger_without_scope_returns_403(http_client, librarian_headers):
    resp = await http_client.get("/api/v1/inventory/ledger/", headers=librarian_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_list_ledger_outside_scope_filters_entries(
    db_session,
    http_client,
    admin_headers,
    seeded_roles,
    sample_password,
    seeded_user_orm,
    seeded_inventory_item,
    seeded_location,
):
    create_entry = await http_client.post(
        "/api/v1/inventory/ledger/adjustment",
        headers=admin_headers,
        json={
            "item_id": seeded_inventory_item.id,
            "location_id": seeded_location.id,
            "quantity_delta": 1,
            "reason_code": "RESTOCK",
        },
    )
    assert create_entry.status_code == 201

    other_school, _, _ = await _create_school_with_warehouse_and_location(db_session, "202")
    scoped_headers = await _create_user_with_role_and_scope(
        db_session,
        http_client,
        username="ledger_scope_librarian",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=other_school.id,
    )

    resp = await http_client.get("/api/v1/inventory/ledger/", headers=scoped_headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 0
    assert payload["items"] == []


async def test_freeze_stock_outside_scope_returns_403(
    db_session,
    http_client,
    seeded_roles,
    sample_password,
    seeded_user_orm,
):
    scoped_school, _, _ = await _create_school_with_warehouse_and_location(db_session, "301")
    _, _, out_loc = await _create_school_with_warehouse_and_location(db_session, "302")

    item = InventoryItemORM(
        id=str(uuid.uuid4()),
        sku="SC-FRZ-001",
        name="Scoped Freeze Item",
        description="",
        unit_cost="1.00",
        created_by=seeded_user_orm.id,
        created_at=datetime.utcnow().isoformat(),
    )
    db_session.add(item)
    await db_session.flush()

    balance = StockBalanceORM(
        id=str(uuid.uuid4()),
        item_id=item.id,
        location_id=out_loc.id,
        batch_id=None,
        serial_id=None,
        status="AVAILABLE",
        quantity=10,
        is_frozen=False,
        freeze_reason=None,
        frozen_by=None,
        frozen_at=None,
    )
    db_session.add(balance)
    await db_session.flush()

    headers = await _create_user_with_role_and_scope(
        db_session,
        http_client,
        username="scope_freeze_denied",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=scoped_school.id,
    )

    resp = await http_client.post(
        f"/api/v1/inventory/stock/{balance.id}/freeze",
        headers=headers,
        json={"reason": "Out of scope"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_unfreeze_stock_outside_scope_returns_403(
    db_session,
    http_client,
    seeded_roles,
    sample_password,
    seeded_user_orm,
):
    scoped_school, _, _ = await _create_school_with_warehouse_and_location(db_session, "311")
    _, _, out_loc = await _create_school_with_warehouse_and_location(db_session, "312")

    item = InventoryItemORM(
        id=str(uuid.uuid4()),
        sku="SC-UNF-001",
        name="Scoped Unfreeze Item",
        description="",
        unit_cost="1.00",
        created_by=seeded_user_orm.id,
        created_at=datetime.utcnow().isoformat(),
    )
    db_session.add(item)
    await db_session.flush()

    balance = StockBalanceORM(
        id=str(uuid.uuid4()),
        item_id=item.id,
        location_id=out_loc.id,
        batch_id=None,
        serial_id=None,
        status="AVAILABLE",
        quantity=10,
        is_frozen=True,
        freeze_reason="Seeded",
        frozen_by=seeded_user_orm.id,
        frozen_at=datetime.utcnow().isoformat(),
    )
    db_session.add(balance)
    await db_session.flush()

    headers = await _create_user_with_role_and_scope(
        db_session,
        http_client,
        username="scope_unfreeze_denied",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=scoped_school.id,
    )

    resp = await http_client.post(
        f"/api/v1/inventory/stock/{balance.id}/unfreeze",
        headers=headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_adjustment_outside_scope_returns_403(
    db_session,
    http_client,
    seeded_roles,
    sample_password,
    seeded_user_orm,
):
    scoped_school, _, _ = await _create_school_with_warehouse_and_location(db_session, "321")
    _, _, out_loc = await _create_school_with_warehouse_and_location(db_session, "322")

    item = InventoryItemORM(
        id=str(uuid.uuid4()),
        sku="SC-ADJ-001",
        name="Scoped Adjustment Item",
        description="",
        unit_cost="1.00",
        created_by=seeded_user_orm.id,
        created_at=datetime.utcnow().isoformat(),
    )
    db_session.add(item)
    await db_session.flush()

    headers = await _create_user_with_role_and_scope(
        db_session,
        http_client,
        username="scope_adjust_denied",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=scoped_school.id,
    )

    resp = await http_client.post(
        "/api/v1/inventory/ledger/adjustment",
        headers=headers,
        json={
            "item_id": item.id,
            "location_id": out_loc.id,
            "quantity_delta": 1,
            "reason_code": "RESTOCK",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_correction_outside_scope_returns_403(
    db_session,
    http_client,
    admin_headers,
    seeded_roles,
    sample_password,
    seeded_user_orm,
):
    scoped_school, _, _ = await _create_school_with_warehouse_and_location(db_session, "331")
    _, _, out_loc = await _create_school_with_warehouse_and_location(db_session, "332")

    item = InventoryItemORM(
        id=str(uuid.uuid4()),
        sku="SC-COR-001",
        name="Scoped Correction Item",
        description="",
        unit_cost="1.00",
        created_by=seeded_user_orm.id,
        created_at=datetime.utcnow().isoformat(),
    )
    db_session.add(item)
    await db_session.flush()

    create_entry = await http_client.post(
        "/api/v1/inventory/ledger/adjustment",
        headers=admin_headers,
        json={
            "item_id": item.id,
            "location_id": out_loc.id,
            "quantity_delta": 2,
            "reason_code": "RESTOCK",
        },
    )
    assert create_entry.status_code == 201
    entry_id = create_entry.json()["entry_id"]

    headers = await _create_user_with_role_and_scope(
        db_session,
        http_client,
        username="scope_correction_denied",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=scoped_school.id,
    )

    resp = await http_client.post(
        f"/api/v1/inventory/ledger/correction/{entry_id}",
        headers=headers,
        json={"reason_code": "CORRECTION"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_approve_count_session_outside_scope_returns_403(
    db_session,
    http_client,
    admin_headers,
    seeded_roles,
    sample_password,
    seeded_user_orm,
    seeded_warehouse,
):
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

    # Ensure the REVIEWER role can pass permission checks so scope checks are exercised.
    perm = await db_session.execute(
        select(PermissionORM).where(PermissionORM.name == "inventory.approve_count")
    )
    approve_perm = perm.scalar_one_or_none()
    assert approve_perm is not None
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

    other_school, _, _ = await _create_school_with_warehouse_and_location(db_session, "341")
    headers = await _create_user_with_role_and_scope(
        db_session,
        http_client,
        username="scope_approve_denied",
        password=sample_password,
        role_orm=seeded_roles["REVIEWER"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=other_school.id,
    )

    resp = await http_client.post(
        f"/api/v1/inventory/count-sessions/{session_id}/approve",
        headers=headers,
        json={"notes": "Scoped reviewer"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


# ---------------------------------------------------------------------------
# Resource object-level scope isolation (Tests 6, 7, 8)
# ---------------------------------------------------------------------------

async def _create_scoped_resource(db_session, created_by_id: str, scope_ref_id: str) -> ResourceORM:
    """Insert a ResourceORM with an explicit owner_scope_ref_id."""
    import hashlib
    content = f"scoped-resource-{scope_ref_id}".encode()
    fingerprint = hashlib.sha256(content).hexdigest()
    dedup_key = hashlib.sha256((fingerprint + scope_ref_id).encode()).hexdigest()
    now = datetime.utcnow().isoformat()
    resource = ResourceORM(
        id=str(uuid.uuid4()),
        title=f"Scoped Resource for {scope_ref_id[:8]}",
        resource_type="BOOK",
        status="DRAFT",
        file_fingerprint=fingerprint,
        isbn=None,
        dedup_key=dedup_key,
        created_by=created_by_id,
        created_at=now,
        updated_at=now,
        owner_scope_type="SCHOOL",
        owner_scope_ref_id=scope_ref_id,
    )
    db_session.add(resource)
    await db_session.flush()
    return resource


async def test_scoped_resource_hidden_from_different_scope_user(
    db_session,
    http_client,
    seeded_roles,
    sample_password,
    seeded_user_orm,
):
    """A resource owned by school_A must not appear in list for a user scoped to school_B."""
    school_a, _, _ = await _create_school_with_warehouse_and_location(db_session, "RSC-A")
    school_b, _, _ = await _create_school_with_warehouse_and_location(db_session, "RSC-B")

    await _create_scoped_resource(db_session, seeded_user_orm.id, school_a.id)

    headers_b = await _create_user_with_role_and_scope(
        db_session, http_client,
        username="res_scope_b_user",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=school_b.id,
    )

    resp = await http_client.get("/api/v1/resources/", headers=headers_b)
    assert resp.status_code == 200
    resource_ids = [item["resource_id"] for item in resp.json()["items"]]
    # The school_A-scoped resource must not be visible to a school_B user.
    for rid in resource_ids:
        result = await db_session.execute(
            select(ResourceORM).where(ResourceORM.id == rid)
        )
        orm = result.scalar_one_or_none()
        assert orm is not None
        assert orm.owner_scope_ref_id != school_a.id, (
            f"Resource {rid} owned by school_A leaked to school_B user"
        )


async def test_scoped_resource_visible_to_matching_scope_user(
    db_session,
    http_client,
    seeded_roles,
    sample_password,
    seeded_user_orm,
):
    """A resource owned by school_A must appear in the list for a user scoped to school_A."""
    school_a, _, _ = await _create_school_with_warehouse_and_location(db_session, "RSC-C")

    resource = await _create_scoped_resource(db_session, seeded_user_orm.id, school_a.id)

    headers_a = await _create_user_with_role_and_scope(
        db_session, http_client,
        username="res_scope_a_user",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=school_a.id,
    )

    resp = await http_client.get("/api/v1/resources/", headers=headers_a)
    assert resp.status_code == 200
    resource_ids = [item["resource_id"] for item in resp.json()["items"]]
    assert resource.id in resource_ids, (
        "Resource scoped to school_A was not returned for school_A user"
    )


async def test_scoped_resource_get_returns_403_for_different_scope_user(
    db_session,
    http_client,
    seeded_roles,
    sample_password,
    seeded_user_orm,
):
    """GET /resources/{id} for a resource owned by school_A must return 403 for a school_B user."""
    school_a, _, _ = await _create_school_with_warehouse_and_location(db_session, "RSC-D")
    school_b, _, _ = await _create_school_with_warehouse_and_location(db_session, "RSC-E")

    resource = await _create_scoped_resource(db_session, seeded_user_orm.id, school_a.id)

    headers_b = await _create_user_with_role_and_scope(
        db_session, http_client,
        username="res_get_scope_b_user",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=school_b.id,
    )

    resp = await http_client.get(f"/api/v1/resources/{resource.id}", headers=headers_b)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_scoped_resource_update_denied_for_different_scope_user(
    db_session,
    http_client,
    seeded_roles,
    sample_password,
    seeded_user_orm,
):
    """PUT /resources/{id} for a resource owned by school_A must return 403 for a school_B user."""
    school_a, _, _ = await _create_school_with_warehouse_and_location(db_session, "RSC-F")
    school_b, _, _ = await _create_school_with_warehouse_and_location(db_session, "RSC-G")

    resource = await _create_scoped_resource(db_session, seeded_user_orm.id, school_a.id)

    headers_b = await _create_user_with_role_and_scope(
        db_session, http_client,
        username="res_put_scope_b_user",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=school_b.id,
    )

    resp = await http_client.put(
        f"/api/v1/resources/{resource.id}",
        headers=headers_b,
        json={"title": "Attempted override"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


# ---------------------------------------------------------------------------
# Mutation endpoint object-level scope enforcement (Tests 9–13 + scope-type collision)
# ---------------------------------------------------------------------------

async def test_submit_review_denied_for_different_scope_user(
    db_session,
    http_client,
    seeded_roles,
    sample_password,
    seeded_user_orm,
):
    """POST /resources/{id}/submit-review for school_A resource must return 403 for school_B user."""
    school_a, _, _ = await _create_school_with_warehouse_and_location(db_session, "MUT-A1")
    school_b, _, _ = await _create_school_with_warehouse_and_location(db_session, "MUT-B1")
    resource = await _create_scoped_resource(db_session, seeded_user_orm.id, school_a.id)

    headers_b = await _create_user_with_role_and_scope(
        db_session, http_client,
        username="submit_scope_b_user",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=school_b.id,
    )

    resp = await http_client.post(
        f"/api/v1/resources/{resource.id}/submit-review",
        headers=headers_b,
        json={"reviewer_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_publish_denied_for_different_scope_user(
    db_session,
    http_client,
    seeded_roles,
    sample_password,
    seeded_user_orm,
):
    """POST /resources/{id}/publish for school_A resource must return 403 for school_B user."""
    school_a, _, _ = await _create_school_with_warehouse_and_location(db_session, "MUT-A2")
    school_b, _, _ = await _create_school_with_warehouse_and_location(db_session, "MUT-B2")
    resource = await _create_scoped_resource(db_session, seeded_user_orm.id, school_a.id)

    headers_b = await _create_user_with_role_and_scope(
        db_session, http_client,
        username="publish_scope_b_user",
        password=sample_password,
        role_orm=seeded_roles["REVIEWER"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=school_b.id,
    )

    resp = await http_client.post(
        f"/api/v1/resources/{resource.id}/publish",
        headers=headers_b,
        json={"reviewer_notes": "attempt"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_unpublish_denied_for_different_scope_user(
    db_session,
    http_client,
    seeded_roles,
    sample_password,
    seeded_user_orm,
):
    """POST /resources/{id}/unpublish for school_A resource must return 403 for school_B user."""
    school_a, _, _ = await _create_school_with_warehouse_and_location(db_session, "MUT-A3")
    school_b, _, _ = await _create_school_with_warehouse_and_location(db_session, "MUT-B3")
    resource = await _create_scoped_resource(db_session, seeded_user_orm.id, school_a.id)

    headers_b = await _create_user_with_role_and_scope(
        db_session, http_client,
        username="unpublish_scope_b_user",
        password=sample_password,
        role_orm=seeded_roles["REVIEWER"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=school_b.id,
    )

    resp = await http_client.post(
        f"/api/v1/resources/{resource.id}/unpublish",
        headers=headers_b,
        json={"reviewer_notes": "attempt"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_classify_denied_for_different_scope_user(
    db_session,
    http_client,
    seeded_roles,
    sample_password,
    seeded_user_orm,
):
    """POST /resources/{id}/classify for school_A resource must return 403 for school_B user."""
    school_a, _, _ = await _create_school_with_warehouse_and_location(db_session, "MUT-A4")
    school_b, _, _ = await _create_school_with_warehouse_and_location(db_session, "MUT-B4")
    resource = await _create_scoped_resource(db_session, seeded_user_orm.id, school_a.id)

    headers_b = await _create_user_with_role_and_scope(
        db_session, http_client,
        username="classify_scope_b_user",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=school_b.id,
    )

    resp = await http_client.post(
        f"/api/v1/resources/{resource.id}/classify",
        headers=headers_b,
        json={"min_age": 6, "max_age": 10, "timeliness_type": "EVERGREEN"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_request_allocation_denied_for_different_scope_user(
    db_session,
    http_client,
    seeded_roles,
    sample_password,
    seeded_user_orm,
):
    """POST /resources/{id}/request-allocation for school_A resource must return 403 for school_B user."""
    school_a, _, _ = await _create_school_with_warehouse_and_location(db_session, "MUT-A5")
    school_b, _, _ = await _create_school_with_warehouse_and_location(db_session, "MUT-B5")
    resource = await _create_scoped_resource(db_session, seeded_user_orm.id, school_a.id)

    headers_b = await _create_user_with_role_and_scope(
        db_session, http_client,
        username="alloc_scope_b_user",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="SCHOOL",
        scope_ref_id=school_b.id,
    )

    resp = await http_client.post(
        f"/api/v1/resources/{resource.id}/request-allocation",
        headers=headers_b,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_scope_type_collision_does_not_leak_resource(
    db_session,
    http_client,
    seeded_roles,
    sample_password,
    seeded_user_orm,
):
    """
    A resource scoped to (SCHOOL, id_X) must NOT be visible to a user whose scope
    is (INDIVIDUAL, id_X) — even though the ref_id UUID is the same.
    This validates that scope-type is included in the authorization check.
    """
    import hashlib
    # Use the same UUID for both scope_ref_id values
    shared_uuid = str(uuid.uuid4())

    # Create resource owned by SCHOOL scope with shared_uuid
    content = f"collision-resource-{shared_uuid}".encode()
    fingerprint = hashlib.sha256(content).hexdigest()
    dedup_key = hashlib.sha256((fingerprint + shared_uuid).encode()).hexdigest()
    now = datetime.utcnow().isoformat()
    resource = ResourceORM(
        id=str(uuid.uuid4()),
        title="Scope-Type Collision Resource",
        resource_type="BOOK",
        status="DRAFT",
        file_fingerprint=fingerprint,
        isbn=None,
        dedup_key=dedup_key,
        created_by=seeded_user_orm.id,
        created_at=now,
        updated_at=now,
        owner_scope_type="SCHOOL",
        owner_scope_ref_id=shared_uuid,
    )
    db_session.add(resource)
    await db_session.flush()

    # Create a user with scope (INDIVIDUAL, shared_uuid) — same UUID, different type
    headers_individual = await _create_user_with_role_and_scope(
        db_session, http_client,
        username="individual_collision_user",
        password=sample_password,
        role_orm=seeded_roles["LIBRARIAN"],
        seeded_user_orm=seeded_user_orm,
        scope_type="INDIVIDUAL",
        scope_ref_id=shared_uuid,
    )

    # Resource must NOT appear in the list for this user
    resp = await http_client.get("/api/v1/resources/", headers=headers_individual)
    assert resp.status_code == 200
    resource_ids = [item["resource_id"] for item in resp.json()["items"]]
    assert resource.id not in resource_ids, (
        "Resource scoped to SCHOOL leaked to user with INDIVIDUAL scope for the same ref_id"
    )

    # Resource must also be denied on direct GET
    get_resp = await http_client.get(
        f"/api/v1/resources/{resource.id}", headers=headers_individual
    )
    assert get_resp.status_code == 403
    assert get_resp.json()["error"]["code"] == "SCOPE_VIOLATION"
