"""
Relocation service — intra-warehouse stock movements with ledger audit trail.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from district_console.domain.entities.inventory import StockBalance
from district_console.domain.entities.ledger import LedgerEntry
from district_console.domain.entities.relocation import Relocation
from district_console.domain.enums import DeviceSource, LedgerEntryType, StockStatus
from district_console.domain.exceptions import (
    DomainValidationError,
    InsufficientStockError,
    StockFrozenError,
)
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.lock_manager import LockManager
from district_console.infrastructure.repositories import (
    InventoryRepository,
    LedgerRepository,
    RelocationRepository,
)


class RelocationService:
    def __init__(
        self,
        inventory_repo: InventoryRepository,
        ledger_repo: LedgerRepository,
        lock_manager: LockManager,
        audit_writer: AuditWriter,
        relocation_repo: RelocationRepository,
    ) -> None:
        self._inventory_repo = inventory_repo
        self._ledger_repo = ledger_repo
        self._lock_manager = lock_manager
        self._audit_writer = audit_writer
        self._relocation_repo = relocation_repo

    async def relocate(
        self,
        session: AsyncSession,
        item_id: uuid.UUID,
        from_location_id: uuid.UUID,
        to_location_id: uuid.UUID,
        quantity: int,
        operator_id: uuid.UUID,
        device_source: DeviceSource,
        now: datetime,
        batch_id: Optional[str] = None,
        serial_id: Optional[str] = None,
        status: StockStatus = StockStatus.AVAILABLE,
    ) -> Relocation:
        """
        Move stock between two bins in the same warehouse.

        Both a DEBIT and a CREDIT ledger entry are appended, and the
        corresponding StockBalance records are updated atomically.
        The Relocation domain entity is immutable and validated on construction
        (quantity > 0, from != to).
        """
        # Validate via domain entity construction (raises DomainValidationError)
        # We do a pre-check here to give cleaner error messages before acquiring the lock
        if from_location_id == to_location_id:
            raise DomainValidationError(
                field="to_location_id",
                value=str(to_location_id),
                constraint="Destination location must differ from source location.",
            )
        if quantity <= 0:
            raise DomainValidationError(
                field="quantity",
                value=quantity,
                constraint="Relocation quantity must be positive.",
            )

        from_location = await self._inventory_repo.get_location_by_id(session, from_location_id)
        if from_location is None:
            raise DomainValidationError(
                field="from_location_id",
                value=str(from_location_id),
                constraint="Source location does not exist.",
            )
        to_location = await self._inventory_repo.get_location_by_id(session, to_location_id)
        if to_location is None:
            raise DomainValidationError(
                field="to_location_id",
                value=str(to_location_id),
                constraint="Destination location does not exist.",
            )
        if from_location.warehouse_id != to_location.warehouse_id:
            raise DomainValidationError(
                field="to_location_id",
                value=str(to_location_id),
                constraint="Destination location must be in the same warehouse as source location.",
            )

        from_balance = await self._inventory_repo.get_stock_balance(
            session,
            item_id,
            from_location_id,
            batch_id=batch_id,
            serial_id=serial_id,
            status=status.value,
        )
        if from_balance is None and status == StockStatus.AVAILABLE:
            frozen_balance = await self._inventory_repo.get_stock_balance(
                session,
                item_id,
                from_location_id,
                batch_id=batch_id,
                serial_id=serial_id,
                status=StockStatus.FROZEN.value,
            )
            if frozen_balance is not None:
                raise StockFrozenError(str(frozen_balance.id))
        if from_balance is None or from_balance.quantity < quantity:
            available = from_balance.quantity if from_balance else 0
            raise InsufficientStockError(
                item_id=str(item_id),
                location_id=str(from_location_id),
                available=available,
                requested=quantity,
            )
        if from_balance.is_frozen:
            raise StockFrozenError(str(from_balance.id))

        # Load or create destination balance before acquiring any locks
        to_balance = await self._inventory_repo.get_stock_balance(
            session,
            item_id,
            to_location_id,
            batch_id=batch_id,
            serial_id=serial_id,
            status=status.value,
        )
        if to_balance is None:
            to_balance = StockBalance(
                id=uuid.uuid4(),
                item_id=item_id,
                location_id=to_location_id,
                batch_id=batch_id,
                serial_id=serial_id,
                status=status,
                quantity=0,
            )

        # Acquire both locks in sorted UUID order to prevent deadlock
        lock_ids = sorted([from_balance.id, to_balance.id], key=lambda x: str(x))
        await self._lock_manager.acquire(session, "stock_balance", lock_ids[0], operator_id)
        await self._lock_manager.acquire(session, "stock_balance", lock_ids[1], operator_id)
        try:
            # DEBIT from source
            debit_qty_after = from_balance.quantity - quantity
            debit_entry = LedgerEntry(
                id=uuid.uuid4(),
                item_id=item_id,
                location_id=from_location_id,
                entry_type=LedgerEntryType.RELOCATION,
                quantity_delta=-quantity,
                quantity_after=debit_qty_after,
                operator_id=operator_id,
                reason_code="RELOCATION",
                created_at=now,
                reference_id=str(to_location_id),
            )
            await self._ledger_repo.append(session, debit_entry)

            # CREDIT to destination
            credit_qty_after = to_balance.quantity + quantity
            credit_entry = LedgerEntry(
                id=uuid.uuid4(),
                item_id=item_id,
                location_id=to_location_id,
                entry_type=LedgerEntryType.RELOCATION,
                quantity_delta=quantity,
                quantity_after=credit_qty_after,
                operator_id=operator_id,
                reason_code="RELOCATION",
                created_at=now,
                reference_id=str(from_location_id),
            )
            await self._ledger_repo.append(session, credit_entry)

            # Update balances
            from_balance.quantity = debit_qty_after
            await self._inventory_repo.save_stock_balance(session, from_balance)

            to_balance.quantity = credit_qty_after
            await self._inventory_repo.save_stock_balance(session, to_balance)

            # Create immutable Relocation record
            relocation = Relocation(
                id=uuid.uuid4(),
                item_id=item_id,
                from_location_id=from_location_id,
                to_location_id=to_location_id,
                quantity=quantity,
                operator_id=operator_id,
                device_source=device_source,
                created_at=now,
                ledger_debit_entry_id=debit_entry.id,
                ledger_credit_entry_id=credit_entry.id,
            )
            await self._relocation_repo.save(session, relocation)

            await self._audit_writer.write(
                session,
                entity_type="Relocation",
                entity_id=relocation.id,
                action="RELOCATION",
                actor_id=operator_id,
                metadata={
                    "item_id": str(item_id),
                    "from_location_id": str(from_location_id),
                    "to_location_id": str(to_location_id),
                    "quantity": quantity,
                    "device_source": device_source.value,
                },
            )
        finally:
            await self._lock_manager.release(session, "stock_balance", lock_ids[1], operator_id)
            await self._lock_manager.release(session, "stock_balance", lock_ids[0], operator_id)

        return relocation

    async def list_relocations(
        self,
        session: AsyncSession,
        item_id: Optional[uuid.UUID] = None,
        operator_id: Optional[uuid.UUID] = None,
        location_ids: Optional[list[uuid.UUID]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Relocation], int]:
        return await self._relocation_repo.list(
            session,
            item_id,
            operator_id,
            location_ids,
            date_from,
            date_to,
            offset,
            limit,
        )
