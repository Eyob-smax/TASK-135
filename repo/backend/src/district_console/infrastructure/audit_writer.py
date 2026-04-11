"""
Append-only audit event writer.

AuditEvent records are immutable by design:
  - The domain AuditEvent dataclass uses frozen=True.
  - The AuditRepository.append() method only issues INSERT statements.
  - No UPDATE or DELETE is ever issued against the audit_events table.

This writer is the sole path for persisting audit events. All application
services that need to record a security-relevant action call write() here.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from district_console.domain.entities.resource import AuditEvent
from district_console.infrastructure.repositories import AuditRepository


class AuditWriter:
    """
    Creates and persists immutable AuditEvent records.

    Usage:
        event = await audit_writer.write(
            session,
            entity_type="User",
            entity_id=user.id,
            action="LOGIN_SUCCESS",
            actor_id=user.id,
            metadata={"username": user.username},
        )
        # event is a frozen AuditEvent domain object
    """

    def __init__(self, repo: AuditRepository) -> None:
        self._repo = repo

    async def write(
        self,
        session: AsyncSession,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        actor_id: uuid.UUID,
        metadata: Optional[dict] = None,
    ) -> AuditEvent:
        """
        Create and persist an AuditEvent.

        Args:
            session:     Open AsyncSession (caller manages transaction).
            entity_type: Logical entity class name, e.g. "User", "Resource".
            entity_id:   UUID of the affected entity.
            action:      Verb describing the action, e.g. "LOGIN_FAILED".
            actor_id:    UUID of the user performing the action.
            metadata:    Optional dict of additional context. Never include
                         secrets — the logging_config.SanitizingFilter also
                         covers log records, but this dict is persisted to DB.

        Returns:
            The frozen AuditEvent domain object that was persisted.

        Note:
            APPEND-ONLY — this method never updates or deletes audit events.
        """
        event = AuditEvent(
            id=uuid.uuid4(),
            entity_type=entity_type,
            entity_id=str(entity_id),
            action=action,
            actor_id=actor_id,
            timestamp=datetime.utcnow(),
            metadata=metadata or {},
        )
        # APPEND-ONLY: only INSERT is issued — see AuditRepository.append()
        await self._repo.append(session, event)
        return event
