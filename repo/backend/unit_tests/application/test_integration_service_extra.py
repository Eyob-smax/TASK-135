"""
Additional IntegrationService tests covering uncovered branches:

  * commit_rotation without a pending next key → KeyRotationError
  * enforce_key_lifecycle skips non-expired keys and already-inactive keys
  * write_outbound_event success path with a real LAN folder
  * write_outbound_event OutboxWriteError path (read-only target)
  * retry_pending_events success + OutboxWriteError paths
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.auth_service import AuthService
from district_console.application.integration_service import (
    IntegrationService,
    KeyRotationError,
)
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.orm import UserORM
from district_console.infrastructure.outbox_writer import (
    OutboxWriteError,
    OutboxWriter,
)
from district_console.infrastructure.repositories import (
    AuditRepository,
    IntegrationRepository,
    RoleRepository,
    UserRepository,
)


TEST_MASTER_KEY_HEX = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
NOW = datetime(2024, 6, 1, 10, 0, 0)
ACTOR = uuid.uuid4()


def _make_service(lan_path: str | None = None) -> IntegrationService:
    return IntegrationService(
        IntegrationRepository(),
        AuditWriter(AuditRepository()),
        OutboxWriter(lan_events_path=lan_path),
        master_key_hex=TEST_MASTER_KEY_HEX,
    )


@pytest.fixture(autouse=True)
async def _seed_actor(db_session: AsyncSession) -> None:
    auth = AuthService(UserRepository(), RoleRepository())
    now = datetime.utcnow().isoformat()
    db_session.add(
        UserORM(
            id=str(ACTOR),
            username="integration_extra_actor",
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
# Key rotation commit branches
# ---------------------------------------------------------------------------

async def test_commit_rotation_without_pending_key_raises(db_session: AsyncSession):
    svc = _make_service()
    client, _, _ = await svc.create_client(db_session, "Svc", "", ACTOR, NOW)
    with pytest.raises(KeyRotationError):
        await svc.commit_rotation(db_session, client.id, ACTOR, NOW)


# ---------------------------------------------------------------------------
# Key lifecycle skip branches
# ---------------------------------------------------------------------------

async def test_enforce_key_lifecycle_skips_non_expired_keys(db_session: AsyncSession):
    """Keys whose expires_at is in the future must be skipped."""
    svc = _make_service()
    client, _, _ = await svc.create_client(db_session, "NotExpired", "", ACTOR, NOW)
    # Run before the default 90-day TTL — both active key should be skipped
    result = await svc.enforce_key_lifecycle(db_session, NOW + timedelta(days=10))
    assert result["deactivated"] == 0


async def test_enforce_key_lifecycle_skips_already_inactive_keys(db_session: AsyncSession):
    """
    Keys that are already is_active=False and is_next=False must be skipped
    even when expired — they were already lifecycled.
    """
    svc = _make_service()
    client, _, _ = await svc.create_client(db_session, "Old", "", ACTOR, NOW)

    # First pass — deactivates the active key
    first = await svc.enforce_key_lifecycle(db_session, NOW + timedelta(days=120))
    assert first["deactivated"] == 1

    # Second pass on the same (now-inactive) key must skip it
    second = await svc.enforce_key_lifecycle(db_session, NOW + timedelta(days=200))
    assert second["deactivated"] == 0


# ---------------------------------------------------------------------------
# Outbound delivery success / failure
# ---------------------------------------------------------------------------

async def test_write_outbound_event_success_sets_delivered(
    db_session: AsyncSession, tmp_path: Path
):
    outbox_dir = tmp_path / "events"
    svc = _make_service(lan_path=str(outbox_dir))
    client, _, _ = await svc.create_client(db_session, "Sync", "", ACTOR, NOW)

    event = await svc.write_outbound_event(
        db_session, client.id, "PING", {"hello": "world"}, NOW
    )
    assert event.status == "DELIVERED"
    assert event.delivered_at == NOW
    # File was written
    files = list(outbox_dir.iterdir())
    # exactly one file (tmp files are renamed in place)
    actual = [f for f in files if f.suffix == ".json"]
    assert len(actual) == 1
    data = json.loads(actual[0].read_text())
    assert data["event_type"] == "PING"
    assert data["payload"] == {"hello": "world"}


async def test_write_outbound_event_write_error_sets_last_error(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Simulate an OutboxWriteError so the except-branch in write_outbound_event runs."""
    svc = _make_service(lan_path="/some/path")
    client, _, _ = await svc.create_client(db_session, "FailSync", "", ACTOR, NOW)

    def _raise(event):
        raise OutboxWriteError("disk is on fire")

    monkeypatch.setattr(svc._outbox_writer, "write_event", _raise)

    event = await svc.write_outbound_event(db_session, client.id, "PING", {}, NOW)
    assert event.status == "PENDING"
    assert "disk is on fire" in (event.last_error or "")


# ---------------------------------------------------------------------------
# Retry loop branches
# ---------------------------------------------------------------------------

async def test_retry_pending_events_delivers_successful(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """
    First write with outbox disabled → PENDING.
    Then swap the outbox to a real path and retry → DELIVERED.
    """
    svc = _make_service(lan_path=None)
    client, _, _ = await svc.create_client(db_session, "Retry", "", ACTOR, NOW)

    pending = await svc.write_outbound_event(db_session, client.id, "PING", {"a": 1}, NOW)
    assert pending.status == "PENDING"

    # Swap underlying outbox to a real writable directory so retry succeeds
    real_outbox = tmp_path / "events"
    monkeypatch.setattr(svc, "_outbox_writer", OutboxWriter(lan_events_path=str(real_outbox)))

    result = await svc.retry_pending_events(db_session, NOW + timedelta(minutes=5))
    assert result["delivered"] >= 1


async def test_retry_pending_events_write_error_increments_retry(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """OutboxWriteError during retry must not crash the loop and must bump retry_count."""
    svc = _make_service(lan_path="/some/path")
    client, _, _ = await svc.create_client(db_session, "RetryFail", "", ACTOR, NOW)

    # First write — make the outbox explode so we get a PENDING row
    def _raise(event):
        raise OutboxWriteError("boom")

    monkeypatch.setattr(svc._outbox_writer, "write_event", _raise)
    await svc.write_outbound_event(db_session, client.id, "PING", {}, NOW)

    result = await svc.retry_pending_events(db_session, NOW + timedelta(minutes=5))
    assert result["failed"] >= 1
