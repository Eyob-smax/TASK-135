"""
Count session service — open/blind/cycle count workflows with variance approval.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from district_console.domain.entities.count import CountApproval, CountLine, CountSession
from district_console.domain.entities.inventory import StockBalance
from district_console.domain.entities.ledger import LedgerEntry
from district_console.domain.enums import CountSessionStatus, LedgerEntryType, ReviewDecision, StockStatus
from district_console.domain.exceptions import DomainValidationError, InsufficientPermissionError
from district_console.domain.policies import is_count_session_expired
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.checkpoint_store import CheckpointStore
from district_console.infrastructure.lock_manager import LockManager
from district_console.infrastructure.repositories import (
    CountSessionRepository,
    InventoryRepository,
    LedgerRepository,
)


class CountSessionService:
    def __init__(
        self,
        count_repo: CountSessionRepository,
        inventory_repo: InventoryRepository,
        ledger_repo: LedgerRepository,
        audit_writer: AuditWriter,
        lock_manager: LockManager,
        checkpoint_store: CheckpointStore,
    ) -> None:
        self._count_repo = count_repo
        self._inventory_repo = inventory_repo
        self._ledger_repo = ledger_repo
        self._audit_writer = audit_writer
        self._lock_manager = lock_manager
        self._checkpoint_store = checkpoint_store

    async def open_session(
        self,
        session: AsyncSession,
        mode,
        warehouse_id: uuid.UUID,
        created_by: uuid.UUID,
        now: datetime,
    ) -> CountSession:
        """Open a new ACTIVE count session."""
        count_session = CountSession(
            id=uuid.uuid4(),
            mode=mode,
            status=CountSessionStatus.ACTIVE,
            warehouse_id=warehouse_id,
            created_by=created_by,
            created_at=now,
            last_activity_at=now,
        )
        await self._count_repo.save_session(session, count_session)

        cp = await self._checkpoint_store.save(
            session,
            job_type="count",
            job_id=str(count_session.id),
            state={"session_id": str(count_session.id), "step": "opened"},
        )

        await self._audit_writer.write(
            session,
            entity_type="CountSession",
            entity_id=count_session.id,
            action="COUNT_SESSION_OPENED",
            actor_id=created_by,
            metadata={"mode": mode.value, "warehouse_id": str(warehouse_id)},
        )
        return count_session

    async def add_count_line(
        self,
        session: AsyncSession,
        session_id: uuid.UUID,
        item_id: uuid.UUID,
        location_id: uuid.UUID,
        counted_qty: int,
        reason_code: Optional[str],
        operator_id: uuid.UUID,
        now: datetime,
    ) -> CountLine:
        """Add or update a count line in an active session."""
        count_session = await self._count_repo.get_by_id(session, session_id)
        if count_session is None:
            raise DomainValidationError(
                field="session_id", value=str(session_id), constraint="Count session not found."
            )
        if count_session.status != CountSessionStatus.ACTIVE:
            raise DomainValidationError(
                field="session_id",
                value=str(session_id),
                constraint="Count session is not active.",
            )
        if is_count_session_expired(count_session.last_activity_at, now):
            raise DomainValidationError(
                field="session_id",
                value=str(session_id),
                constraint="Count session has expired due to inactivity.",
            )

        item = await self._inventory_repo.get_item_by_id(session, item_id)
        if item is None:
            raise DomainValidationError(
                field="item_id", value=str(item_id), constraint="Inventory item not found."
            )

        balance = await self._inventory_repo.get_stock_balance(
            session,
            item_id,
            location_id,
            batch_id=None,
            serial_id=None,
            status=StockStatus.AVAILABLE.value,
        )
        expected_qty = balance.quantity if balance is not None else 0

        line = CountLine.evaluate(
            id=uuid.uuid4(),
            session_id=session_id,
            item_id=item_id,
            location_id=location_id,
            expected_qty=expected_qty,
            counted_qty=counted_qty,
            unit_cost=item.unit_cost,
            reason_code=reason_code,
        )
        if line.variance_qty != 0 and not reason_code:
            raise DomainValidationError(
                field="reason_code",
                value=None,
                constraint="reason_code is required when a variance exists (counted_qty != expected_qty).",
            )
        await self._count_repo.save_line(session, line)

        count_session.touch(now)
        await self._count_repo.save_session(session, count_session)

        await self._checkpoint_store.save(
            session,
            job_type="count",
            job_id=str(session_id),
            state={"session_id": str(session_id), "step": "in_progress", "lines": 1},
        )
        return line

    async def update_count_line(
        self,
        session: AsyncSession,
        session_id: uuid.UUID,
        line_id: uuid.UUID,
        counted_qty: int,
        operator_id: uuid.UUID,
        now: datetime,
    ) -> CountLine:
        """Update the counted quantity on an existing count line."""
        count_session = await self._count_repo.get_by_id(session, session_id)
        if count_session is None:
            raise DomainValidationError(
                field="session_id", value=str(session_id), constraint="Count session not found."
            )
        if count_session.status != CountSessionStatus.ACTIVE:
            raise DomainValidationError(
                field="session_id",
                value=str(session_id),
                constraint="Count session is not active.",
            )
        if is_count_session_expired(count_session.last_activity_at, now):
            raise DomainValidationError(
                field="session_id",
                value=str(session_id),
                constraint="Count session has expired due to inactivity.",
            )

        line = await self._count_repo.get_line_by_id(session, session_id, line_id)
        if line is None:
            raise DomainValidationError(
                field="line_id", value=str(line_id), constraint="Count line not found."
            )

        item = await self._inventory_repo.get_item_by_id(session, line.item_id)
        if item is None:
            raise DomainValidationError(
                field="item_id", value=str(line.item_id), constraint="Inventory item not found."
            )

        balance = await self._inventory_repo.get_stock_balance(
            session,
            line.item_id,
            line.location_id,
            batch_id=None,
            serial_id=None,
            status=StockStatus.AVAILABLE.value,
        )
        expected_qty = balance.quantity if balance is not None else 0

        updated_line = CountLine.evaluate(
            id=line.id,
            session_id=session_id,
            item_id=line.item_id,
            location_id=line.location_id,
            expected_qty=expected_qty,
            counted_qty=counted_qty,
            unit_cost=item.unit_cost,
            reason_code=line.reason_code,
        )
        await self._count_repo.save_line(session, updated_line)

        count_session.touch(now)
        await self._count_repo.save_session(session, count_session)

        return updated_line

    async def close_session(
        self,
        session: AsyncSession,
        session_id: uuid.UUID,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> CountSession:
        """
        Close the count session.

        For each line with variance_qty != 0: append a COUNT_CLOSE ledger
        entry and update the stock balance.
        """
        count_session = await self._count_repo.get_by_id(session, session_id)
        if count_session is None:
            raise DomainValidationError(
                field="session_id", value=str(session_id), constraint="Count session not found."
            )
        if count_session.status != CountSessionStatus.ACTIVE:
            raise DomainValidationError(
                field="session_id",
                value=str(session_id),
                constraint="Count session is not active.",
            )

        await self._lock_manager.acquire(session, "count_session", session_id, actor_id)
        try:
            lines = await self._count_repo.get_lines(session, session_id)

            # Pre-validate: all non-approval variance lines must carry a reason_code
            for line in lines:
                if line.variance_qty != 0 and not line.requires_approval and not line.reason_code:
                    raise DomainValidationError(
                        field="reason_code",
                        value=None,
                        constraint=f"Line {line.id}: reason_code is required on variance lines.",
                    )

            for line in lines:
                if line.variance_qty == 0:
                    continue
                if line.requires_approval:
                    continue  # Defer ledger mutation until approve_session confirms

                balance = await self._inventory_repo.get_stock_balance(
                    session,
                    line.item_id,
                    line.location_id,
                    batch_id=None,
                    serial_id=None,
                    status=StockStatus.AVAILABLE.value,
                )
                if balance is None:
                    balance = StockBalance(
                        id=uuid.uuid4(),
                        item_id=line.item_id,
                        location_id=line.location_id,
                        batch_id=None,
                        serial_id=None,
                        status=StockStatus.AVAILABLE,
                        quantity=0,
                    )

                quantity_after = balance.quantity + line.variance_qty
                if quantity_after < 0:
                    quantity_after = 0

                entry = LedgerEntry(
                    id=uuid.uuid4(),
                    item_id=line.item_id,
                    location_id=line.location_id,
                    entry_type=LedgerEntryType.COUNT_CLOSE,
                    quantity_delta=line.variance_qty,
                    quantity_after=quantity_after,
                    operator_id=actor_id,
                    reason_code=line.reason_code,
                    created_at=now,
                    reference_id=str(session_id),
                )
                await self._lock_manager.acquire(session, "stock_balance", balance.id, actor_id)
                try:
                    await self._ledger_repo.append(session, entry)
                    balance.quantity = quantity_after
                    await self._inventory_repo.save_stock_balance(session, balance)
                finally:
                    await self._lock_manager.release(session, "stock_balance", balance.id, actor_id)

            count_session.status = CountSessionStatus.CLOSED
            count_session.closed_at = now
            await self._count_repo.save_session(session, count_session)

            needs_approval = any(line.requires_approval for line in lines)
            cp_step = "awaiting_approval" if needs_approval else "completed"
            cp = await self._checkpoint_store.save(
                session,
                job_type="count",
                job_id=str(session_id),
                state={"session_id": str(session_id), "step": cp_step},
            )
            if not needs_approval:
                await self._checkpoint_store.mark_completed(session, cp.id)
            else:
                # Write a dedicated approval-type checkpoint so the approval queue
                # service (audit_service.get_active_approvals) can discover it.
                await self._checkpoint_store.save(
                    session,
                    job_type="approval",
                    job_id=str(session_id),
                    state={"session_id": str(session_id), "step": "awaiting_approval", "type": "count"},
                )

            await self._audit_writer.write(
                session,
                entity_type="CountSession",
                entity_id=session_id,
                action="COUNT_SESSION_CLOSED",
                actor_id=actor_id,
                metadata={"needs_approval": needs_approval, "line_count": len(lines)},
            )
        finally:
            await self._lock_manager.release(session, "count_session", session_id, actor_id)

        return count_session

    async def approve_session(
        self,
        session: AsyncSession,
        session_id: uuid.UUID,
        notes: str,
        reviewed_by: uuid.UUID,
        roles: list,
        now: datetime,
    ) -> CountSession:
        """Approve variance for a CLOSED count session (requires admin role)."""
        from district_console.application.rbac_service import RbacService
        RbacService().check_permission(roles, "inventory.approve_count")

        count_session = await self._count_repo.get_by_id(session, session_id)
        if count_session is None:
            raise DomainValidationError(
                field="session_id", value=str(session_id), constraint="Count session not found."
            )
        if count_session.status != CountSessionStatus.CLOSED:
            raise DomainValidationError(
                field="session_id",
                value=str(session_id),
                constraint="Count session must be CLOSED before approval.",
            )

        approval = CountApproval(
            id=uuid.uuid4(),
            session_id=session_id,
            reviewed_by=reviewed_by,
            decision=ReviewDecision.APPROVED,
            notes=notes,
            decided_at=now,
        )
        await self._count_repo.save_approval(session, approval)

        count_session.status = CountSessionStatus.APPROVED
        count_session.approved_by = reviewed_by
        count_session.approved_at = now
        await self._count_repo.save_session(session, count_session)

        # Write deferred ledger entries for lines that required approval
        lines = await self._count_repo.get_lines(session, session_id)

        # Pre-validate: approval-gated variance lines must carry a reason_code
        for line in lines:
            if line.requires_approval and line.variance_qty != 0 and not line.reason_code:
                raise DomainValidationError(
                    field="reason_code",
                    value=None,
                    constraint=f"Line {line.id}: reason_code is required on variance lines.",
                )

        for line in lines:
            if not line.requires_approval or line.variance_qty == 0:
                continue
            balance = await self._inventory_repo.get_stock_balance(
                session,
                line.item_id,
                line.location_id,
                batch_id=None,
                serial_id=None,
                status=StockStatus.AVAILABLE.value,
            )
            if balance is None:
                balance = StockBalance(
                    id=uuid.uuid4(),
                    item_id=line.item_id,
                    location_id=line.location_id,
                    batch_id=None,
                    serial_id=None,
                    status=StockStatus.AVAILABLE,
                    quantity=0,
                )
            quantity_after = max(0, balance.quantity + line.variance_qty)
            entry = LedgerEntry(
                id=uuid.uuid4(),
                item_id=line.item_id,
                location_id=line.location_id,
                entry_type=LedgerEntryType.COUNT_CLOSE,
                quantity_delta=line.variance_qty,
                quantity_after=quantity_after,
                operator_id=reviewed_by,
                reason_code=line.reason_code,
                created_at=now,
                reference_id=str(session_id),
            )
            await self._lock_manager.acquire(session, "stock_balance", balance.id, reviewed_by)
            try:
                await self._ledger_repo.append(session, entry)
                balance.quantity = quantity_after
                await self._inventory_repo.save_stock_balance(session, balance)
            finally:
                await self._lock_manager.release(session, "stock_balance", balance.id, reviewed_by)

        cp = await self._checkpoint_store.save(
            session,
            job_type="count",
            job_id=str(session_id),
            state={"session_id": str(session_id), "step": "approved"},
        )
        await self._checkpoint_store.mark_completed(session, cp.id)

        await self._audit_writer.write(
            session,
            entity_type="CountSession",
            entity_id=session_id,
            action="COUNT_SESSION_APPROVED",
            actor_id=reviewed_by,
            metadata={"notes_length": len(notes)},
        )
        return count_session

    async def list_sessions(
        self,
        session: AsyncSession,
        status: Optional[str] = None,
        warehouse_ids: Optional[list[uuid.UUID]] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[CountSession], int]:
        """Return a paginated list of count sessions, optionally filtered by status."""
        return await self._count_repo.list_by_status(
            session,
            status=status,
            warehouse_ids=warehouse_ids,
            offset=offset,
            limit=limit,
        )

    async def check_and_expire(
        self,
        session: AsyncSession,
        session_id: uuid.UUID,
        now: datetime,
    ) -> bool:
        """
        Expire the session if ACTIVE and inactive beyond the threshold.

        Returns True if the session was expired, False otherwise.
        """
        count_session = await self._count_repo.get_by_id(session, session_id)
        if count_session is None:
            return False
        if count_session.status != CountSessionStatus.ACTIVE:
            return False
        if not is_count_session_expired(count_session.last_activity_at, now):
            return False

        count_session.status = CountSessionStatus.EXPIRED
        await self._count_repo.save_session(session, count_session)

        cp = await self._checkpoint_store.save(
            session,
            job_type="count",
            job_id=str(session_id),
            state={"session_id": str(session_id), "step": "expired"},
        )
        await self._checkpoint_store.mark_failed(session, cp.id, "Session expired due to inactivity.")

        await self._audit_writer.write(
            session,
            entity_type="CountSession",
            entity_id=session_id,
            action="COUNT_SESSION_EXPIRED",
            actor_id=count_session.created_by,
            metadata={"last_activity_at": count_session.last_activity_at.isoformat()},
        )
        return True

    async def resume_count_checkpoint(
        self,
        session: AsyncSession,
        session_id: uuid.UUID,
        now: datetime,
    ) -> str:
        """
        Resume a count-session checkpoint discovered at startup.

        Returns one of: "resumed", "expired", "completed", "abandoned".
        """
        count_session = await self._count_repo.get_by_id(session, session_id)
        if count_session is None:
            return "abandoned"

        if count_session.status == CountSessionStatus.ACTIVE:
            expired = await self.check_and_expire(session, session_id, now)
            return "expired" if expired else "resumed"

        # CLOSED/APPROVED/EXPIRED sessions should no longer remain ACTIVE checkpoints.
        return "completed"

    async def resume_approval_checkpoint(
        self,
        session: AsyncSession,
        session_id: uuid.UUID,
    ) -> str:
        """
        Resume an approval-queue checkpoint discovered at startup.

        Returns one of: "resumed", "completed", "abandoned".
        """
        count_session = await self._count_repo.get_by_id(session, session_id)
        if count_session is None:
            return "abandoned"

        if count_session.status == CountSessionStatus.CLOSED:
            return "resumed"

        if count_session.status in (CountSessionStatus.APPROVED, CountSessionStatus.EXPIRED):
            return "completed"

        return "abandoned"
