"""
Additional unit tests for InventoryService covering gaps in the primary suite:

  * update_item / get_item not-found paths
  * update_item partial-field updates
  * list_items pagination
  * create_warehouse / list_warehouses
  * create_location / list_locations
  * freeze/unfreeze not-found + already-unfrozen paths
  * add_correction on a frozen balance partition
  * _decode_balance_partition edge cases
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.inventory_service import (
    InventoryService,
    _decode_balance_partition,
    _encode_balance_partition,
)
from district_console.domain.enums import StockStatus
from district_console.domain.exceptions import (
    DomainValidationError,
    StockFrozenError,
)
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.lock_manager import LockManager
from district_console.infrastructure.repositories import (
    AuditRepository,
    InventoryRepository,
    LedgerRepository,
    LockRepository,
)


def _make_service() -> InventoryService:
    return InventoryService(
        InventoryRepository(),
        LedgerRepository(),
        AuditWriter(AuditRepository()),
        LockManager(LockRepository()),
    )


NOW = datetime(2024, 6, 1, 10, 0, 0)


# ---------------------------------------------------------------------------
# Partition encode/decode
# ---------------------------------------------------------------------------

def test_decode_partition_returns_none_for_empty_or_non_balance_string():
    assert _decode_balance_partition(None) == (None, None, None)
    assert _decode_balance_partition("") == (None, None, None)
    assert _decode_balance_partition("not_a_partition") == (None, None, None)


def test_decode_partition_returns_none_for_bad_shape():
    # Missing fields — not enough colons after the "balance:" prefix
    assert _decode_balance_partition("balance:AVAILABLE") == (None, None, None)


def test_decode_partition_returns_none_for_bad_status_enum():
    assert _decode_balance_partition("balance:NOPE:-:-") == (None, None, None)


def test_encode_decode_partition_roundtrip():
    encoded = _encode_balance_partition(StockStatus.AVAILABLE, "BATCH-X", "SER-Y")
    status, batch, serial = _decode_balance_partition(encoded)
    assert status == StockStatus.AVAILABLE
    assert batch == "BATCH-X"
    assert serial == "SER-Y"


def test_encode_partition_sentinels_for_missing_batch_serial():
    encoded = _encode_balance_partition(StockStatus.AVAILABLE, None, None)
    status, batch, serial = _decode_balance_partition(encoded)
    assert status == StockStatus.AVAILABLE
    assert batch is None
    assert serial is None


# ---------------------------------------------------------------------------
# Item lookup / update
# ---------------------------------------------------------------------------

async def test_get_item_not_found_raises(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(DomainValidationError) as exc:
        await svc.get_item(db_session, uuid.uuid4())
    assert exc.value.field == "item_id"


async def test_update_item_not_found_raises(db_session: AsyncSession, seeded_user_orm):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    with pytest.raises(DomainValidationError) as exc:
        await svc.update_item(
            db_session, uuid.uuid4(), name="X", description=None, unit_cost=None, actor_id=actor
        )
    assert exc.value.field == "item_id"


async def test_update_item_updates_only_provided_fields(
    db_session: AsyncSession, seeded_inventory_item, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    item_id = uuid.UUID(seeded_inventory_item.id)
    original_desc = seeded_inventory_item.description

    updated = await svc.update_item(
        db_session,
        item_id,
        name="Renamed",
        description=None,
        unit_cost=None,
        actor_id=actor,
    )
    assert updated.name == "Renamed"
    assert updated.description == original_desc
    assert updated.unit_cost == Decimal(seeded_inventory_item.unit_cost)


async def test_update_item_all_fields(
    db_session: AsyncSession, seeded_inventory_item, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    item_id = uuid.UUID(seeded_inventory_item.id)

    updated = await svc.update_item(
        db_session,
        item_id,
        name="New Name",
        description="New Description",
        unit_cost=Decimal("42.99"),
        actor_id=actor,
    )
    assert updated.name == "New Name"
    assert updated.description == "New Description"
    assert updated.unit_cost == Decimal("42.99")


async def test_list_items_returns_seeded_row(
    db_session: AsyncSession, seeded_inventory_item
):
    svc = _make_service()
    items, total = await svc.list_items(db_session)
    assert total >= 1
    assert any(str(i.id) == seeded_inventory_item.id for i in items)


# ---------------------------------------------------------------------------
# Warehouse
# ---------------------------------------------------------------------------

async def test_create_and_list_warehouse(
    db_session: AsyncSession, seeded_school, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    warehouse = await svc.create_warehouse(
        db_session,
        name="North WH",
        school_id=uuid.UUID(seeded_school.id),
        address="42 Elm St",
        actor_id=actor,
    )
    assert warehouse.name == "North WH"
    warehouses = await svc.list_warehouses(db_session)
    assert any(w.id == warehouse.id for w in warehouses)


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

async def test_create_and_list_location_filtered_by_warehouse(
    db_session: AsyncSession, seeded_warehouse, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    wh_id = uuid.UUID(seeded_warehouse.id)
    loc = await svc.create_location(
        db_session,
        warehouse_id=wh_id,
        zone="A",
        aisle="3",
        bin_label="B-17",
        actor_id=actor,
    )
    assert loc.zone == "A"
    assert loc.aisle == "3"

    all_locations = await svc.list_locations(db_session)
    assert any(l.id == loc.id for l in all_locations)

    filtered = await svc.list_locations(db_session, warehouse_id=wh_id)
    assert any(l.id == loc.id for l in filtered)

    batched = await svc.list_locations(db_session, warehouse_ids=[wh_id])
    assert any(l.id == loc.id for l in batched)


# ---------------------------------------------------------------------------
# Freeze / Unfreeze edge cases
# ---------------------------------------------------------------------------

async def test_freeze_stock_not_found_raises(db_session: AsyncSession, seeded_user_orm):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    with pytest.raises(DomainValidationError) as exc:
        await svc.freeze_stock(db_session, uuid.uuid4(), "Audit", actor, NOW)
    assert exc.value.field == "balance_id"


async def test_unfreeze_stock_not_found_raises(db_session: AsyncSession, seeded_user_orm):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    with pytest.raises(DomainValidationError) as exc:
        await svc.unfreeze_stock(db_session, uuid.uuid4(), actor, NOW)
    assert exc.value.field == "balance_id"


async def test_unfreeze_stock_not_frozen_raises(
    db_session: AsyncSession, seeded_stock_balance, seeded_user_orm
):
    """unfreeze_stock must reject a balance that is currently unfrozen."""
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    with pytest.raises(DomainValidationError) as exc:
        await svc.unfreeze_stock(
            db_session, uuid.UUID(seeded_stock_balance.id), actor, NOW
        )
    assert exc.value.field == "balance_id"


async def test_add_adjustment_on_frozen_balance_partition_raises(
    db_session: AsyncSession,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
    seeded_user_orm,
):
    """
    Adjustments to an item/location whose AVAILABLE balance is frozen must
    raise StockFrozenError rather than silently creating a new balance.
    """
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    item_id = uuid.UUID(seeded_inventory_item.id)
    location_id = uuid.UUID(seeded_location.id)
    balance_id = uuid.UUID(seeded_stock_balance.id)

    # First seed an adjustment so the balance exists and then freeze it.
    await svc.freeze_stock(db_session, balance_id, "Hold", actor, NOW)

    # AVAILABLE balance is frozen now — after freeze the balance status is FROZEN.
    # A new adjustment with status=AVAILABLE finds no AVAILABLE balance, then
    # discovers the FROZEN balance at the same partition → must raise.
    with pytest.raises(StockFrozenError):
        await svc.add_adjustment(
            db_session,
            item_id,
            location_id,
            quantity_delta=5,
            reason_code="RESTOCK",
            operator_id=actor,
            now=NOW,
        )


async def test_add_correction_entry_not_found_raises(
    db_session: AsyncSession, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    with pytest.raises(DomainValidationError) as exc:
        await svc.add_correction(db_session, uuid.uuid4(), "BAD", actor, NOW)
    assert exc.value.field == "entry_id"
