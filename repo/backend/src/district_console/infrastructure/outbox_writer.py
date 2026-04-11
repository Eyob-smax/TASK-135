"""
LAN-shared folder outbox writer for outbound webhook-style events.

Writes OutboundEvent payloads as JSON files to a configurable directory
(DC_LAN_EVENTS_PATH). If the path is not configured, writing is disabled and
an OutboxDisabledError is raised.

Files are written atomically via a temp file + os.replace() to reduce the
risk of partial writes being consumed by readers on the shared folder.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from district_console.domain.entities.integration import OutboundEvent


class OutboxDisabledError(Exception):
    """Raised when DC_LAN_EVENTS_PATH is not configured."""


class OutboxWriteError(Exception):
    """Raised when writing an outbound event file fails."""


class OutboxWriter:
    """
    Writes outbound events as JSON files to a LAN-shared folder.

    File naming convention: ``{event_id}_{event_type}.json``

    Consumers on the same LAN read these files from the shared path.
    Delivery is best-effort: failures are recorded on the OutboundEvent
    record and retried by the APScheduler retry job every 5 minutes.
    """

    def __init__(self, lan_events_path: Optional[str] = None) -> None:
        self._path = lan_events_path

    @property
    def is_enabled(self) -> bool:
        return bool(self._path)

    def write_event(self, event: OutboundEvent) -> None:
        """
        Write event payload to the LAN-shared folder as a JSON file.

        Raises:
            OutboxDisabledError: DC_LAN_EVENTS_PATH is not configured.
            OutboxWriteError: The file cannot be written (permissions, missing mount, etc.).
        """
        if not self._path:
            raise OutboxDisabledError(
                "DC_LAN_EVENTS_PATH is not configured; outbound events are disabled."
            )

        target_dir = Path(self._path)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OutboxWriteError(
                f"Cannot create LAN events directory '{target_dir}': {exc}"
            ) from exc

        filename = f"{event.id}_{event.event_type}.json"
        target_file = target_dir / filename

        payload = {
            "event_id": str(event.id),
            "event_type": event.event_type,
            "client_id": str(event.client_id),
            "payload": json.loads(event.payload_json),
            "created_at": event.created_at.isoformat(),
        }
        serialized = json.dumps(payload, indent=2)

        # Atomic write: write to a temp file in the same directory, then rename.
        # os.replace() is atomic on POSIX; on Windows it overwrites atomically
        # since Python 3.3+ (wraps MoveFileExW with MOVEFILE_REPLACE_EXISTING).
        try:
            fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
            try:
                os.write(fd, serialized.encode("utf-8"))
            finally:
                os.close(fd)
            os.replace(tmp_path, target_file)
        except OSError as exc:
            # Clean up the temp file if rename failed
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise OutboxWriteError(
                f"Failed to write event file '{target_file}': {exc}"
            ) from exc
