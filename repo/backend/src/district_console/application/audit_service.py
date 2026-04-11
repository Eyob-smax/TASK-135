"""
Audit trail and admin visibility service.

Provides read-only access to the immutable audit_events table for admin
browsing, security event inspection, approval queue recovery, and
checkpoint resume status visibility.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from district_console.domain.entities.checkpoint import CheckpointRecord
from district_console.domain.entities.resource import AuditEvent


class AuditService:
    """
    Application service for audit trail browsing and admin visibility.

    All methods are read-only — no mutations are made to audit_events
    (append-only invariant). Checkpoint and approval queue methods
    surface in-progress records for the admin recovery panel.
    """

    def __init__(self, audit_query_repo, checkpoint_repo) -> None:
        self._audit_repo = audit_query_repo
        self._checkpoint_repo = checkpoint_repo

    # ------------------------------------------------------------------
    # Audit event browsing
    # ------------------------------------------------------------------

    async def list_audit_events(
        self,
        session,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        action: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AuditEvent], int]:
        return await self._audit_repo.list_events(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            action=action,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )

    async def list_security_events(
        self, session, offset: int = 0, limit: int = 50
    ) -> tuple[list[AuditEvent], int]:
        """
        Return login, lockout, logout, and key-rotation audit events.

        Covers: LOGIN, LOGIN_FAILED, ACCOUNT_LOCKED, LOGOUT, KEY_ROTATION
        """
        return await self._audit_repo.list_security_events(
            session, offset=offset, limit=limit
        )

    # ------------------------------------------------------------------
    # Approval queue recovery
    # ------------------------------------------------------------------

    async def list_approval_queue(self, session) -> list[CheckpointRecord]:
        """
        Return all ACTIVE checkpoints with job_type='approval'.

        These are count sessions that have been closed and require supervisor
        approval but have not yet been actioned. Surface in the admin panel
        for recovery after a crash or restart.
        """
        all_active = await self._checkpoint_repo.get_active(session)
        return [
            _checkpoint_to_domain(c)
            for c in all_active
            if c.job_type == "approval"
        ]

    async def list_checkpoint_status(self, session) -> list[CheckpointRecord]:
        """
        Return all non-COMPLETED checkpoint records for admin visibility.

        Covers ACTIVE, FAILED, ABANDONED states — anything that may need
        attention or manual intervention.
        """
        from sqlalchemy import select
        from district_console.infrastructure.orm import CheckpointRecordORM
        result = await session.execute(
            select(CheckpointRecordORM).where(
                CheckpointRecordORM.status.in_(["ACTIVE", "FAILED", "ABANDONED"])
            ).order_by(CheckpointRecordORM.updated_at.desc())
        )
        return [_checkpoint_to_domain(c) for c in result.scalars().all()]


def _checkpoint_to_domain(orm) -> CheckpointRecord:
    import uuid as _uuid
    from datetime import datetime as _dt
    from district_console.domain.enums import CheckpointStatus
    return CheckpointRecord(
        id=_uuid.UUID(orm.id),
        job_type=orm.job_type,
        job_id=orm.job_id,
        state_json=orm.state_json,
        status=CheckpointStatus(orm.status),
        created_at=_dt.fromisoformat(orm.created_at),
        updated_at=_dt.fromisoformat(orm.updated_at),
    )
