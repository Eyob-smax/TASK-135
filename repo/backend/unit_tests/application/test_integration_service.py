"""
Unit tests for IntegrationService — client lifecycle, key rotation, outbound events.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.integration_service import (
    IntegrationService,
    KeyRotationError,
)
from district_console.domain.exceptions import DomainValidationError
from district_console.application.auth_service import AuthService
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.orm import UserORM
from district_console.infrastructure.outbox_writer import OutboxWriter
from district_console.infrastructure.repositories import AuditRepository, IntegrationRepository
from district_console.infrastructure.repositories import RoleRepository, UserRepository


TEST_MASTER_KEY_HEX = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _make_service(lan_path=None):
    return IntegrationService(
        IntegrationRepository(),
        AuditWriter(AuditRepository()),
        OutboxWriter(lan_events_path=lan_path),
        master_key_hex=TEST_MASTER_KEY_HEX,
    )


NOW = datetime(2024, 6, 1, 10, 0, 0)
ACTOR = uuid.uuid4()


@pytest.fixture(autouse=True)
async def _seed_actor_user(db_session: AsyncSession) -> None:
    """Seed a user matching ACTOR so audit_event actor_id FK constraints pass."""
    auth = AuthService(UserRepository(), RoleRepository())
    now = datetime.utcnow().isoformat()
    db_session.add(
        UserORM(
            id=str(ACTOR),
            username="integration_actor",
            password_hash=auth.hash_password("SecurePassword1!"),
            is_active=True,
            failed_attempts=0,
            locked_until=None,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.flush()


async def test_create_client_returns_client_and_key(db_session: AsyncSession):
    svc = _make_service()
    client, key, raw_key = await svc.create_client(
        db_session, "ERP System", "ERP integration", ACTOR, NOW
    )
    assert client.name == "ERP System"
    assert client.is_active is True
    assert key.is_active is True
    assert len(raw_key) == 64
    assert all(ch in "0123456789abcdef" for ch in raw_key)
    assert key.key_encrypted != raw_key


async def test_create_client_empty_name_raises(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(DomainValidationError):
        await svc.create_client(db_session, "   ", "", ACTOR, NOW)


async def test_deactivate_client(db_session: AsyncSession):
    svc = _make_service()
    client, _, _ = await svc.create_client(
        db_session, "Attendance", "Attendance sync", ACTOR, NOW
    )
    deactivated = await svc.deactivate_client(db_session, client.id, ACTOR, NOW)
    assert deactivated.is_active is False


async def test_rotate_key_creates_next_key(db_session: AsyncSession):
    svc = _make_service()
    client, _, _ = await svc.create_client(
        db_session, "Finance", "Finance sync", ACTOR, NOW
    )
    next_key, raw_key = await svc.rotate_key(db_session, client.id, ACTOR, NOW)
    assert next_key.is_next is True
    assert next_key.is_active is False
    assert len(raw_key) == 64


async def test_rotate_key_twice_raises(db_session: AsyncSession):
    svc = _make_service()
    client, _, _ = await svc.create_client(db_session, "HR", "HR sync", ACTOR, NOW)
    await svc.rotate_key(db_session, client.id, ACTOR, NOW)
    with pytest.raises(KeyRotationError):
        await svc.rotate_key(db_session, client.id, ACTOR, NOW)


async def test_commit_rotation_promotes_next_key(db_session: AsyncSession):
    svc = _make_service()
    client, _, _ = await svc.create_client(
        db_session, "Library", "Library sync", ACTOR, NOW
    )
    await svc.rotate_key(db_session, client.id, ACTOR, NOW)
    promoted = await svc.commit_rotation(db_session, client.id, ACTOR, NOW)
    assert promoted.is_active is True
    assert promoted.is_next is False


async def test_enforce_key_lifecycle_deactivates_expired_active_and_next(
    db_session: AsyncSession,
):
    svc = _make_service()
    client, active_key, _ = await svc.create_client(
        db_session, "Lifecycle", "Lifecycle sync", ACTOR, NOW
    )
    next_key, _ = await svc.rotate_key(db_session, client.id, ACTOR, NOW)

    result = await svc.enforce_key_lifecycle(db_session, NOW + timedelta(days=120))
    assert result["deactivated"] == 2

    repo = IntegrationRepository()
    keys = await repo.list_keys(db_session, client.id)
    active_after = next(k for k in keys if k.id == active_key.id)
    next_after = next(k for k in keys if k.id == next_key.id)
    assert active_after.is_active is False
    assert active_after.is_next is False
    assert next_after.is_active is False
    assert next_after.is_next is False


async def test_write_outbound_event_disabled_sets_pending(db_session: AsyncSession):
    svc = _make_service(lan_path=None)
    client, _, _ = await svc.create_client(
        db_session, "External", "External sync", ACTOR, NOW
    )
    event = await svc.write_outbound_event(
        db_session, client.id, "RESOURCE_PUBLISHED", {"id": "abc"}, NOW
    )
    assert event.status == "PENDING"
    assert "not configured" in (event.last_error or "")


async def test_retry_pending_marks_failed_after_max_retries(db_session: AsyncSession):
    svc = _make_service(lan_path=None)
    client, _, _ = await svc.create_client(db_session, "Retry Client", "", ACTOR, NOW)
    # Write event (will stay PENDING since outbox disabled)
    event = await svc.write_outbound_event(db_session, client.id, "TEST_EVENT", {}, NOW)
    assert event.status == "PENDING"

    # Force retry count to max by saving directly
    from district_console.infrastructure.repositories import IntegrationRepository
    repo = IntegrationRepository()
    event.retry_count = 5  # type: ignore[misc]
    await repo.save_event(db_session, event)

    result = await svc.retry_pending_events(db_session, NOW)
    assert result["failed"] >= 1
