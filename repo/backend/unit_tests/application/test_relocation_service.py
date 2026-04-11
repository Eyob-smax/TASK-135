"""
Unit tests for RelocationService — intra-warehouse stock moves.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.relocation_service import RelocationService
from district_console.domain.enums import DeviceSource, StockStatus
from district_console.domain.exceptions import (
    DomainValidationError,
    InsufficientStockError,
    StockFrozenError,
)
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.lock_manager import LockManager
from district_console.infrastructure.orm import LocationORM, StockBalanceORM, WarehouseORM
from district_console.infrastructure.repositories import (
    AuditRepository,
    InventoryRepository,
    LedgerRepository,
    LockRepository,
    RelocationRepository,
)


def _make_service():
    return RelocationService(
        InventoryRepository(),
        LedgerRepository(),
        LockManager(LockRepository()),
        AuditWriter(AuditRepository()),
        RelocationRepository(),
    )


NOW = datetime(2024, 6, 1, 10, 0, 0)


async def _seed_second_location(db_session, seeded_warehouse):
    """Add a second location for relocation target."""
    loc2 = LocationORM(
        id=str(uuid.uuid4()),
        warehouse_id=seeded_warehouse.id,
        zone="B",
        aisle="02",
        bin_label="B-02-01",
        is_active=True,
    )
    db_session.add(loc2)
    await db_session.flush()
    return loc2


async def test_relocate_creates_two_ledger_entries_and_updates_balances(
    db_session: AsyncSession, seeded_inventory_item, seeded_location,
    seeded_stock_balance, seeded_warehouse, seeded_user_orm
):
    svc = _make_service()
    loc2 = await _seed_second_location(db_session, seeded_warehouse)
    actor_id = uuid.UUID(seeded_user_orm.id)
    relocation = await svc.relocate(
        db_session,
        item_id=uuid.UUID(seeded_inventory_item.id),
        from_location_id=uuid.UUID(seeded_location.id),
        to_location_id=uuid.UUID(loc2.id),
        quantity=30,
        operator_id=actor_id,
        device_source=DeviceSource.MANUAL,
        now=NOW,
    )
    assert relocation.quantity == 30
    assert relocation.ledger_debit_entry_id is not None
    assert relocation.ledger_credit_entry_id is not None

    # Verify stock balances updated
    inv_repo = InventoryRepository()
    from_bal = await inv_repo.get_stock_balance(
        db_session, uuid.UUID(seeded_inventory_item.id), uuid.UUID(seeded_location.id)
    )
    to_bal = await inv_repo.get_stock_balance(
        db_session, uuid.UUID(seeded_inventory_item.id), uuid.UUID(loc2.id)
    )
    assert from_bal.quantity == 70   # 100 - 30
    assert to_bal.quantity == 30


async def test_relocate_same_location_raises_validation_error(
    db_session: AsyncSession,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
    seeded_user_orm,
):
    svc = _make_service()
    loc_id = uuid.UUID(seeded_location.id)
    actor_id = uuid.UUID(seeded_user_orm.id)
    with pytest.raises(DomainValidationError):
        await svc.relocate(
            db_session,
            item_id=uuid.UUID(seeded_inventory_item.id),
            from_location_id=loc_id,
            to_location_id=loc_id,
            quantity=10,
            operator_id=actor_id,
            device_source=DeviceSource.MANUAL,
            now=NOW,
        )


async def test_relocate_zero_quantity_raises_validation_error(
    db_session: AsyncSession, seeded_inventory_item, seeded_location,
    seeded_stock_balance, seeded_warehouse, seeded_user_orm
):
    svc = _make_service()
    loc2 = await _seed_second_location(db_session, seeded_warehouse)
    actor_id = uuid.UUID(seeded_user_orm.id)
    with pytest.raises(DomainValidationError):
        await svc.relocate(
            db_session,
            item_id=uuid.UUID(seeded_inventory_item.id),
            from_location_id=uuid.UUID(seeded_location.id),
            to_location_id=uuid.UUID(loc2.id),
            quantity=0,
            operator_id=actor_id,
            device_source=DeviceSource.USB_SCANNER,
            now=NOW,
        )


async def test_relocate_cross_warehouse_raises_validation_error(
    db_session: AsyncSession,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
    seeded_school,
    seeded_user_orm,
):
    svc = _make_service()
    actor_id = uuid.UUID(seeded_user_orm.id)

    other_warehouse = WarehouseORM(
        id=str(uuid.uuid4()),
        name="Other Warehouse",
        school_id=seeded_school.id,
        address="Other Address",
        is_active=True,
    )
    db_session.add(other_warehouse)
    await db_session.flush()

    outside_location = LocationORM(
        id=str(uuid.uuid4()),
        warehouse_id=other_warehouse.id,
        zone="C",
        aisle="03",
        bin_label="C-03-01",
        is_active=True,
    )
    db_session.add(outside_location)
    await db_session.flush()

    with pytest.raises(DomainValidationError):
        await svc.relocate(
            db_session,
            item_id=uuid.UUID(seeded_inventory_item.id),
            from_location_id=uuid.UUID(seeded_location.id),
            to_location_id=uuid.UUID(outside_location.id),
            quantity=1,
            operator_id=actor_id,
            device_source=DeviceSource.MANUAL,
            now=NOW,
        )


async def test_relocate_insufficient_stock_raises_error(
    db_session: AsyncSession, seeded_inventory_item, seeded_location,
    seeded_stock_balance, seeded_warehouse, seeded_user_orm
):
    svc = _make_service()
    loc2 = await _seed_second_location(db_session, seeded_warehouse)
    actor_id = uuid.UUID(seeded_user_orm.id)
    with pytest.raises(InsufficientStockError):
        await svc.relocate(
            db_session,
            item_id=uuid.UUID(seeded_inventory_item.id),
            from_location_id=uuid.UUID(seeded_location.id),
            to_location_id=uuid.UUID(loc2.id),
            quantity=500,  # More than the 100 in stock
            operator_id=actor_id,
            device_source=DeviceSource.MANUAL,
            now=NOW,
        )


async def test_relocate_frozen_stock_raises_stock_frozen_error(
    db_session: AsyncSession, seeded_inventory_item, seeded_location,
    seeded_stock_balance, seeded_warehouse, seeded_user_orm
):
    from district_console.application.inventory_service import InventoryService
    from district_console.infrastructure.repositories import LedgerRepository as LR
    inv_svc = InventoryService(
        InventoryRepository(), LR(),
        AuditWriter(AuditRepository()), LockManager(LockRepository()),
    )
    actor = uuid.UUID(seeded_user_orm.id)
    await inv_svc.freeze_stock(
        db_session, uuid.UUID(seeded_stock_balance.id), "Locked for test", actor, NOW
    )

    svc = _make_service()
    loc2 = await _seed_second_location(db_session, seeded_warehouse)
    with pytest.raises(StockFrozenError):
        await svc.relocate(
            db_session,
            item_id=uuid.UUID(seeded_inventory_item.id),
            from_location_id=uuid.UUID(seeded_location.id),
            to_location_id=uuid.UUID(loc2.id),
            quantity=10,
            operator_id=actor,
            device_source=DeviceSource.MANUAL,
            now=NOW,
        )


async def test_relocate_uses_batch_partition_and_status(
    db_session: AsyncSession,
    seeded_inventory_item,
    seeded_location,
    seeded_warehouse,
    seeded_user_orm,
):
    svc = _make_service()
    loc2 = await _seed_second_location(db_session, seeded_warehouse)
    actor_id = uuid.UUID(seeded_user_orm.id)

    db_session.add(
        StockBalanceORM(
            id=str(uuid.uuid4()),
            item_id=seeded_inventory_item.id,
            location_id=seeded_location.id,
            batch_id="BATCH-42",
            serial_id=None,
            status=StockStatus.AVAILABLE.value,
            quantity=25,
            is_frozen=False,
            freeze_reason=None,
            frozen_by=None,
            frozen_at=None,
        )
    )
    await db_session.flush()

    relocation = await svc.relocate(
        db_session,
        item_id=uuid.UUID(seeded_inventory_item.id),
        from_location_id=uuid.UUID(seeded_location.id),
        to_location_id=uuid.UUID(loc2.id),
        quantity=10,
        operator_id=actor_id,
        device_source=DeviceSource.MANUAL,
        now=NOW,
        batch_id="BATCH-42",
        status=StockStatus.AVAILABLE,
    )
    assert relocation.quantity == 10

    inv_repo = InventoryRepository()
    from_partition = await inv_repo.get_stock_balance(
        db_session,
        uuid.UUID(seeded_inventory_item.id),
        uuid.UUID(seeded_location.id),
        batch_id="BATCH-42",
        serial_id=None,
        status=StockStatus.AVAILABLE.value,
    )
    to_partition = await inv_repo.get_stock_balance(
        db_session,
        uuid.UUID(seeded_inventory_item.id),
        uuid.UUID(loc2.id),
        batch_id="BATCH-42",
        serial_id=None,
        status=StockStatus.AVAILABLE.value,
    )
    assert from_partition is not None
    assert from_partition.quantity == 15
    assert to_partition is not None
    assert to_partition.quantity == 10
