"""
User, UserRole, and ScopeAssignment domain entities.

These are pure Python dataclasses with no framework dependencies.
The infrastructure layer maps these to SQLAlchemy ORM models.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from district_console.domain.enums import ScopeType


@dataclass
class User:
    """
    Authenticated user account.

    password_hash stores the full Argon2id encoded string (includes algorithm,
    parameters, salt, and hash) as produced by argon2-cffi. It is never
    stored in plaintext or a reversible format.
    """
    id: uuid.UUID
    username: str
    password_hash: str
    is_active: bool
    failed_attempts: int
    locked_until: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    def is_locked_out(self, now: datetime) -> bool:
        from district_console.domain.policies import is_locked_out
        return is_locked_out(self.failed_attempts, self.locked_until, now)

    def record_failed_attempt(self, now: datetime) -> None:
        """Increment failed_attempts and set locked_until if threshold reached."""
        from district_console.domain.policies import MAX_FAILED_ATTEMPTS, LOCKOUT_DURATION_MINUTES
        from datetime import timedelta

        self.failed_attempts += 1
        self.updated_at = now
        if self.failed_attempts >= MAX_FAILED_ATTEMPTS:
            self.locked_until = now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)

    def reset_failed_attempts(self, now: datetime) -> None:
        """Clear lockout state after a successful login."""
        self.failed_attempts = 0
        self.locked_until = None
        self.updated_at = now


@dataclass(frozen=True)
class UserRole:
    """Association between a user and a role."""
    user_id: uuid.UUID
    role_id: uuid.UUID
    assigned_by: uuid.UUID
    assigned_at: datetime


@dataclass(frozen=True)
class ScopeAssignment:
    """
    Grants a user access to records within a specific scope boundary.

    scope_ref_id references the primary key of the scope entity
    (schools.id, departments.id, classes.id, or individuals.id depending
    on scope_type).
    """
    id: uuid.UUID
    user_id: uuid.UUID
    scope_type: ScopeType
    scope_ref_id: uuid.UUID
    granted_by: uuid.UUID
    granted_at: datetime
