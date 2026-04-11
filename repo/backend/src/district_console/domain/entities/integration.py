"""
Integration domain entities: IntegrationClient, HmacKey, OutboundEvent, RateLimitState.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class IntegrationClient:
    """
    A registered local REST integration client.

    Integration clients are external processes on the same LAN that consume
    the District Console REST API. Each client has its own HMAC key set and
    rate limit state. There is no internet-facing registration; clients are
    created by Administrators through the admin UI.
    """
    id: uuid.UUID
    name: str
    description: str
    is_active: bool
    created_at: datetime


@dataclass
class HmacKey:
    """
    An HMAC-SHA256 signing key for an integration client.

    At most two keys are active per client at any time:
        is_active=True,  is_next=False — the current signing key
        is_active=False, is_next=True  — the next key (pre-generated for rotation)

    The rotation workflow:
    1. Administrator requests rotation: a new key is generated with is_next=True
    2. Client code is updated to use the next key
    3. On cutover date, the old key is deactivated and the next key becomes active
    4. The old key is deleted after a grace period

    key_encrypted stores the raw key material encrypted at rest by the
    infrastructure layer. The domain entity holds it as an opaque string.
    """
    id: uuid.UUID
    client_id: uuid.UUID
    key_encrypted: str         # Encrypted at rest by infrastructure layer
    created_at: datetime
    expires_at: datetime       # created_at + HMAC_KEY_ROTATION_DAYS
    is_active: bool
    is_next: bool              # True only for the pre-generated rotation key

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at

    def needs_rotation_warning(self, now: datetime, warning_days: int = 14) -> bool:
        """Return True if the key expires within warning_days."""
        from datetime import timedelta
        return (self.expires_at - now) <= timedelta(days=warning_days)


@dataclass
class OutboundEvent:
    """
    A webhook-style event to be delivered by writing a JSON file to the
    LAN-shared folder configured in DC_LAN_EVENTS_PATH.

    Delivery is best-effort with retry. The infrastructure outbox writer
    attempts to write the file; on failure it increments retry_count and
    records last_error. The APScheduler job retries pending events on a
    5-minute interval.

    status values: "PENDING", "DELIVERED", "FAILED"
    """
    id: uuid.UUID
    client_id: uuid.UUID
    event_type: str
    payload_json: str          # JSON string of the event payload
    status: str
    created_at: datetime
    delivered_at: Optional[datetime] = None
    retry_count: int = 0
    last_error: Optional[str] = None


@dataclass
class RateLimitState:
    """
    Sliding-window rate limit tracker for an integration client.

    window_start marks the beginning of the current 60-second window.
    request_count is the number of requests received in this window.
    The rate limiter resets window_start and request_count when the
    window expires.
    """
    id: uuid.UUID
    client_id: uuid.UUID
    window_start: datetime
    request_count: int

    def is_window_expired(self, now: datetime) -> bool:
        from datetime import timedelta
        return (now - self.window_start) >= timedelta(seconds=60)

    def is_limit_exceeded(self) -> bool:
        from district_console.domain.policies import RATE_LIMIT_RPM
        return self.request_count >= RATE_LIMIT_RPM
