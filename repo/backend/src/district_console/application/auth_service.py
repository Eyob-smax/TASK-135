"""
Local authentication service.

Implements credential verification, password hashing (Argon2id), lockout
enforcement, and session token management for the desktop application.

Session tokens:
  Stored in-memory in a dict[token → SessionEntry]. Sessions are invalidated
  when the application restarts, which is acceptable for a local desktop app
  where the operator is physically present. Session TTL is 8 hours.

Password hashing:
  Uses argon2-cffi's PasswordHasher with default parameters (Argon2id variant).
  The stored hash includes the algorithm identifier, parameters, salt, and
  digest — no additional fields are needed.

Lockout policy (from domain/policies.py):
  MAX_FAILED_ATTEMPTS = 5
  LOCKOUT_DURATION_MINUTES = 15
  MIN_PASSWORD_LENGTH = 12
"""
from __future__ import annotations

import secrets
import uuid
from collections import namedtuple
from datetime import datetime, timedelta
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.domain.entities.role import Role
from district_console.domain.entities.user import User
from district_console.domain.exceptions import (
    InvalidCredentialsError,
    LockoutError,
    PasswordTooShortError,
)
from district_console.domain.policies import MIN_PASSWORD_LENGTH
from district_console.infrastructure.repositories import RoleRepository, UserRepository

SESSION_TTL_HOURS: int = 8

_SessionEntry = namedtuple("_SessionEntry", ["user_id", "roles", "expires_at"])


class AuthService:
    """
    Handles local authentication: hashing, verification, lockout, and sessions.

    One instance should exist per application lifetime (holds the in-memory
    session store).
    """

    def __init__(
        self,
        user_repo: UserRepository,
        role_repo: RoleRepository,
    ) -> None:
        self._ph = PasswordHasher()
        self._user_repo = user_repo
        self._role_repo = role_repo
        self._sessions: dict[str, _SessionEntry] = {}

    # ------------------------------------------------------------------
    # Password operations
    # ------------------------------------------------------------------

    def hash_password(self, password: str) -> str:
        """
        Hash a plaintext password with Argon2id.

        Raises:
            PasswordTooShortError: If password is shorter than MIN_PASSWORD_LENGTH.

        Returns:
            Full encoded Argon2id string (includes algorithm, params, salt, hash).
        """
        if len(password) < MIN_PASSWORD_LENGTH:
            raise PasswordTooShortError(MIN_PASSWORD_LENGTH)
        return self._ph.hash(password)

    def verify_password(self, password: str, stored_hash: str) -> bool:
        """
        Verify a plaintext password against a stored Argon2id hash.

        Returns False on mismatch. Never raises on expected mismatches.
        Argon2 rehash_if_needed() is not called here — callers that need
        hash upgrading should check _ph.check_needs_rehash() separately.
        """
        try:
            return self._ph.verify(stored_hash, password)
        except VerifyMismatchError:
            return False
        except Exception:  # pragma: no cover — unexpected argon2 errors
            return False

    # ------------------------------------------------------------------
    # Authentication flow
    # ------------------------------------------------------------------

    async def authenticate(
        self,
        session: AsyncSession,
        username: str,
        password: str,
        now: datetime,
    ) -> tuple[User, list[Role]]:
        """
        Full authentication flow:
          1. Load user by username → raise InvalidCredentialsError if not found or inactive
          2. Check lockout → raise LockoutError if locked
          3. Verify password → on fail: record attempt, save, raise InvalidCredentialsError
          4. On success: reset attempts, save, load roles, return (user, roles)

        The caller must commit the session after this call.
        """
        user = await self._user_repo.get_by_username(session, username)
        if user is None or not user.is_active:
            raise InvalidCredentialsError()

        if user.is_locked_out(now):
            raise LockoutError(locked_until=user.locked_until)  # type: ignore[arg-type]

        if not self.verify_password(password, user.password_hash):
            user.record_failed_attempt(now)
            await self._user_repo.save(session, user)
            # Check again — the 5th failure sets locked_until
            if user.is_locked_out(now):
                raise LockoutError(locked_until=user.locked_until)  # type: ignore[arg-type]
            raise InvalidCredentialsError()

        user.reset_failed_attempts(now)
        await self._user_repo.save(session, user)

        roles = await self._role_repo.get_roles_for_user(session, user.id)
        return user, roles

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def create_session(self, user_id: uuid.UUID, roles: list[Role]) -> str:
        """
        Generate a session token and store it in memory.

        Returns:
            URL-safe base64-encoded 32-byte token string.
        """
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=SESSION_TTL_HOURS)
        self._sessions[token] = _SessionEntry(
            user_id=user_id,
            roles=roles,
            expires_at=expires_at,
        )
        return token

    def validate_session(
        self,
        token: str,
        now: datetime,
    ) -> Optional[tuple[uuid.UUID, list[Role]]]:
        """
        Validate a session token.

        Returns:
            (user_id, roles) if the token is valid and not expired.
            None if the token is missing or expired.
        """
        entry = self._sessions.get(token)
        if entry is None:
            return None
        if now >= entry.expires_at:
            del self._sessions[token]
            return None
        return entry.user_id, entry.roles

    def invalidate_session(self, token: str) -> None:
        """Remove a session token (logout). Idempotent."""
        self._sessions.pop(token, None)
