"""
Unit tests for CountSessionService — open, add lines, close, approve workflows.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.auth_service import AuthService
from district_console.application.count_session_service import CountSessionService
from district_console.domain.entities.role import Permission, Role
from district_console.domain.enums import CountMode, CountSessionStatus
from district_console.domain.enums import RoleType
from district_console.domain.exceptions import DomainValidationError, InsufficientPermissionError
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.checkpoint_store import CheckpointStore
from district_console.infrastructure.lock_manager import LockManager
from district_console.infrastructure.orm import UserORM
from district_console.infrastructure.repositories import (
    AuditRepository,
    CheckpointRepository,
    CountSessionRepository,
    InventoryRepository,
    LedgerRepository,
    LockRepository,
    RoleRepository,
    UserRepository,
)


def _make_service():
    audit_writer = AuditWriter(AuditRepository())
    lock_manager = LockManager(LockRepository())
    checkpoint_store = CheckpointStore(CheckpointRepository())
    return CountSessionService(
        CountSessionRepository(),
        InventoryRepository(),
        LedgerRepository(),
        audit_writer,
        lock_manager,
        checkpoint_store,
    )


NOW = datetime(2024, 6, 1, 10, 0, 0)
ACTOR = uuid.uuid4()


def _role(role_type: RoleType, permissions: list[str]) -> Role:
    perms = frozenset(
        Permission(
            id=uuid.uuid4(),
            name=name,
            resource_name=name.split(".")[0],
            action=name.split(".")[1],
        )
        for name in permissions
    )
    return Role(
        id=uuid.uuid4(),
        role_type=role_type,
        display_name=role_type.value,
        permissions=perms,
    )


@pytest.fixture(autouse=True)
async def _seed_actor_user(db_session: AsyncSession) -> None:
    """Seed a user matching ACTOR so FK constraints pass for count session tests."""
    auth = AuthService(UserRepository(), RoleRepository())
    now = datetime.utcnow().isoformat()
    db_session.add(
        UserORM(
            id=str(ACTOR),
            username="count_session_actor",
            password_hash=auth.hash_password("SecurePassword1!"),
            is_active=True,
            failed_attempts=0,
            locked_until=None,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.flush()


async def test_open_session_creates_active_session(
    db_session: AsyncSession, seeded_warehouse
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    assert cs.status == CountSessionStatus.ACTIVE
    assert cs.mode == CountMode.OPEN
    assert cs.warehouse_id == uuid.UUID(seeded_warehouse.id)


async def test_open_session_saves_checkpoint(
    db_session: AsyncSession, seeded_warehouse
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.BLIND, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    # Verify checkpoint record exists
    checkpoint_repo = CheckpointRepository()
    cp = await checkpoint_repo.get(db_session, "count", str(cs.id))
    assert cp is not None
    assert cp.job_type == "count"


async def test_add_count_line_evaluates_variance(
    db_session: AsyncSession, seeded_warehouse, seeded_inventory_item,
    seeded_location, seeded_stock_balance
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    line = await svc.add_count_line(
        db_session,
        session_id=cs.id,
        item_id=uuid.UUID(seeded_inventory_item.id),
        location_id=uuid.UUID(seeded_location.id),
        counted_qty=90,
        reason_code="RECOUNT",
        operator_id=ACTOR,
        now=NOW,
    )
    # seeded_stock_balance has quantity=100, counted 90 → variance=-10
    assert line.variance_qty == -10
    assert line.expected_qty == 100


async def test_add_line_to_expired_session_raises(
    db_session: AsyncSession, seeded_warehouse, seeded_inventory_item, seeded_location
):
    svc = _make_service()
    old_time = NOW - timedelta(hours=9)
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, old_time
    )
    with pytest.raises(DomainValidationError, match="expired"):
        await svc.add_count_line(
            db_session,
            session_id=cs.id,
            item_id=uuid.UUID(seeded_inventory_item.id),
            location_id=uuid.UUID(seeded_location.id),
            counted_qty=10,
            reason_code=None,
            operator_id=ACTOR,
            now=NOW,
        )


async def test_close_session_generates_ledger_entries_for_variances(
    db_session: AsyncSession, seeded_warehouse, seeded_inventory_item,
    seeded_location, seeded_stock_balance
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    line = await svc.add_count_line(
        db_session, cs.id,
        uuid.UUID(seeded_inventory_item.id),
        uuid.UUID(seeded_location.id),
        counted_qty=95, reason_code="RECOUNT", operator_id=ACTOR, now=NOW,
    )
    closed = await svc.close_session(db_session, cs.id, ACTOR, NOW)
    assert closed.status == CountSessionStatus.CLOSED

    # Verify ledger entry was created
    ledger_repo = LedgerRepository()
    entries, total = await ledger_repo.list(
        db_session,
        item_id=uuid.UUID(seeded_inventory_item.id),
        location_id=uuid.UUID(seeded_location.id),
    )
    count_close_entries = [e for e in entries if e.entry_type.value == "COUNT_CLOSE"]
    expected_entries = 0 if line.requires_approval else 1
    assert len(count_close_entries) == expected_entries


async def test_close_session_marks_requires_approval_for_large_variance(
    db_session: AsyncSession, seeded_warehouse, seeded_inventory_item,
    seeded_location, seeded_stock_balance
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    # unit_cost=9.99, need variance > $250 → variance_qty > 25 units
    # seeded_stock_balance has qty=100, count 60 → variance=-40 × 9.99 = 399.60 > 250
    await svc.add_count_line(
        db_session, cs.id,
        uuid.UUID(seeded_inventory_item.id),
        uuid.UUID(seeded_location.id),
        counted_qty=60, reason_code="DAMAGE", operator_id=ACTOR, now=NOW,
    )
    closed = await svc.close_session(db_session, cs.id, ACTOR, NOW)
    lines = await svc._count_repo.get_lines(db_session, cs.id)
    assert any(line.requires_approval for line in lines)


async def test_approve_session_without_permission_raises(
    db_session: AsyncSession, seeded_warehouse
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    await svc.close_session(db_session, cs.id, ACTOR, NOW)
    # Teacher role has no inventory.approve_count permission
    teacher_roles = [_role(RoleType.TEACHER, ["resources.view"])]
    with pytest.raises(InsufficientPermissionError):
        await svc.approve_session(db_session, cs.id, "Good work", ACTOR, teacher_roles, NOW)


async def test_approve_session_with_admin_role_succeeds(
    db_session: AsyncSession, seeded_warehouse
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    await svc.close_session(db_session, cs.id, ACTOR, NOW)
    admin_roles = [_role(RoleType.ADMINISTRATOR, ["inventory.approve_count"])]
    approved = await svc.approve_session(db_session, cs.id, "Approved!", ACTOR, admin_roles, NOW)
    assert approved.status == CountSessionStatus.APPROVED


async def test_close_session_does_not_mutate_inventory_for_requires_approval_lines(
    db_session: AsyncSession, seeded_warehouse, seeded_inventory_item,
    seeded_location, seeded_stock_balance
):
    """High-variance lines (requires_approval=True) must NOT create ledger entries on close."""
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    # qty=100, count=60 → variance=-40 × $9.99 = $399.60 > $250 → requires_approval=True
    await svc.add_count_line(
        db_session, cs.id,
        uuid.UUID(seeded_inventory_item.id),
        uuid.UUID(seeded_location.id),
        counted_qty=60, reason_code="LOSS", operator_id=ACTOR, now=NOW,
    )
    await svc.close_session(db_session, cs.id, ACTOR, NOW)

    ledger_repo = LedgerRepository()
    entries, _ = await ledger_repo.list(
        db_session,
        item_id=uuid.UUID(seeded_inventory_item.id),
        location_id=uuid.UUID(seeded_location.id),
    )
    count_close_entries = [e for e in entries if e.entry_type.value == "COUNT_CLOSE"]
    assert len(count_close_entries) == 0  # Deferred until approved


async def test_approve_session_writes_deferred_ledger_entries(
    db_session: AsyncSession, seeded_warehouse, seeded_inventory_item,
    seeded_location, seeded_stock_balance
):
    """approve_session must write the ledger entry deferred for a requires_approval line."""
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    # qty=100, count=60 → variance=-40 × $9.99 = $399.60 > $250 → requires_approval=True
    await svc.add_count_line(
        db_session, cs.id,
        uuid.UUID(seeded_inventory_item.id),
        uuid.UUID(seeded_location.id),
        counted_qty=60, reason_code="LOSS", operator_id=ACTOR, now=NOW,
    )
    await svc.close_session(db_session, cs.id, ACTOR, NOW)

    admin_roles = [_role(RoleType.ADMINISTRATOR, ["inventory.approve_count"])]
    await svc.approve_session(db_session, cs.id, "Approved!", ACTOR, admin_roles, NOW)

    ledger_repo = LedgerRepository()
    entries, _ = await ledger_repo.list(
        db_session,
        item_id=uuid.UUID(seeded_inventory_item.id),
        location_id=uuid.UUID(seeded_location.id),
    )
    count_close_entries = [e for e in entries if e.entry_type.value == "COUNT_CLOSE"]
    assert len(count_close_entries) == 1  # Written during approve, not close


async def test_resume_count_checkpoint_expires_inactive_active_session(
    db_session: AsyncSession,
    seeded_warehouse,
):
    svc = _make_service()
    old_time = NOW - timedelta(hours=9)
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, old_time
    )

    outcome = await svc.resume_count_checkpoint(db_session, cs.id, NOW)
    assert outcome == "expired"


async def test_resume_count_checkpoint_closed_session_returns_completed(
    db_session: AsyncSession,
    seeded_warehouse,
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    await svc.close_session(db_session, cs.id, ACTOR, NOW)

    outcome = await svc.resume_count_checkpoint(db_session, cs.id, NOW)
    assert outcome == "completed"


async def test_resume_approval_checkpoint_closed_session_returns_resumed(
    db_session: AsyncSession,
    seeded_warehouse,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    await svc.add_count_line(
        db_session,
        cs.id,
        uuid.UUID(seeded_inventory_item.id),
        uuid.UUID(seeded_location.id),
        counted_qty=60,
        reason_code="RECOUNT",
        operator_id=ACTOR,
        now=NOW,
    )
    await svc.close_session(db_session, cs.id, ACTOR, NOW)

    outcome = await svc.resume_approval_checkpoint(db_session, cs.id)
    assert outcome == "resumed"
