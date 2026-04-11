"""
Domain exception hierarchy for District Console.

All exceptions raised by domain and application layers inherit from
DistrictConsoleError so callers can catch the base type when needed.
Infrastructure and API layers translate these to appropriate HTTP responses
or user-facing error messages without leaking internal details.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


class DistrictConsoleError(Exception):
    """Base class for all District Console domain exceptions."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__


# ---------------------------------------------------------------------------
# Authentication and authorisation
# ---------------------------------------------------------------------------

class AuthenticationError(DistrictConsoleError):
    """Raised when authentication fails (wrong credentials, expired session)."""


class InvalidCredentialsError(AuthenticationError):
    """Username not found or password does not match."""

    def __init__(self) -> None:
        super().__init__(
            "Invalid username or password.",
            code="INVALID_CREDENTIALS",
        )


class LockoutError(AuthenticationError):
    """Account is locked out after too many failed attempts."""

    def __init__(self, locked_until: datetime) -> None:
        super().__init__(
            f"Account locked until {locked_until.isoformat()}. "
            "Too many failed login attempts.",
            code="ACCOUNT_LOCKED",
        )
        self.locked_until = locked_until


class PasswordTooShortError(AuthenticationError):
    """Password does not meet the minimum length requirement."""

    def __init__(self, min_length: int) -> None:
        super().__init__(
            f"Password must be at least {min_length} characters.",
            code="PASSWORD_TOO_SHORT",
        )
        self.min_length = min_length


class SessionExpiredError(AuthenticationError):
    """Desktop or API session token has expired."""

    def __init__(self) -> None:
        super().__init__("Session has expired. Please log in again.", code="SESSION_EXPIRED")


class AuthorizationError(DistrictConsoleError):
    """Raised when an authenticated user lacks permission for an operation."""


class InsufficientPermissionError(AuthorizationError):
    """User's role does not include the required permission."""

    def __init__(self, required_permission: str) -> None:
        super().__init__(
            f"Your role does not grant the '{required_permission}' permission.",
            code="INSUFFICIENT_PERMISSION",
        )
        self.required_permission = required_permission


class ScopeViolationError(AuthorizationError):
    """Requested record is outside the user's assigned data scope."""

    def __init__(self, entity_type: str, entity_id: str) -> None:
        super().__init__(
            f"{entity_type} '{entity_id}' is outside your assigned data scope.",
            code="SCOPE_VIOLATION",
        )
        self.entity_type = entity_type
        self.entity_id = entity_id


# ---------------------------------------------------------------------------
# Record locking
# ---------------------------------------------------------------------------

class RecordLockedError(DistrictConsoleError):
    """Another session holds an exclusive lock on the requested record."""

    def __init__(
        self,
        entity_type: str,
        entity_id: str,
        lock_holder: str,
        expires_at: datetime,
    ) -> None:
        super().__init__(
            f"{entity_type} '{entity_id}' is locked by '{lock_holder}' "
            f"until {expires_at.isoformat()}.",
            code="RECORD_LOCKED",
        )
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.lock_holder = lock_holder
        self.expires_at = expires_at


# ---------------------------------------------------------------------------
# Resource library
# ---------------------------------------------------------------------------

class ResourceNotFoundError(DistrictConsoleError):
    def __init__(self, resource_id: str) -> None:
        super().__init__(f"Resource '{resource_id}' not found.", code="NOT_FOUND")
        self.resource_id = resource_id


class DuplicateResourceError(DistrictConsoleError):
    """File fingerprint + ISBN/metadata combination already exists."""

    def __init__(self, existing_id: str, dedup_key: str) -> None:
        super().__init__(
            f"A resource with dedup key '{dedup_key}' already exists "
            f"(id: {existing_id}).",
            code="DUPLICATE_RESOURCE",
        )
        self.existing_id = existing_id
        self.dedup_key = dedup_key


class RevisionLimitError(DistrictConsoleError):
    """Resource already has the maximum number of retained revisions."""

    def __init__(self, resource_id: str, limit: int) -> None:
        super().__init__(
            f"Resource '{resource_id}' already has {limit} revisions "
            f"(maximum). Delete the oldest revision before adding a new one.",
            code="REVISION_LIMIT_REACHED",
        )
        self.resource_id = resource_id
        self.limit = limit


class InvalidStateTransitionError(DistrictConsoleError):
    """Workflow state transition is not permitted."""

    def __init__(self, from_status: str, to_status: str, entity_type: str = "Entity") -> None:
        super().__init__(
            f"{entity_type} cannot transition from '{from_status}' to '{to_status}'.",
            code="INVALID_STATE_TRANSITION",
        )
        self.from_status = from_status
        self.to_status = to_status
        self.entity_type = entity_type


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class DomainValidationError(DistrictConsoleError):
    """A domain-level field constraint was violated."""

    def __init__(self, field: str, value: Any, constraint: str) -> None:
        super().__init__(
            f"Validation failed for field '{field}': {constraint} (got {value!r}).",
            code="VALIDATION_ERROR",
        )
        self.field = field
        self.value = value
        self.constraint = constraint


# ---------------------------------------------------------------------------
# Inventory and ledger
# ---------------------------------------------------------------------------

class AppendOnlyViolationError(DistrictConsoleError):
    """Attempted to delete or update an immutable append-only record."""

    def __init__(self, table: str, record_id: str) -> None:
        super().__init__(
            f"Records in '{table}' are append-only and cannot be modified "
            f"(id: {record_id}). Use a correction entry instead.",
            code="APPEND_ONLY_VIOLATION",
        )
        self.table = table
        self.record_id = record_id


class InsufficientStockError(DistrictConsoleError):
    """Stock quantity is insufficient to fulfil the requested operation."""

    def __init__(self, item_id: str, location_id: str, available: int, requested: int) -> None:
        super().__init__(
            f"Insufficient stock for item '{item_id}' at location '{location_id}': "
            f"available={available}, requested={requested}.",
            code="INSUFFICIENT_STOCK",
        )
        self.item_id = item_id
        self.location_id = location_id
        self.available = available
        self.requested = requested


class StockFrozenError(DistrictConsoleError):
    """Cannot modify a frozen stock balance record."""

    def __init__(self, stock_balance_id: str) -> None:
        super().__init__(
            f"Stock balance '{stock_balance_id}' is frozen and cannot be adjusted. "
            "Unfreeze the record before making changes.",
            code="STOCK_FROZEN",
        )
        self.stock_balance_id = stock_balance_id


# ---------------------------------------------------------------------------
# Checkpointing
# ---------------------------------------------------------------------------

class CheckpointError(DistrictConsoleError):
    """Base class for checkpoint and recovery errors."""


class CheckpointResumeError(CheckpointError):
    """A checkpoint job could not be resumed from its saved state."""

    def __init__(self, checkpoint_id: str, reason: str) -> None:
        super().__init__(
            f"Cannot resume checkpoint '{checkpoint_id}': {reason}",
            code="CHECKPOINT_RESUME_FAILED",
        )
        self.checkpoint_id = checkpoint_id


# ---------------------------------------------------------------------------
# Integration and signing
# ---------------------------------------------------------------------------

class IntegrationSigningError(DistrictConsoleError):
    """HMAC signature verification failed for an integration client request."""

    def __init__(self) -> None:
        super().__init__(
            "Request signature verification failed. "
            "Ensure the correct active key is used and the timestamp is current.",
            code="SIGNATURE_INVALID",
        )


class RateLimitExceededError(DistrictConsoleError):
    """Integration client has exceeded the rate limit."""

    def __init__(self, client_id: str, limit: int) -> None:
        super().__init__(
            f"Client '{client_id}' exceeded the rate limit of {limit} requests/minute.",
            code="RATE_LIMIT_EXCEEDED",
        )
        self.client_id = client_id
        self.limit = limit
