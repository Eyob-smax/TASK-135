"""
Unit tests for OutboxWriter — enabled/disabled paths and atomic file write.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from district_console.domain.entities.integration import OutboundEvent
from district_console.infrastructure.outbox_writer import (
    OutboxDisabledError,
    OutboxWriteError,
    OutboxWriter,
)


def _make_event(event_type="RESOURCE_PUBLISHED") -> OutboundEvent:
    return OutboundEvent(
        id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        event_type=event_type,
        payload_json='{"resource_id": "abc"}',
        status="PENDING",
        created_at=datetime(2024, 6, 1, 10, 0, 0),
    )


def test_write_event_disabled_raises_outbox_disabled_error():
    writer = OutboxWriter(lan_events_path=None)
    with pytest.raises(OutboxDisabledError):
        writer.write_event(_make_event())


def test_is_enabled_false_when_path_not_set():
    writer = OutboxWriter(lan_events_path=None)
    assert writer.is_enabled is False


def test_write_event_creates_json_file(tmp_path: Path):
    writer = OutboxWriter(lan_events_path=str(tmp_path))
    event = _make_event("STOCK_ADJUSTED")
    writer.write_event(event)

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1

    filename = files[0].name
    assert str(event.id) in filename
    assert "STOCK_ADJUSTED" in filename

    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["event_type"] == "STOCK_ADJUSTED"
    assert payload["event_id"] == str(event.id)
    assert "payload" in payload


def test_write_event_invalid_path_raises_outbox_write_error(tmp_path: Path):
    # Use a path that cannot be created (file already exists with same name)
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory")
    writer = OutboxWriter(lan_events_path=str(blocker))
    with pytest.raises(OutboxWriteError):
        writer.write_event(_make_event())
