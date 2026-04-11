"""
Intra-warehouse relocation domain entity.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from district_console.domain.enums import DeviceSource


@dataclass(frozen=True)
class Relocation:
    """
    A record of an intra-warehouse stock movement.

    device_source identifies how the from/to locations were entered:
        MANUAL      — operator typed location codes via keyboard
        USB_SCANNER — location barcodes were scanned via USB barcode scanner
                      (keyboard-wedge input; no special driver required)

    ledger_ref_id points to the pair of LedgerEntry records (one debit,
    one credit) that were appended when this relocation was processed.
    The relocation record itself is immutable; adjustments go through
    correction entries on the ledger.
    """
    id: uuid.UUID
    item_id: uuid.UUID
    from_location_id: uuid.UUID
    to_location_id: uuid.UUID
    quantity: int
    operator_id: uuid.UUID
    device_source: DeviceSource
    created_at: datetime
    ledger_debit_entry_id: uuid.UUID     # LedgerEntry for source (negative delta)
    ledger_credit_entry_id: uuid.UUID    # LedgerEntry for destination (positive delta)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            from district_console.domain.exceptions import DomainValidationError
            raise DomainValidationError(
                field="quantity",
                value=self.quantity,
                constraint="Relocation quantity must be positive.",
            )
        if self.from_location_id == self.to_location_id:
            from district_console.domain.exceptions import DomainValidationError
            raise DomainValidationError(
                field="to_location_id",
                value=str(self.to_location_id),
                constraint="Destination location must differ from source location.",
            )
