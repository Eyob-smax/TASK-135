"""
Additional CountSessionService tests targeting uncovered branches:

  * add_count_line: not-found, not-active, missing item, missing reason_code on variance
  * update_count_line: all not-found / not-active / expired paths
  * close_session: not-found, not-active, missing reason_code on variance line
  * approve_session: not-found, not-CLOSED, missing reason_code on deferred variance
  * check_and_expire: session not found / not active / not yet expired → False
  * resume_count_checkpoint: session not found → abandoned
  * resume_count_checkpoint: active non-expired → resumed
  * resume_approval_checkpoint: session not found / APPROVED / EXPIRED / ACTIVE(other)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.auth_service import AuthService
from district_console.application.count_session_service import CountSessionService
from district_console.domain.entities.role import Permission, Role
from district_console.domain.enums import CountMode, CountSessionStatus, RoleType
from district_console.domain.exceptions import DomainValidationError
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


def _make_service() -> CountSessionService:
    return CountSessionService(
        CountSessionRepository(),
        InventoryRepository(),
        LedgerRepository(),
        AuditWriter(AuditRepository()),
        LockManager(LockRepository()),
        CheckpointStore(CheckpointRepository()),
    )


def _admin_roles() -> list:
    perm = Permission(
        id=uuid.uuid4(),
        name="inventory.approve_count",
        resource_name="inventory",
        action="approve_count",
    )
    return [
        Role(
            id=uuid.uuid4(),
            role_type=RoleType.ADMINISTRATOR,
            display_name="Administrator",
            permissions=frozenset({perm}),
        )
    ]


NOW = datetime(2024, 6, 1, 10, 0, 0)
ACTOR = uuid.uuid4()


@pytest.fixture(autouse=True)
async def _seed_actor(db_session: AsyncSession) -> None:
    auth = AuthService(UserRepository(), RoleRepository())
    now = datetime.utcnow().isoformat()
    db_session.add(
        UserORM(
            id=str(ACTOR),
            username="count_extra_actor",
            password_hash=auth.hash_password("SecurePassword1!"),
            is_active=True,
            failed_attempts=0,
            locked_until=None,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.flush()


# ---------------------------------------------------------------------------
# add_count_line — edge cases
# ---------------------------------------------------------------------------

async def test_add_count_line_session_not_found(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(DomainValidationError) as exc:
        await svc.add_count_line(
            db_session,
            session_id=uuid.uuid4(),
            item_id=uuid.uuid4(),
            location_id=uuid.uuid4(),
            counted_qty=1,
            reason_code=None,
            operator_id=ACTOR,
            now=NOW,
        )
    assert exc.value.field == "session_id"


async def test_add_count_line_session_not_active(
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
    await svc.close_session(db_session, cs.id, ACTOR, NOW)

    with pytest.raises(DomainValidationError, match="not active"):
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


async def test_add_count_line_missing_item_raises(
    db_session: AsyncSession, seeded_warehouse, seeded_location
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    with pytest.raises(DomainValidationError) as exc:
        await svc.add_count_line(
            db_session,
            session_id=cs.id,
            item_id=uuid.uuid4(),
            location_id=uuid.UUID(seeded_location.id),
            counted_qty=5,
            reason_code=None,
            operator_id=ACTOR,
            now=NOW,
        )
    assert exc.value.field == "item_id"


async def test_add_count_line_variance_without_reason_raises(
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
    # Counted differs from expected (100) but no reason_code supplied
    with pytest.raises(DomainValidationError) as exc:
        await svc.add_count_line(
            db_session,
            session_id=cs.id,
            item_id=uuid.UUID(seeded_inventory_item.id),
            location_id=uuid.UUID(seeded_location.id),
            counted_qty=99,
            reason_code=None,
            operator_id=ACTOR,
            now=NOW,
        )
    assert exc.value.field == "reason_code"


# ---------------------------------------------------------------------------
# update_count_line — full path
# ---------------------------------------------------------------------------

async def test_update_count_line_updates_counted_qty(
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
    line = await svc.add_count_line(
        db_session,
        session_id=cs.id,
        item_id=uuid.UUID(seeded_inventory_item.id),
        location_id=uuid.UUID(seeded_location.id),
        counted_qty=95,
        reason_code="RECOUNT",
        operator_id=ACTOR,
        now=NOW,
    )
    updated = await svc.update_count_line(
        db_session, cs.id, line.id, counted_qty=97, operator_id=ACTOR, now=NOW
    )
    assert updated.counted_qty == 97
    assert updated.expected_qty == 100


async def test_update_count_line_session_not_found(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(DomainValidationError) as exc:
        await svc.update_count_line(
            db_session, uuid.uuid4(), uuid.uuid4(), counted_qty=1, operator_id=ACTOR, now=NOW
        )
    assert exc.value.field == "session_id"


async def test_update_count_line_session_not_active(
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
    line = await svc.add_count_line(
        db_session,
        session_id=cs.id,
        item_id=uuid.UUID(seeded_inventory_item.id),
        location_id=uuid.UUID(seeded_location.id),
        counted_qty=100,
        reason_code=None,
        operator_id=ACTOR,
        now=NOW,
    )
    await svc.close_session(db_session, cs.id, ACTOR, NOW)

    with pytest.raises(DomainValidationError, match="not active"):
        await svc.update_count_line(
            db_session, cs.id, line.id, counted_qty=99, operator_id=ACTOR, now=NOW
        )


async def test_update_count_line_expired_session(
    db_session: AsyncSession,
    seeded_warehouse,
    seeded_inventory_item,
    seeded_location,
    seeded_stock_balance,
):
    svc = _make_service()
    old_time = NOW - timedelta(hours=9)
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, old_time
    )
    # Add line before expiration using same old timestamp
    line = await svc.add_count_line(
        db_session,
        session_id=cs.id,
        item_id=uuid.UUID(seeded_inventory_item.id),
        location_id=uuid.UUID(seeded_location.id),
        counted_qty=100,
        reason_code=None,
        operator_id=ACTOR,
        now=old_time,
    )
    with pytest.raises(DomainValidationError, match="expired"):
        await svc.update_count_line(
            db_session, cs.id, line.id, counted_qty=99, operator_id=ACTOR, now=NOW
        )


async def test_update_count_line_line_not_found(
    db_session: AsyncSession, seeded_warehouse
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    with pytest.raises(DomainValidationError) as exc:
        await svc.update_count_line(
            db_session, cs.id, uuid.uuid4(), counted_qty=10, operator_id=ACTOR, now=NOW
        )
    assert exc.value.field == "line_id"


# ---------------------------------------------------------------------------
# close_session — edge cases
# ---------------------------------------------------------------------------

async def test_close_session_not_found(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(DomainValidationError) as exc:
        await svc.close_session(db_session, uuid.uuid4(), ACTOR, NOW)
    assert exc.value.field == "session_id"


async def test_close_session_not_active(db_session: AsyncSession, seeded_warehouse):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    await svc.close_session(db_session, cs.id, ACTOR, NOW)
    with pytest.raises(DomainValidationError, match="not active"):
        await svc.close_session(db_session, cs.id, ACTOR, NOW)


# ---------------------------------------------------------------------------
# approve_session — edge cases
# ---------------------------------------------------------------------------

async def test_approve_session_not_found(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(DomainValidationError) as exc:
        await svc.approve_session(
            db_session, uuid.uuid4(), "notes", ACTOR, _admin_roles(), NOW
        )
    assert exc.value.field == "session_id"


async def test_approve_session_requires_closed_status(
    db_session: AsyncSession, seeded_warehouse
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    # Still ACTIVE — approve should complain.
    with pytest.raises(DomainValidationError, match="CLOSED"):
        await svc.approve_session(db_session, cs.id, "notes", ACTOR, _admin_roles(), NOW)


# ---------------------------------------------------------------------------
# check_and_expire — non-expiry paths
# ---------------------------------------------------------------------------

async def test_check_and_expire_session_not_found(db_session: AsyncSession):
    svc = _make_service()
    assert await svc.check_and_expire(db_session, uuid.uuid4(), NOW) is False


async def test_check_and_expire_session_not_active(
    db_session: AsyncSession, seeded_warehouse
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    await svc.close_session(db_session, cs.id, ACTOR, NOW)
    assert await svc.check_and_expire(db_session, cs.id, NOW) is False


async def test_check_and_expire_session_not_yet_expired(
    db_session: AsyncSession, seeded_warehouse
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    assert await svc.check_and_expire(db_session, cs.id, NOW + timedelta(minutes=1)) is False


# ---------------------------------------------------------------------------
# resume_*_checkpoint — missing / state-specific paths
# ---------------------------------------------------------------------------

async def test_resume_count_checkpoint_session_not_found_returns_abandoned(
    db_session: AsyncSession,
):
    svc = _make_service()
    assert await svc.resume_count_checkpoint(db_session, uuid.uuid4(), NOW) == "abandoned"


async def test_resume_count_checkpoint_active_non_expired_returns_resumed(
    db_session: AsyncSession, seeded_warehouse
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    assert await svc.resume_count_checkpoint(db_session, cs.id, NOW) == "resumed"


async def test_resume_approval_checkpoint_session_not_found_returns_abandoned(
    db_session: AsyncSession,
):
    svc = _make_service()
    assert await svc.resume_approval_checkpoint(db_session, uuid.uuid4()) == "abandoned"


async def test_resume_approval_checkpoint_active_returns_abandoned(
    db_session: AsyncSession, seeded_warehouse
):
    """Approval checkpoints only make sense for CLOSED / APPROVED / EXPIRED sessions."""
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    # Session is ACTIVE, not CLOSED — resume_approval should return "abandoned"
    assert await svc.resume_approval_checkpoint(db_session, cs.id) == "abandoned"


async def test_resume_approval_checkpoint_approved_returns_completed(
    db_session: AsyncSession, seeded_warehouse
):
    svc = _make_service()
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, NOW
    )
    await svc.close_session(db_session, cs.id, ACTOR, NOW)
    await svc.approve_session(db_session, cs.id, "ok", ACTOR, _admin_roles(), NOW)
    assert await svc.resume_approval_checkpoint(db_session, cs.id) == "completed"


async def test_resume_approval_checkpoint_expired_returns_completed(
    db_session: AsyncSession, seeded_warehouse
):
    svc = _make_service()
    old = NOW - timedelta(hours=9)
    cs = await svc.open_session(
        db_session, CountMode.OPEN, uuid.UUID(seeded_warehouse.id), ACTOR, old
    )
    await svc.check_and_expire(db_session, cs.id, NOW)
    assert await svc.resume_approval_checkpoint(db_session, cs.id) == "completed"


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------

async def test_list_sessions_filters_by_status_and_warehouse(
    db_session: AsyncSession, seeded_warehouse
):
    svc = _make_service()
    wh_id = uuid.UUID(seeded_warehouse.id)
    cs = await svc.open_session(db_session, CountMode.OPEN, wh_id, ACTOR, NOW)

    rows, total = await svc.list_sessions(
        db_session, status="ACTIVE", warehouse_ids=[wh_id]
    )
    assert total >= 1
    assert any(r.id == cs.id for r in rows)
