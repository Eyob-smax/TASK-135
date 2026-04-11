"""
Integration management application service.

Handles integration client registration, HMAC key lifecycle (rotation,
commit), outbound event writing to the LAN-shared folder, and retry of
failed/pending deliveries.
"""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

from district_console.domain.entities.integration import (
    HmacKey,
    IntegrationClient,
    OutboundEvent,
)
from district_console.domain.exceptions import DomainValidationError
from district_console.infrastructure.hmac_signer import encrypt_hmac_key
from district_console.infrastructure.outbox_writer import OutboxDisabledError, OutboxWriteError

# Default key TTL: 90 days
_KEY_TTL_DAYS = 90
# Max outbox retries before event is marked FAILED
_MAX_RETRY_COUNT = 5


class KeyRotationError(Exception):
    """Raised when a rotation precondition is not met."""


class IntegrationService:
    """
    Application service for local integration management.

    Integration clients authenticate to the local REST API using
    HMAC-SHA256 signed requests. Outbound events are written as JSON
    files to a LAN-shared folder (DC_LAN_EVENTS_PATH).
    """

    def __init__(
        self,
        integration_repo,
        audit_writer,
        outbox_writer,
        master_key_hex: str = "",
    ) -> None:
        self._repo = integration_repo
        self._audit_writer = audit_writer
        self._outbox_writer = outbox_writer
        self._master_key_hex = master_key_hex

    # ------------------------------------------------------------------
    # Client management
    # ------------------------------------------------------------------

    async def list_clients(self, session) -> list[IntegrationClient]:
        return await self._repo.list_clients(session)

    async def create_client(
        self,
        session,
        name: str,
        description: str,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> tuple[IntegrationClient, HmacKey, str]:
        if not name.strip():
            raise DomainValidationError("name", name, "must not be empty")

        client = IntegrationClient(
            id=uuid.uuid4(),
            name=name,
            description=description,
            is_active=True,
            created_at=now,
        )
        client = await self._repo.save_client(session, client)

        # Generate initial HMAC key and encrypt at rest
        raw_key = secrets.token_hex(32)
        hmac_key = HmacKey(
            id=uuid.uuid4(),
            client_id=client.id,
            key_encrypted=encrypt_hmac_key(raw_key, self._master_key_hex),
            created_at=now,
            expires_at=now + timedelta(days=_KEY_TTL_DAYS),
            is_active=True,
            is_next=False,
        )
        await self._repo.save_key(session, hmac_key)

        await self._audit_writer.write(
            session,
            entity_type="integration_client",
            entity_id=client.id,
            action="CLIENT_CREATED",
            actor_id=actor_id,
            metadata={"name": name},
        )
        # Return raw_key so the router can expose it once (one-time reveal)
        return client, hmac_key, raw_key

    async def deactivate_client(
        self,
        session,
        client_id: uuid.UUID,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> IntegrationClient:
        client = await self._repo.get_client(session, client_id)
        if client is None:
            raise DomainValidationError("client_id", str(client_id), "not found")
        deactivated = IntegrationClient(
            id=client.id,
            name=client.name,
            description=client.description,
            is_active=False,
            created_at=client.created_at,
        )
        deactivated = await self._repo.save_client(session, deactivated)
        await self._audit_writer.write(
            session,
            entity_type="integration_client",
            entity_id=client_id,
            action="CLIENT_DEACTIVATED",
            actor_id=actor_id,
        )
        return deactivated

    # ------------------------------------------------------------------
    # Key rotation
    # ------------------------------------------------------------------

    async def rotate_key(
        self,
        session,
        client_id: uuid.UUID,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> tuple[HmacKey, str]:
        """
        Pre-generate a next key (is_next=True) for an integration client.

        The old key remains active so callers have time to update their
        configuration before calling commit_rotation().
        """
        existing_next = await self._repo.get_next_key_for_client(session, client_id)
        if existing_next is not None:
            raise KeyRotationError(
                f"Client {client_id} already has a pending rotation key. "
                "Call commit_rotation() first."
            )
        raw_key = secrets.token_hex(32)
        next_key = HmacKey(
            id=uuid.uuid4(),
            client_id=client_id,
            key_encrypted=encrypt_hmac_key(raw_key, self._master_key_hex),
            created_at=now,
            expires_at=now + timedelta(days=_KEY_TTL_DAYS),
            is_active=False,
            is_next=True,
        )
        await self._repo.save_key(session, next_key)
        await self._audit_writer.write(
            session,
            entity_type="integration_client",
            entity_id=client_id,
            action="KEY_ROTATION",
            actor_id=actor_id,
            metadata={"phase": "rotate_initiated"},
        )
        # Return raw_key alongside entity for one-time reveal in the response
        return next_key, raw_key

    async def commit_rotation(
        self,
        session,
        client_id: uuid.UUID,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> HmacKey:
        """
        Promote the next key to active, deactivating the old one.
        """
        next_key = await self._repo.get_next_key_for_client(session, client_id)
        if next_key is None:
            raise KeyRotationError(
                f"Client {client_id} has no pending rotation key. Call rotate_key() first."
            )
        old_key = await self._repo.get_active_key_for_client(session, client_id)
        if old_key is not None:
            deactivated = HmacKey(
                id=old_key.id,
                client_id=old_key.client_id,
                key_encrypted=old_key.key_encrypted,
                created_at=old_key.created_at,
                expires_at=old_key.expires_at,
                is_active=False,
                is_next=False,
            )
            await self._repo.save_key(session, deactivated)

        promoted = HmacKey(
            id=next_key.id,
            client_id=next_key.client_id,
            key_encrypted=next_key.key_encrypted,
            created_at=next_key.created_at,
            expires_at=next_key.expires_at,
            is_active=True,
            is_next=False,
        )
        await self._repo.save_key(session, promoted)
        await self._audit_writer.write(
            session,
            entity_type="integration_client",
            entity_id=client_id,
            action="KEY_ROTATION",
            actor_id=actor_id,
            metadata={"phase": "rotation_committed"},
        )
        return promoted

    async def enforce_key_lifecycle(
        self,
        session,
        now: datetime,
    ) -> dict[str, int]:
        """
        Deactivate expired active/next keys to enforce 90-day lifecycle boundaries.

        Returns a summary dict with key "deactivated".
        """
        deactivated = 0
        clients = await self._repo.list_clients(session)
        for client in clients:
            keys = await self._repo.list_keys(session, client.id)
            for key in keys:
                if key.expires_at > now:
                    continue
                if not key.is_active and not key.is_next:
                    continue

                expired_key = HmacKey(
                    id=key.id,
                    client_id=key.client_id,
                    key_encrypted=key.key_encrypted,
                    created_at=key.created_at,
                    expires_at=key.expires_at,
                    is_active=False,
                    is_next=False,
                )
                await self._repo.save_key(session, expired_key)
                deactivated += 1

        return {"deactivated": deactivated}

    # ------------------------------------------------------------------
    # Outbound events
    # ------------------------------------------------------------------

    async def write_outbound_event(
        self,
        session,
        client_id: uuid.UUID,
        event_type: str,
        payload: dict,
        now: datetime,
    ) -> OutboundEvent:
        """
        Create an OutboundEvent and attempt immediate delivery to the LAN folder.

        On write success: status=DELIVERED.
        On write failure: status=PENDING, last_error set.
        If outbox is disabled (DC_LAN_EVENTS_PATH not set): status=PENDING.
        """
        event = OutboundEvent(
            id=uuid.uuid4(),
            client_id=client_id,
            event_type=event_type,
            payload_json=json.dumps(payload),
            status="PENDING",
            created_at=now,
        )
        event = await self._repo.save_event(session, event)

        try:
            self._outbox_writer.write_event(event)
            event.status = "DELIVERED"  # type: ignore[misc]
            event.delivered_at = now  # type: ignore[misc]
        except OutboxDisabledError:
            # Outbox not configured — stays PENDING, will not retry
            event.last_error = "LAN events path not configured"  # type: ignore[misc]
        except OutboxWriteError as exc:
            event.last_error = str(exc)[:500]  # type: ignore[misc]

        event = await self._repo.save_event(session, event)
        return event

    async def retry_pending_events(
        self, session, now: datetime
    ) -> dict[str, int]:
        """
        Retry all PENDING outbound events. Called by the APScheduler job.

        Returns dict with keys "delivered" and "failed" counts.
        Events that exceed _MAX_RETRY_COUNT are marked FAILED.
        """
        pending = await self._repo.get_pending_events(session)
        delivered = 0
        failed = 0
        for event in pending:
            if event.retry_count >= _MAX_RETRY_COUNT:
                event.status = "FAILED"  # type: ignore[misc]
                await self._repo.save_event(session, event)
                failed += 1
                continue
            try:
                self._outbox_writer.write_event(event)
                event.status = "DELIVERED"  # type: ignore[misc]
                event.delivered_at = now  # type: ignore[misc]
                event.retry_count = event.retry_count + 1  # type: ignore[misc]
                delivered += 1
            except (OutboxDisabledError, OutboxWriteError) as exc:
                event.last_error = str(exc)[:500]  # type: ignore[misc]
                event.retry_count = event.retry_count + 1  # type: ignore[misc]
                failed += 1
            await self._repo.save_event(session, event)
        return {"delivered": delivered, "failed": failed}

    async def list_events(
        self,
        session,
        client_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[OutboundEvent], int]:
        return await self._repo.list_events(
            session, client_id=client_id, status=status, offset=offset, limit=limit
        )
