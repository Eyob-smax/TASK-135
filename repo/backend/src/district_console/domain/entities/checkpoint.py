"""
Checkpoint and recovery domain entity.

CheckpointRecord persists enough state for a resumable job to continue
from its last successful point after an application crash or restart.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from district_console.domain.enums import CheckpointStatus

#: Allowed job type identifiers
CHECKPOINT_JOB_TYPES = frozenset({"import", "count", "approval", "scheduled"})


@dataclass
class CheckpointRecord:
    """
    A durable record of a long-running job's progress.

    job_type must be one of the values in CHECKPOINT_JOB_TYPES.
    job_id is the primary key of the associated domain record
    (e.g. import batch ID, count_session.id, review_task.id).

    state_json is the serialised progress snapshot. Its schema is
    specific to each job_type and defined in the corresponding service.
    For an import job, state_json might contain:
        {"processed_rows": 142, "total_rows": 500, "last_file_hash": "abc..."}

    On startup, the bootstrap module queries for all ACTIVE checkpoints
    and calls the appropriate service's resume method with the state_json.
    """
    id: uuid.UUID
    job_type: str
    job_id: str                # String PK of the associated domain record
    state_json: str            # JSON-encoded progress snapshot
    status: CheckpointStatus
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.job_type not in CHECKPOINT_JOB_TYPES:
            from district_console.domain.exceptions import DomainValidationError
            raise DomainValidationError(
                field="job_type",
                value=self.job_type,
                constraint=f"job_type must be one of {sorted(CHECKPOINT_JOB_TYPES)}.",
            )

    def mark_completed(self, now: datetime) -> None:
        self.status = CheckpointStatus.COMPLETED
        self.updated_at = now

    def mark_failed(self, now: datetime) -> None:
        self.status = CheckpointStatus.FAILED
        self.updated_at = now
