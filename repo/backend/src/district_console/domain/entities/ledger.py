"""
Inventory ledger entry domain entity.

LedgerEntry is append-only and frozen. Every stock movement, adjustment,
correction, relocation, and count close produces a new entry. Records are
never updated or deleted; corrections are represented by a new CORRECTION
entry that references the original via reversal_of_id.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from district_console.domain.enums import LedgerEntryType


@dataclass(frozen=True)
class LedgerEntry:
    """
    A single append-only record in the inventory adjustment ledger.

    quantity_delta: Signed change (+receipt/-adjustment). Corrections negate
                    the original entry's delta.
    quantity_after: Running balance after this entry is applied.
    is_reversed:    True when a CORRECTION entry has been created against
                    this entry. Set by the infrastructure layer; the domain
                    entity itself is frozen.
    reversal_of_id: If entry_type==CORRECTION, this references the original
                    entry being reversed.

    NOTE: LedgerEntry.is_reversed and reversal_of_id are technically
    "mutable" state (a correction sets is_reversed=True on the original).
    Because the entity is frozen at construction, the infrastructure layer
    handles this by re-creating the record in the database with the updated
    flag rather than issuing an UPDATE — or by treating is_reversed as a
    derived view computed from the presence of a CORRECTION entry referencing
    this entry's id.

    For simplicity, the infrastructure layer records is_reversed as an
    updatable column ONLY for the is_reversed flag (not for any business data).
    All other columns remain immutable after insert.
    """
    id: uuid.UUID
    item_id: uuid.UUID
    location_id: uuid.UUID
    entry_type: LedgerEntryType
    quantity_delta: int            # Signed: positive=in, negative=out
    quantity_after: int            # Non-negative running balance
    operator_id: uuid.UUID
    reason_code: str
    created_at: datetime
    reference_id: Optional[str] = None    # e.g. count_session_id, relocation_id
    is_reversed: bool = False
    reversal_of_id: Optional[uuid.UUID] = None

    def __post_init__(self) -> None:
        if self.quantity_after < 0:
            from district_console.domain.exceptions import DomainValidationError
            raise DomainValidationError(
                field="quantity_after",
                value=self.quantity_after,
                constraint="Running balance cannot be negative.",
            )
