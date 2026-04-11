"""
Count session domain entities: CountSession, CountLine, CountApproval.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from district_console.domain.enums import CountMode, CountSessionStatus, ReviewDecision
from district_console.domain.policies import COUNT_SESSION_INACTIVITY_HOURS


@dataclass
class CountSession:
    """
    A physical stock count session at a warehouse.

    mode:
        OPEN  — counters can see expected quantities (on-hand) while counting
        BLIND — counters do not see expected quantities (eliminates anchoring bias)
        CYCLE — partial count of a subset of locations on a rotating schedule

    A session expires after COUNT_SESSION_INACTIVITY_HOURS hours of inactivity.
    The APScheduler job checks this periodically and sets status=EXPIRED.
    Once closed, variance evaluation runs and may require supervisor approval.
    """
    id: uuid.UUID
    mode: CountMode
    status: CountSessionStatus
    warehouse_id: uuid.UUID
    created_by: uuid.UUID
    created_at: datetime
    last_activity_at: datetime
    closed_at: Optional[datetime] = None
    approved_by: Optional[uuid.UUID] = None
    approved_at: Optional[datetime] = None

    @property
    def expires_at(self) -> datetime:
        """Calculated expiry time based on last activity."""
        return self.last_activity_at + timedelta(hours=COUNT_SESSION_INACTIVITY_HOURS)

    def is_expired(self, now: datetime) -> bool:
        from district_console.domain.policies import is_count_session_expired
        return is_count_session_expired(self.last_activity_at, now)

    def touch(self, now: datetime) -> None:
        """Update last_activity_at to prevent expiry while a count is in progress."""
        self.last_activity_at = now


@dataclass
class CountLine:
    """
    One counted item/location pair within a count session.

    variance_qty = counted_qty - expected_qty  (negative = shrinkage)
    variance_value = abs(variance_qty) × unit_cost
    requires_approval is set by the domain policy evaluation after the session
    is closed, not by the user directly.
    """
    id: uuid.UUID
    session_id: uuid.UUID
    item_id: uuid.UUID
    location_id: uuid.UUID
    expected_qty: int
    counted_qty: int
    variance_qty: int          # counted_qty - expected_qty
    variance_value: Decimal    # abs(variance_qty) × unit_cost
    requires_approval: bool
    reason_code: Optional[str] = None

    @classmethod
    def evaluate(
        cls,
        id: uuid.UUID,
        session_id: uuid.UUID,
        item_id: uuid.UUID,
        location_id: uuid.UUID,
        expected_qty: int,
        counted_qty: int,
        unit_cost: Decimal,
        reason_code: Optional[str] = None,
    ) -> "CountLine":
        """Factory that computes variance and approval flag from raw counts."""
        from district_console.domain.policies import requires_supervisor_approval

        variance_qty = counted_qty - expected_qty
        variance_value = abs(Decimal(variance_qty)) * unit_cost

        on_hand = Decimal(expected_qty) if expected_qty > 0 else Decimal("1")
        variance_pct = variance_value / (on_hand * unit_cost) if unit_cost > 0 else Decimal("0")

        approval_needed = requires_supervisor_approval(variance_value, variance_pct)

        return cls(
            id=id,
            session_id=session_id,
            item_id=item_id,
            location_id=location_id,
            expected_qty=expected_qty,
            counted_qty=counted_qty,
            variance_qty=variance_qty,
            variance_value=variance_value,
            requires_approval=approval_needed,
            reason_code=reason_code,
        )


@dataclass(frozen=True)
class CountApproval:
    """
    Supervisor approval or rejection of a count session's variance.

    Created when a count session is closed and at least one CountLine
    has requires_approval=True. The supervisor reviews the variances and
    records a decision with mandatory notes.
    """
    id: uuid.UUID
    session_id: uuid.UUID
    reviewed_by: uuid.UUID
    decision: ReviewDecision
    notes: str
    decided_at: datetime
