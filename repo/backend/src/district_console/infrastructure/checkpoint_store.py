"""
Crash-safe checkpoint persistence for resumable long-running jobs.

On startup, the bootstrap module calls get_active() to find all ACTIVE
checkpoint records and resume each corresponding job from its saved state_json.

Job types (from CHECKPOINT_JOB_TYPES):
  - "import"     Resource file or CSV import batches
  - "count"      Count session reconciliation
  - "approval"   Pending review/approval workflows
  - "scheduled"  APScheduler background jobs
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from district_console.domain.entities.checkpoint import (
    CHECKPOINT_JOB_TYPES,
    CheckpointRecord,
)
from district_console.domain.enums import CheckpointStatus
from district_console.domain.exceptions import DomainValidationError
from district_console.infrastructure.repositories import (
    CheckpointRepository,
    _checkpoint_to_domain,
)


class CheckpointStore:
    """
    High-level API for saving and recovering job checkpoints.

    All methods operate within the caller's AsyncSession. The caller commits
    the transaction after calling these methods.
    """

    def __init__(self, repo: CheckpointRepository) -> None:
        self._repo = repo

    async def save(
        self,
        session: AsyncSession,
        job_type: str,
        job_id: str,
        state: dict,
    ) -> CheckpointRecord:
        """
        Create or update a checkpoint for (job_type, job_id).

        Status is set/reset to ACTIVE. Serialises state dict to JSON.

        Raises:
            DomainValidationError: If job_type is not in CHECKPOINT_JOB_TYPES.
        """
        if job_type not in CHECKPOINT_JOB_TYPES:
            raise DomainValidationError(
                field="job_type",
                value=job_type,
                constraint=f"job_type must be one of {sorted(CHECKPOINT_JOB_TYPES)}",
            )
        now = datetime.utcnow()
        state_json = json.dumps(state)
        orm = await self._repo.upsert(session, job_type, job_id, state_json, now)
        return _checkpoint_to_domain(orm)

    async def load(
        self,
        session: AsyncSession,
        job_type: str,
        job_id: str,
    ) -> Optional[CheckpointRecord]:
        """
        Load a checkpoint by (job_type, job_id). Returns None if not found.
        """
        orm = await self._repo.get(session, job_type, job_id)
        return _checkpoint_to_domain(orm) if orm else None

    async def mark_completed(
        self,
        session: AsyncSession,
        id: uuid.UUID,
    ) -> None:
        """Mark a checkpoint as COMPLETED."""
        now = datetime.utcnow()
        await self._repo.update_status(
            session, str(id), "COMPLETED", now
        )

    async def mark_failed(
        self,
        session: AsyncSession,
        id: uuid.UUID,
        reason: str,
    ) -> None:
        """Mark a checkpoint as FAILED and store the failure reason in state_json."""
        now = datetime.utcnow()
        await self._repo.update_status(
            session, str(id), "FAILED", now,
            extra_state_fields={"failure_reason": reason},
        )

    async def get_active(
        self,
        session: AsyncSession,
    ) -> list[CheckpointRecord]:
        """
        Return all ACTIVE checkpoints. Called on startup to resume in-flight jobs.
        """
        orms = await self._repo.get_active(session)
        return [_checkpoint_to_domain(orm) for orm in orms]
