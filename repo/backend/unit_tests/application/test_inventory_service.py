"""
Unit tests for InventoryService — items, stock freeze/unfreeze, and ledger.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.inventory_service import InventoryService
from district_console.domain.exceptions import (
    AppendOnlyViolationError,
    DomainValidationError,
    InsufficientStockError,
    StockFrozenError,
)
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.checkpoint_store import CheckpointStore
from district_console.infrastructure.lock_manager import LockManager
from district_console.infrastructure.repositories import (
    AuditRepository,
    CheckpointRepository,
    InventoryRepository,
    LedgerRepository,
    LockRepository,
)


def _make_service():
    audit_writer = AuditWriter(AuditRepository())
    lock_manager = LockManager(LockRepository())
    return InventoryService(
        InventoryRepository(),
        LedgerRepository(),
        audit_writer,
        lock_manager,
    )


NOW = datetime(2024, 6, 1, 10, 0, 0)
ACTOR = uuid.uuid4()


async def test_create_item_stores_decimal_as_string(db_session: AsyncSession, seeded_user_orm):
    svc = _make_service()
    item = await svc.create_item(
        db_session, sku="SKU-001", name="Widget", description="A widget",
        unit_cost=Decimal("12.50"), created_by=uuid.UUID(seeded_user_orm.id), now=NOW
    )
    assert item.unit_cost == Decimal("12.50")
    assert item.sku == "SKU-001"


async def test_create_item_duplicate_sku_raises_conflict(db_session: AsyncSession, seeded_user_orm):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    await svc.create_item(db_session, "DUP-SKU", "Item A", "", Decimal("1.00"), actor, NOW)
    with pytest.raises(DomainValidationError):
        await svc.create_item(db_session, "DUP-SKU", "Item B", "", Decimal("2.00"), actor, NOW)


async def test_freeze_stock_sets_is_frozen_and_reason(
    db_session: AsyncSession, seeded_stock_balance, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    import uuid as _uuid
    balance_id = _uuid.UUID(seeded_stock_balance.id)
    balance = await svc.freeze_stock(db_session, balance_id, "Audit hold", actor, NOW)
    assert balance.is_frozen is True
    assert balance.freeze_reason == "Audit hold"


async def test_unfreeze_stock_clears_frozen_state(
    db_session: AsyncSession, seeded_stock_balance, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    import uuid as _uuid
    balance_id = _uuid.UUID(seeded_stock_balance.id)
    await svc.freeze_stock(db_session, balance_id, "Hold", actor, NOW)
    balance = await svc.unfreeze_stock(db_session, balance_id, actor, NOW)
    assert balance.is_frozen is False
    assert balance.freeze_reason is None


async def test_freeze_already_frozen_raises_stock_frozen_error(
    db_session: AsyncSession, seeded_stock_balance, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    import uuid as _uuid
    balance_id = _uuid.UUID(seeded_stock_balance.id)
    await svc.freeze_stock(db_session, balance_id, "First freeze", actor, NOW)
    with pytest.raises(StockFrozenError):
        await svc.freeze_stock(db_session, balance_id, "Second freeze", actor, NOW)


async def test_add_adjustment_creates_ledger_entry_and_updates_balance(
    db_session: AsyncSession, seeded_inventory_item, seeded_location, seeded_stock_balance, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    item_id = uuid.UUID(seeded_inventory_item.id)
    location_id = uuid.UUID(seeded_location.id)

    entry = await svc.add_adjustment(
        db_session, item_id, location_id, quantity_delta=10, reason_code="RESTOCK",
        operator_id=actor, now=NOW
    )
    assert entry.quantity_delta == 10
    assert entry.quantity_after == 110  # 100 + 10


async def test_add_adjustment_negative_balance_raises_insufficient_stock(
    db_session: AsyncSession, seeded_inventory_item, seeded_location, seeded_stock_balance, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    item_id = uuid.UUID(seeded_inventory_item.id)
    location_id = uuid.UUID(seeded_location.id)

    with pytest.raises(InsufficientStockError):
        await svc.add_adjustment(
            db_session, item_id, location_id, quantity_delta=-200, reason_code="WRITE_OFF",
            operator_id=actor, now=NOW
        )


async def test_add_adjustment_uses_batch_partition_independently(
    db_session: AsyncSession,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
    seeded_user_orm,
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    item_id = uuid.UUID(seeded_inventory_item.id)
    location_id = uuid.UUID(seeded_location.id)

    batch_a_1 = await svc.add_adjustment(
        db_session,
        item_id,
        location_id,
        quantity_delta=5,
        reason_code="RESTOCK",
        operator_id=actor,
        now=NOW,
        batch_id="BATCH-A",
    )
    batch_b_1 = await svc.add_adjustment(
        db_session,
        item_id,
        location_id,
        quantity_delta=7,
        reason_code="RESTOCK",
        operator_id=actor,
        now=NOW,
        batch_id="BATCH-B",
    )
    batch_a_2 = await svc.add_adjustment(
        db_session,
        item_id,
        location_id,
        quantity_delta=3,
        reason_code="RESTOCK",
        operator_id=actor,
        now=NOW,
        batch_id="BATCH-A",
    )

    assert batch_a_1.quantity_after == 5
    assert batch_b_1.quantity_after == 7
    assert batch_a_2.quantity_after == 8


async def test_add_correction_reverses_entry_and_updates_balance(
    db_session: AsyncSession, seeded_inventory_item, seeded_location, seeded_stock_balance, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    item_id = uuid.UUID(seeded_inventory_item.id)
    location_id = uuid.UUID(seeded_location.id)

    entry = await svc.add_adjustment(
        db_session, item_id, location_id, quantity_delta=20, reason_code="INITIAL",
        operator_id=actor, now=NOW
    )
    correction = await svc.add_correction(
        db_session, entry.id, reason_code="CORRECTION", operator_id=actor, now=NOW
    )
    assert correction.quantity_delta == -20
    assert correction.reversal_of_id == entry.id


async def test_add_correction_already_reversed_raises_append_only_violation(
    db_session: AsyncSession, seeded_inventory_item, seeded_location, seeded_stock_balance, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    item_id = uuid.UUID(seeded_inventory_item.id)
    location_id = uuid.UUID(seeded_location.id)

    entry = await svc.add_adjustment(
        db_session, item_id, location_id, quantity_delta=5, reason_code="ADJ",
        operator_id=actor, now=NOW
    )
    await svc.add_correction(db_session, entry.id, "CORR", actor, NOW)
    with pytest.raises(AppendOnlyViolationError):
        await svc.add_correction(db_session, entry.id, "CORR2", actor, NOW)
