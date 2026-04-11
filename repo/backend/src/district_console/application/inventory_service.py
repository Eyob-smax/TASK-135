"""
Inventory service — items, warehouses, locations, stock balances, and ledger.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from district_console.domain.entities.inventory import InventoryItem, Location, StockBalance, Warehouse
from district_console.domain.entities.ledger import LedgerEntry
from district_console.domain.enums import LedgerEntryType, StockStatus
from district_console.domain.exceptions import (
    AppendOnlyViolationError,
    DomainValidationError,
    InsufficientStockError,
    StockFrozenError,
)
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.lock_manager import LockManager
from district_console.infrastructure.repositories import InventoryRepository, LedgerRepository


def _encode_balance_partition(
    status: StockStatus,
    batch_id: Optional[str],
    serial_id: Optional[str],
) -> str:
    """Encode stock-balance partition info for ledger reference_id."""
    batch = batch_id if batch_id is not None else "-"
    serial = serial_id if serial_id is not None else "-"
    return f"balance:{status.value}:{batch}:{serial}"


def _decode_balance_partition(reference_id: Optional[str]) -> tuple[Optional[StockStatus], Optional[str], Optional[str]]:
    """Decode partition info previously stored in ledger reference_id."""
    if not reference_id or not reference_id.startswith("balance:"):
        return None, None, None
    parts = reference_id.split(":", 3)
    if len(parts) != 4:
        return None, None, None
    try:
        status = StockStatus(parts[1])
    except ValueError:
        return None, None, None
    batch_id = None if parts[2] == "-" else parts[2]
    serial_id = None if parts[3] == "-" else parts[3]
    return status, batch_id, serial_id


class InventoryService:
    def __init__(
        self,
        inventory_repo: InventoryRepository,
        ledger_repo: LedgerRepository,
        audit_writer: AuditWriter,
        lock_manager: LockManager,
    ) -> None:
        self._inventory_repo = inventory_repo
        self._ledger_repo = ledger_repo
        self._audit_writer = audit_writer
        self._lock_manager = lock_manager

    # ------------------------------------------------------------------
    # InventoryItem
    # ------------------------------------------------------------------

    async def create_item(
        self,
        session: AsyncSession,
        sku: str,
        name: str,
        description: str,
        unit_cost: Decimal,
        created_by: uuid.UUID,
        now: datetime,
    ) -> InventoryItem:
        existing = await self._inventory_repo.get_item_by_sku(session, sku)
        if existing is not None:
            raise DomainValidationError(
                field="sku",
                value=sku,
                constraint=f"An inventory item with SKU '{sku}' already exists.",
            )
        item = InventoryItem(
            id=uuid.uuid4(),
            sku=sku,
            name=name,
            description=description,
            unit_cost=unit_cost,
            created_by=created_by,
            created_at=now,
        )
        await self._inventory_repo.save_item(session, item)
        await self._audit_writer.write(
            session,
            entity_type="InventoryItem",
            entity_id=item.id,
            action="ITEM_CREATED",
            actor_id=created_by,
            metadata={"sku": sku},
        )
        return item

    async def update_item(
        self,
        session: AsyncSession,
        item_id: uuid.UUID,
        name: Optional[str],
        description: Optional[str],
        unit_cost: Optional[Decimal],
        actor_id: uuid.UUID,
    ) -> InventoryItem:
        item = await self._inventory_repo.get_item_by_id(session, item_id)
        if item is None:
            raise DomainValidationError(field="item_id", value=str(item_id), constraint="Item not found.")
        if name is not None:
            item.name = name
        if description is not None:
            item.description = description
        if unit_cost is not None:
            item.unit_cost = unit_cost
        await self._inventory_repo.save_item(session, item)
        return item

    async def get_item(self, session: AsyncSession, item_id: uuid.UUID) -> InventoryItem:
        item = await self._inventory_repo.get_item_by_id(session, item_id)
        if item is None:
            raise DomainValidationError(field="item_id", value=str(item_id), constraint="Item not found.")
        return item

    async def list_items(
        self, session: AsyncSession, offset: int = 0, limit: int = 50
    ) -> tuple[list[InventoryItem], int]:
        return await self._inventory_repo.list_items(session, offset, limit)

    # ------------------------------------------------------------------
    # Warehouse
    # ------------------------------------------------------------------

    async def create_warehouse(
        self,
        session: AsyncSession,
        name: str,
        school_id: uuid.UUID,
        address: str,
        actor_id: uuid.UUID,
    ) -> Warehouse:
        warehouse = Warehouse(
            id=uuid.uuid4(),
            name=name,
            school_id=school_id,
            address=address,
            is_active=True,
        )
        await self._inventory_repo.save_warehouse(session, warehouse)
        await self._audit_writer.write(
            session,
            entity_type="Warehouse",
            entity_id=warehouse.id,
            action="WAREHOUSE_CREATED",
            actor_id=actor_id,
            metadata={"name": name},
        )
        return warehouse

    async def list_warehouses(self, session: AsyncSession) -> list[Warehouse]:
        return await self._inventory_repo.list_warehouses(session)

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------

    async def create_location(
        self,
        session: AsyncSession,
        warehouse_id: uuid.UUID,
        zone: str,
        aisle: str,
        bin_label: str,
        actor_id: uuid.UUID,
    ) -> Location:
        location = Location(
            id=uuid.uuid4(),
            warehouse_id=warehouse_id,
            zone=zone,
            aisle=aisle,
            bin_label=bin_label,
            is_active=True,
        )
        await self._inventory_repo.save_location(session, location)
        return location

    async def list_locations(
        self,
        session: AsyncSession,
        warehouse_id: Optional[uuid.UUID] = None,
        warehouse_ids: Optional[list[uuid.UUID]] = None,
    ) -> list[Location]:
        return await self._inventory_repo.list_locations(
            session,
            warehouse_id=warehouse_id,
            warehouse_ids=warehouse_ids,
        )

    # ------------------------------------------------------------------
    # Stock balance
    # ------------------------------------------------------------------

    async def list_stock(
        self,
        session: AsyncSession,
        item_id: Optional[uuid.UUID] = None,
        location_id: Optional[uuid.UUID] = None,
        batch_id: Optional[str] = None,
        serial_id: Optional[str] = None,
        status: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
        location_ids: Optional[list[uuid.UUID]] = None,
    ) -> tuple[list[StockBalance], int]:
        return await self._inventory_repo.list_stock(
            session, item_id, location_id, batch_id, serial_id, status, offset, limit,
            location_ids=location_ids,
        )

    async def freeze_stock(
        self,
        session: AsyncSession,
        balance_id: uuid.UUID,
        reason: str,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> StockBalance:
        """Freeze a stock balance. Raises StockFrozenError if already frozen."""
        balance = await self._inventory_repo.get_stock_balance_by_id(session, balance_id)
        if balance is None:
            raise DomainValidationError(
                field="balance_id", value=str(balance_id), constraint="Stock balance not found."
            )
        # StockBalance.freeze() raises StockFrozenError if already frozen
        balance.freeze(reason, actor_id, now)
        await self._lock_manager.acquire(session, "stock_balance", balance_id, actor_id)
        try:
            await self._inventory_repo.save_stock_balance(session, balance)
            await self._audit_writer.write(
                session,
                entity_type="StockBalance",
                entity_id=balance_id,
                action="STOCK_FROZEN",
                actor_id=actor_id,
                metadata={"reason": reason},
            )
        finally:
            await self._lock_manager.release(session, "stock_balance", balance_id, actor_id)
        return balance

    async def unfreeze_stock(
        self,
        session: AsyncSession,
        balance_id: uuid.UUID,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> StockBalance:
        """Unfreeze a stock balance."""
        balance = await self._inventory_repo.get_stock_balance_by_id(session, balance_id)
        if balance is None:
            raise DomainValidationError(
                field="balance_id", value=str(balance_id), constraint="Stock balance not found."
            )
        if not balance.is_frozen:
            raise DomainValidationError(
                field="balance_id", value=str(balance_id), constraint="Stock balance is not frozen."
            )
        balance.unfreeze()
        await self._lock_manager.acquire(session, "stock_balance", balance_id, actor_id)
        try:
            await self._inventory_repo.save_stock_balance(session, balance)
            await self._audit_writer.write(
                session,
                entity_type="StockBalance",
                entity_id=balance_id,
                action="STOCK_UNFROZEN",
                actor_id=actor_id,
                metadata={},
            )
        finally:
            await self._lock_manager.release(session, "stock_balance", balance_id, actor_id)
        return balance

    # ------------------------------------------------------------------
    # Ledger
    # ------------------------------------------------------------------

    async def add_adjustment(
        self,
        session: AsyncSession,
        item_id: uuid.UUID,
        location_id: uuid.UUID,
        quantity_delta: int,
        reason_code: str,
        operator_id: uuid.UUID,
        now: datetime,
        batch_id: Optional[str] = None,
        serial_id: Optional[str] = None,
        status: StockStatus = StockStatus.AVAILABLE,
    ) -> LedgerEntry:
        """Append a manual adjustment ledger entry and update stock balance."""
        balance = await self._inventory_repo.get_stock_balance(
            session,
            item_id,
            location_id,
            batch_id=batch_id,
            serial_id=serial_id,
            status=status.value,
        )
        if balance is None:
            frozen_balance = await self._inventory_repo.get_stock_balance(
                session,
                item_id,
                location_id,
                batch_id=batch_id,
                serial_id=serial_id,
                status=StockStatus.FROZEN.value,
            )
            if frozen_balance is not None:
                raise StockFrozenError(str(frozen_balance.id))
            # Auto-create balance at zero
            balance = StockBalance(
                id=uuid.uuid4(),
                item_id=item_id,
                location_id=location_id,
                batch_id=batch_id,
                serial_id=serial_id,
                status=status,
                quantity=0,
            )

        if balance.is_frozen:
            raise StockFrozenError(str(balance.id))

        quantity_after = balance.quantity + quantity_delta
        if quantity_after < 0:
            raise InsufficientStockError(
                item_id=str(item_id),
                location_id=str(location_id),
                available=balance.quantity,
                requested=abs(quantity_delta),
            )

        entry = LedgerEntry(
            id=uuid.uuid4(),
            item_id=item_id,
            location_id=location_id,
            entry_type=LedgerEntryType.ADJUSTMENT,
            quantity_delta=quantity_delta,
            quantity_after=quantity_after,
            operator_id=operator_id,
            reason_code=reason_code,
            created_at=now,
            reference_id=_encode_balance_partition(balance.status, balance.batch_id, balance.serial_id),
        )
        await self._lock_manager.acquire(session, "stock_balance", balance.id, operator_id)
        try:
            await self._ledger_repo.append(session, entry)
            balance.quantity = quantity_after
            await self._inventory_repo.save_stock_balance(session, balance)
            await self._audit_writer.write(
                session,
                entity_type="LedgerEntry",
                entity_id=entry.id,
                action="LEDGER_ADJUSTMENT",
                actor_id=operator_id,
                metadata={"quantity_delta": quantity_delta, "reason_code": reason_code},
            )
        finally:
            await self._lock_manager.release(session, "stock_balance", balance.id, operator_id)
        return entry

    async def add_correction(
        self,
        session: AsyncSession,
        entry_id: uuid.UUID,
        reason_code: str,
        operator_id: uuid.UUID,
        now: datetime,
    ) -> LedgerEntry:
        """
        Create a reversal correction for a prior ledger entry.

        Raises AppendOnlyViolationError if the original entry is already reversed.
        """
        original = await self._ledger_repo.get_by_id(session, entry_id)
        if original is None:
            raise DomainValidationError(
                field="entry_id", value=str(entry_id), constraint="Ledger entry not found."
            )
        if original.is_reversed:
            raise AppendOnlyViolationError(
                table="ledger_entries", record_id=str(entry_id)
            )

        partition_status, partition_batch_id, partition_serial_id = _decode_balance_partition(original.reference_id)
        resolved_status = partition_status.value if partition_status is not None else StockStatus.AVAILABLE.value

        balance = await self._inventory_repo.get_stock_balance(
            session,
            original.item_id,
            original.location_id,
            batch_id=partition_batch_id,
            serial_id=partition_serial_id,
            status=resolved_status,
        )
        if balance is None and resolved_status == StockStatus.AVAILABLE.value:
            frozen_balance = await self._inventory_repo.get_stock_balance(
                session,
                original.item_id,
                original.location_id,
                batch_id=partition_batch_id,
                serial_id=partition_serial_id,
                status=StockStatus.FROZEN.value,
            )
            if frozen_balance is not None:
                raise StockFrozenError(str(frozen_balance.id))
        if balance is None:
            raise DomainValidationError(
                field="stock_balance",
                value=None,
                constraint="Stock balance partition not found for correction.",
            )

        # Reversal delta is the negation of the original delta
        reversal_delta = -original.quantity_delta
        quantity_after = balance.quantity + reversal_delta
        if quantity_after < 0:
            raise InsufficientStockError(
                item_id=str(original.item_id),
                location_id=str(original.location_id),
                available=balance.quantity,
                requested=abs(reversal_delta),
            )

        correction = LedgerEntry(
            id=uuid.uuid4(),
            item_id=original.item_id,
            location_id=original.location_id,
            entry_type=LedgerEntryType.CORRECTION,
            quantity_delta=reversal_delta,
            quantity_after=quantity_after,
            operator_id=operator_id,
            reason_code=reason_code,
            created_at=now,
            reversal_of_id=original.id,
        )
        await self._lock_manager.acquire(session, "stock_balance", balance.id, operator_id)
        try:
            await self._ledger_repo.append(session, correction)
            # PERMITTED EXCEPTION: mark original as reversed
            await self._ledger_repo.mark_reversed(session, entry_id)
            balance.quantity = quantity_after
            await self._inventory_repo.save_stock_balance(session, balance)
            await self._audit_writer.write(
                session,
                entity_type="LedgerEntry",
                entity_id=correction.id,
                action="LEDGER_CORRECTION",
                actor_id=operator_id,
                metadata={"reversal_of_id": str(entry_id), "reason_code": reason_code},
            )
        finally:
            await self._lock_manager.release(session, "stock_balance", balance.id, operator_id)
        return correction

    async def list_ledger(
        self,
        session: AsyncSession,
        item_id: Optional[uuid.UUID] = None,
        location_id: Optional[uuid.UUID] = None,
        location_ids: Optional[list[uuid.UUID]] = None,
        entry_type: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[LedgerEntry], int]:
        return await self._ledger_repo.list(
            session,
            item_id,
            location_id,
            location_ids,
            entry_type,
            offset,
            limit,
        )
