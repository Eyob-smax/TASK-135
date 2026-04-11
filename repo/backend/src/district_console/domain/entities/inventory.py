"""
Inventory domain entities: InventoryItem, Warehouse, Location, StockBalance, RecordLock.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from district_console.domain.enums import StockStatus


@dataclass
class Warehouse:
    """A physical warehouse or storage facility linked to a school."""
    id: uuid.UUID
    name: str
    school_id: uuid.UUID
    address: str
    is_active: bool = True


@dataclass
class Location:
    """
    A bin address within a warehouse at zone/aisle/bin granularity.
    bin_label is the human-readable full address (e.g. "A-01-03").
    """
    id: uuid.UUID
    warehouse_id: uuid.UUID
    zone: str
    aisle: str
    bin_label: str
    is_active: bool = True


@dataclass
class InventoryItem:
    """
    A stock-keeping unit (SKU) definition.

    unit_cost is used for variance value calculations during count sessions.
    The ledger tracks quantities; InventoryItem itself holds no quantity.
    """
    id: uuid.UUID
    sku: str
    name: str
    description: str
    unit_cost: Decimal
    created_by: uuid.UUID
    created_at: datetime


@dataclass
class StockBalance:
    """
    Current stock level for one item at one location for one batch/serial/status
    combination.

    Represents a record-level balance — not a ledger entry. The source of
    truth for current quantity is always the ledger; StockBalance is a
    materialised view maintained by the inventory service after each ledger
    entry is appended.

    freeze() and unfreeze() update the record state; they do NOT append ledger
    entries — the calling service must do that after updating this object.
    """
    id: uuid.UUID
    item_id: uuid.UUID
    location_id: uuid.UUID
    batch_id: Optional[str]
    serial_id: Optional[str]
    status: StockStatus
    quantity: int
    is_frozen: bool = False
    freeze_reason: Optional[str] = None
    frozen_by: Optional[uuid.UUID] = None
    frozen_at: Optional[datetime] = None

    def freeze(self, reason: str, actor_id: uuid.UUID, now: datetime) -> None:
        """Mark this balance as frozen. Raises StockFrozenError if already frozen."""
        if self.is_frozen:
            from district_console.domain.exceptions import StockFrozenError
            raise StockFrozenError(str(self.id))
        self.is_frozen = True
        self.freeze_reason = reason
        self.frozen_by = actor_id
        self.frozen_at = now
        self.status = StockStatus.FROZEN

    def unfreeze(self) -> None:
        """Remove freeze state and restore status to AVAILABLE."""
        self.is_frozen = False
        self.freeze_reason = None
        self.frozen_by = None
        self.frozen_at = None
        self.status = StockStatus.AVAILABLE


@dataclass
class RecordLock:
    """
    Exclusive advisory lock on any domain record.

    entity_type identifies the table (e.g. "StockBalance", "Resource").
    entity_id is the string primary key of the locked record.
    nonce is a random token the lock holder presents when releasing the lock
    to prevent accidental release by a different session.
    """
    id: uuid.UUID
    entity_type: str
    entity_id: str
    locked_by: uuid.UUID        # User who acquired the lock
    locked_at: datetime
    expires_at: datetime
    nonce: str

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at
