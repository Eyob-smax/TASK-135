"""
Resource library domain entities: Resource, ResourceRevision, ReviewTask, AuditEvent.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from district_console.domain.enums import ResourceStatus, ResourceType, ReviewDecision


@dataclass
class Resource:
    """
    A reading resource record (book, picture book, article, or audio).

    dedup_key is computed from the SHA-256 file fingerprint combined with the
    ISBN (or a metadata hash when ISBN is absent). If a new import produces
    the same dedup_key as an existing resource, a DuplicateResourceError is
    raised and the import is offered as a new revision instead.

    status follows the workflow:
        DRAFT → IN_REVIEW → PUBLISHED
                         ↘ UNPUBLISHED
    """
    id: uuid.UUID
    title: str
    resource_type: ResourceType
    status: ResourceStatus
    file_fingerprint: str      # SHA-256 hex of the primary file
    isbn: Optional[str]        # None for non-book resource types
    dedup_key: str             # Computed: hash(fingerprint + (isbn or ""))
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    owner_scope_type: Optional[str] = None   # SCHOOL/DEPARTMENT/CLASS/INDIVIDUAL; None = district-wide
    owner_scope_ref_id: Optional[str] = None # FK to the owning scope entity; None = district-wide

    def can_transition_to(self, new_status: ResourceStatus) -> bool:
        """Return True if the transition to new_status is permitted."""
        from district_console.domain.enums import VALID_RESOURCE_TRANSITIONS
        return (self.status, new_status) in VALID_RESOURCE_TRANSITIONS


@dataclass(frozen=True)
class ResourceRevision:
    """
    An immutable snapshot of a resource file at a point in time.

    revision_number is 1-based and must be unique per resource_id.
    At most MAX_RESOURCE_REVISIONS revisions are retained; the infrastructure
    layer prunes the oldest when a new one exceeds the limit.
    """
    id: uuid.UUID
    resource_id: uuid.UUID
    revision_number: int       # 1-based; unique per resource_id
    file_path: str             # Absolute local path to the stored file
    file_hash: str             # SHA-256 hex of the file at this revision
    file_size: int             # Bytes
    imported_by: uuid.UUID
    created_at: datetime


@dataclass
class ReviewTask:
    """
    A single review assignment for a resource in the IN_REVIEW state.

    notes must be non-empty before a publish or reject decision is recorded.
    decision is None while the task is pending.
    """
    id: uuid.UUID
    resource_id: uuid.UUID
    assigned_to: uuid.UUID
    decision: Optional[ReviewDecision]
    notes: str
    created_at: datetime
    completed_at: Optional[datetime]

    @property
    def is_pending(self) -> bool:
        return self.decision is None

    def complete(
        self,
        decision: ReviewDecision,
        notes: str,
        now: datetime,
        actor_id: uuid.UUID,
    ) -> "AuditEvent":
        """
        Record a review decision.  Returns an immutable AuditEvent that must
        be persisted alongside this task update.
        """
        if not notes.strip():
            from district_console.domain.exceptions import DomainValidationError
            raise DomainValidationError(
                field="notes",
                value=notes,
                constraint="Reviewer notes must not be empty.",
            )
        self.decision = decision
        self.notes = notes
        self.completed_at = now
        return AuditEvent(
            id=uuid.uuid4(),
            entity_type="Resource",
            entity_id=str(self.resource_id),
            action=f"REVIEW_{decision.value}",
            actor_id=actor_id,
            timestamp=now,
            metadata={"task_id": str(self.id), "notes_length": len(notes)},
        )


@dataclass(frozen=True)
class AuditEvent:
    """
    Immutable timestamped record of a significant action on a domain entity.

    AuditEvent records must never be updated or deleted (append-only).
    The frozen=True dataclass attribute enforces immutability at the Python
    layer; the infrastructure layer enforces it at the database layer by
    never issuing UPDATE or DELETE on the audit_events table.
    """
    id: uuid.UUID
    entity_type: str           # e.g. "Resource", "CountSession", "User"
    entity_id: str             # String representation of the entity's PK
    action: str                # e.g. "PUBLISHED", "COUNT_CLOSED", "LOGIN_FAILED"
    actor_id: uuid.UUID        # User who performed the action
    timestamp: datetime        # UTC timestamp; immutable after creation
    metadata: dict[str, Any] = field(default_factory=dict)
