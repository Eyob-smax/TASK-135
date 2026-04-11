"""
Tests for append-only and immutability invariants.

Verifies that:
- AuditEvent is frozen (immutable after creation)
- LedgerEntry is frozen (immutable after creation)
- AppendOnlyViolationError exists and is properly structured
- Correction entries correctly reference their reversal targets
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from district_console.domain.entities.ledger import LedgerEntry
from district_console.domain.entities.resource import AuditEvent
from district_console.domain.enums import LedgerEntryType
from district_console.domain.exceptions import (
    AppendOnlyViolationError,
    DistrictConsoleError,
)

NOW = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)
ACTOR = uuid.uuid4()
ITEM_ID = uuid.uuid4()
LOC_ID = uuid.uuid4()


def make_audit_event(action: str = "PUBLISHED") -> AuditEvent:
    return AuditEvent(
        id=uuid.uuid4(),
        entity_type="Resource",
        entity_id=str(uuid.uuid4()),
        action=action,
        actor_id=ACTOR,
        timestamp=NOW,
        metadata={"notes": "test"},
    )


def make_ledger_entry(
    entry_type: LedgerEntryType = LedgerEntryType.ADJUSTMENT,
    quantity_delta: int = 10,
    quantity_after: int = 100,
    reversal_of_id: uuid.UUID | None = None,
    is_reversed: bool = False,
) -> LedgerEntry:
    return LedgerEntry(
        id=uuid.uuid4(),
        item_id=ITEM_ID,
        location_id=LOC_ID,
        entry_type=entry_type,
        quantity_delta=quantity_delta,
        quantity_after=quantity_after,
        operator_id=ACTOR,
        reason_code="DATA_ENTRY",
        created_at=NOW,
        is_reversed=is_reversed,
        reversal_of_id=reversal_of_id,
    )


class TestAuditEventImmutability:
    def test_audit_event_is_frozen(self) -> None:
        """AuditEvent must be a frozen dataclass."""
        event = make_audit_event()
        with pytest.raises((AttributeError, TypeError)):
            event.action = "MODIFIED"  # type: ignore[misc]

    def test_audit_event_timestamp_frozen(self) -> None:
        event = make_audit_event()
        with pytest.raises((AttributeError, TypeError)):
            event.timestamp = datetime(2099, 1, 1, tzinfo=timezone.utc)  # type: ignore[misc]

    def test_audit_event_actor_id_frozen(self) -> None:
        event = make_audit_event()
        with pytest.raises((AttributeError, TypeError)):
            event.actor_id = uuid.uuid4()  # type: ignore[misc]

    def test_audit_event_fields_readable(self) -> None:
        event = make_audit_event("REVIEW_APPROVED")
        assert event.entity_type == "Resource"
        assert event.action == "REVIEW_APPROVED"
        assert event.actor_id == ACTOR
        assert event.timestamp == NOW

    def test_audit_event_id_is_uuid(self) -> None:
        event = make_audit_event()
        assert isinstance(event.id, uuid.UUID)


class TestLedgerEntryImmutability:
    def test_ledger_entry_is_frozen(self) -> None:
        """LedgerEntry must be a frozen dataclass — no mutation allowed."""
        entry = make_ledger_entry()
        with pytest.raises((AttributeError, TypeError)):
            entry.quantity_delta = -999  # type: ignore[misc]

    def test_ledger_entry_operator_frozen(self) -> None:
        entry = make_ledger_entry()
        with pytest.raises((AttributeError, TypeError)):
            entry.operator_id = uuid.uuid4()  # type: ignore[misc]

    def test_ledger_entry_fields_readable(self) -> None:
        entry = make_ledger_entry(quantity_delta=5, quantity_after=105)
        assert entry.quantity_delta == 5
        assert entry.quantity_after == 105
        assert entry.item_id == ITEM_ID

    def test_ledger_entry_negative_quantity_after_raises(self) -> None:
        """quantity_after must not be negative."""
        from district_console.domain.exceptions import DomainValidationError
        with pytest.raises(DomainValidationError):
            make_ledger_entry(quantity_delta=-200, quantity_after=-50)


class TestCorrectionEntryStructure:
    def test_correction_entry_has_reversal_reference(self) -> None:
        """A CORRECTION entry must reference the original entry via reversal_of_id."""
        original = make_ledger_entry(
            entry_type=LedgerEntryType.ADJUSTMENT,
            quantity_delta=10,
            quantity_after=110,
        )
        correction = make_ledger_entry(
            entry_type=LedgerEntryType.CORRECTION,
            quantity_delta=-10,      # Negates the original delta
            quantity_after=100,      # Restores the balance
            reversal_of_id=original.id,
        )
        assert correction.reversal_of_id == original.id
        assert correction.entry_type == LedgerEntryType.CORRECTION
        assert correction.quantity_delta == -original.quantity_delta

    def test_correction_negates_original_delta(self) -> None:
        original = make_ledger_entry(quantity_delta=25, quantity_after=125)
        correction = make_ledger_entry(
            entry_type=LedgerEntryType.CORRECTION,
            quantity_delta=-25,
            quantity_after=100,
            reversal_of_id=original.id,
        )
        assert correction.quantity_delta + original.quantity_delta == 0

    def test_normal_entry_has_no_reversal_reference(self) -> None:
        entry = make_ledger_entry(entry_type=LedgerEntryType.RECEIPT)
        assert entry.reversal_of_id is None


class TestAppendOnlyViolationError:
    def test_error_is_raiseable(self) -> None:
        with pytest.raises(AppendOnlyViolationError):
            raise AppendOnlyViolationError(table="ledger_entries", record_id="abc-123")

    def test_error_inherits_from_base(self) -> None:
        err = AppendOnlyViolationError(table="audit_events", record_id="xyz")
        assert isinstance(err, DistrictConsoleError)

    def test_error_code(self) -> None:
        err = AppendOnlyViolationError(table="ledger_entries", record_id="abc")
        assert err.code == "APPEND_ONLY_VIOLATION"

    def test_error_message_contains_table(self) -> None:
        err = AppendOnlyViolationError(table="ledger_entries", record_id="abc")
        assert "ledger_entries" in err.message
