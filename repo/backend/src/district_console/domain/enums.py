"""
Domain enumerations for District Console.

All enums use string values so they serialise cleanly to/from SQLite TEXT
columns and JSON API payloads without needing a translation layer.
"""
from __future__ import annotations

from enum import Enum


class ResourceType(str, Enum):
    BOOK = "BOOK"
    PICTURE_BOOK = "PICTURE_BOOK"
    ARTICLE = "ARTICLE"
    AUDIO = "AUDIO"


class ResourceStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    PUBLISHED = "PUBLISHED"
    UNPUBLISHED = "UNPUBLISHED"


class TimelinesType(str, Enum):
    """
    Timeliness classification for resource metadata.
    Validation rule: value must be one of these three members (case-sensitive).
    """
    EVERGREEN = "EVERGREEN"
    CURRENT = "CURRENT"
    ARCHIVED = "ARCHIVED"


class CountMode(str, Enum):
    OPEN = "OPEN"
    BLIND = "BLIND"
    CYCLE = "CYCLE"


class CountSessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    APPROVED = "APPROVED"


class LedgerEntryType(str, Enum):
    RECEIPT = "RECEIPT"
    ADJUSTMENT = "ADJUSTMENT"
    RELOCATION = "RELOCATION"
    CORRECTION = "CORRECTION"
    COUNT_CLOSE = "COUNT_CLOSE"


class DeviceSource(str, Enum):
    """Source of a stock relocation or count line entry."""
    MANUAL = "MANUAL"
    USB_SCANNER = "USB_SCANNER"


class RoleType(str, Enum):
    ADMINISTRATOR = "ADMINISTRATOR"
    LIBRARIAN = "LIBRARIAN"
    TEACHER = "TEACHER"
    COUNSELOR = "COUNSELOR"
    REVIEWER = "REVIEWER"


class ScopeType(str, Enum):
    """Granularity level of a user's data scope assignment."""
    SCHOOL = "SCHOOL"
    DEPARTMENT = "DEPARTMENT"
    CLASS = "CLASS"
    INDIVIDUAL = "INDIVIDUAL"


class CheckpointStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


class UpdateStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    ROLLED_BACK = "ROLLED_BACK"


class ReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_REVISION = "NEEDS_REVISION"


class StockStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    QUARANTINE = "QUARANTINE"
    DISPOSED = "DISPOSED"
    FROZEN = "FROZEN"


# ---------------------------------------------------------------------------
# Workflow transition graph for ResourceStatus
# Maps each valid (from_status, to_status) pair.  Any pair not in this set
# is an invalid transition and must raise InvalidStateTransitionError.
# ---------------------------------------------------------------------------

VALID_RESOURCE_TRANSITIONS: frozenset[tuple[ResourceStatus, ResourceStatus]] = frozenset({
    (ResourceStatus.DRAFT, ResourceStatus.IN_REVIEW),
    (ResourceStatus.IN_REVIEW, ResourceStatus.PUBLISHED),
    (ResourceStatus.IN_REVIEW, ResourceStatus.UNPUBLISHED),
    (ResourceStatus.PUBLISHED, ResourceStatus.UNPUBLISHED),
    (ResourceStatus.UNPUBLISHED, ResourceStatus.IN_REVIEW),
})


def validate_resource_transition(
    from_status: ResourceStatus,
    to_status: ResourceStatus,
) -> None:
    """
    Raise InvalidStateTransitionError if (from_status, to_status) is not
    a valid resource workflow transition.
    """
    # Import here to avoid circular dependency between enums and exceptions
    from district_console.domain.exceptions import InvalidStateTransitionError

    if (from_status, to_status) not in VALID_RESOURCE_TRANSITIONS:
        raise InvalidStateTransitionError(
            from_status=from_status.value,
            to_status=to_status.value,
            entity_type="Resource",
        )
