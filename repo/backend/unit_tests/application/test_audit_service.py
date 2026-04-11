"""
Unit tests for AuditService — event browsing, security events, and checkpoint status.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.audit_service import AuditService
from district_console.application.auth_service import AuthService
from district_console.infrastructure.orm import UserORM
from district_console.infrastructure.repositories import AuditQueryRepository, CheckpointRepository
from district_console.infrastructure.repositories import RoleRepository, UserRepository


def _make_service():
    return AuditService(AuditQueryRepository(), CheckpointRepository())


NOW = datetime(2024, 6, 1, 10, 0, 0)
ACTOR = uuid.uuid4()


@pytest.fixture(autouse=True)
async def _seed_actor_user(db_session: AsyncSession) -> None:
    auth = AuthService(UserRepository(), RoleRepository())
    now = datetime.utcnow().isoformat()
    db_session.add(
        UserORM(
            id=str(ACTOR),
            username="audit_actor",
            password_hash=auth.hash_password("SecurePassword1!"),
            is_active=True,
            failed_attempts=0,
            locked_until=None,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.flush()


async def test_list_audit_events_returns_empty_initially(db_session: AsyncSession):
    svc = _make_service()
    events, total = await svc.list_audit_events(db_session)
    assert events == []
    assert total == 0


async def test_list_audit_events_filters_by_entity_type(db_session: AsyncSession):
    """Events should be filterable by entity_type."""
    svc = _make_service()
    # Seed some audit events
    from district_console.infrastructure.audit_writer import AuditWriter
    from district_console.infrastructure.repositories import AuditRepository
    writer = AuditWriter(AuditRepository())
    await writer.write(db_session, "resource", uuid.uuid4(), "IMPORTED", ACTOR)
    await writer.write(db_session, "user", uuid.uuid4(), "LOGIN", ACTOR)

    events, total = await svc.list_audit_events(db_session, entity_type="resource")
    assert total == 1
    assert events[0].entity_type == "resource"


async def test_list_security_events_filters_login_actions(db_session: AsyncSession):
    svc = _make_service()
    from district_console.infrastructure.audit_writer import AuditWriter
    from district_console.infrastructure.repositories import AuditRepository
    writer = AuditWriter(AuditRepository())
    await writer.write(db_session, "user", uuid.uuid4(), "LOGIN", ACTOR)
    await writer.write(db_session, "user", uuid.uuid4(), "ACCOUNT_LOCKED", ACTOR)
    await writer.write(db_session, "resource", uuid.uuid4(), "IMPORTED", ACTOR)

    events, total = await svc.list_security_events(db_session)
    # Only LOGIN and ACCOUNT_LOCKED should be returned
    assert total == 2
    actions = {e.action for e in events}
    assert "LOGIN" in actions
    assert "ACCOUNT_LOCKED" in actions
    assert "IMPORTED" not in actions


async def test_list_approval_queue_filters_approval_checkpoints(db_session: AsyncSession):
    svc = _make_service()
    from district_console.infrastructure.checkpoint_store import CheckpointStore
    from district_console.infrastructure.repositories import CheckpointRepository
    store = CheckpointStore(CheckpointRepository())
    await store.save(db_session, "approval", "session-001", {"step": "awaiting_approval"})
    await store.save(db_session, "count", "count-001", {"step": "in_progress"})

    queue = await svc.list_approval_queue(db_session)
    assert len(queue) == 1
    assert queue[0].job_type == "approval"


async def test_list_checkpoint_status_excludes_completed(db_session: AsyncSession):
    svc = _make_service()
    from district_console.infrastructure.checkpoint_store import CheckpointStore
    from district_console.infrastructure.repositories import CheckpointRepository
    store = CheckpointStore(CheckpointRepository())
    await store.save(db_session, "import", "job-001", {"step": "started"})
    await store.save(db_session, "count", "job-002", {"step": "failed"})
    failed_cp = await store.load(db_session, "count", "job-002")
    assert failed_cp is not None
    await store.mark_failed(db_session, failed_cp.id, "test failure")

    await store.save(db_session, "import", "job-003", {"step": "completed"})
    completed_cp = await store.load(db_session, "import", "job-003")
    assert completed_cp is not None
    await store.mark_completed(db_session, completed_cp.id)

    statuses = await svc.list_checkpoint_status(db_session)
    # Should include ACTIVE and FAILED but not COMPLETED
    status_values = {s.status.value for s in statuses}
    assert "ACTIVE" in status_values
    assert "FAILED" in status_values
    assert "COMPLETED" not in status_values
