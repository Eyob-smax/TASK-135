"""
DB-backed record-level lock coordination.

Provides exclusive advisory locks on any domain entity. Used to prevent
concurrent edits to items currently being modified by another operator.

Lock lifecycle:
  acquire()  →  refresh() (optional, extends TTL)  →  release()

Conflict handling:
  If an active non-expired lock exists for the requested entity, acquire()
  raises RecordLockedError with the holder's user_id and expiry time.
  Expired locks are cleared automatically before attempting acquisition.

TTL:
  Default is 300 seconds (5 minutes). Each refresh() call resets the clock.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from district_console.domain.entities.inventory import RecordLock
from district_console.domain.exceptions import RecordLockedError
from district_console.infrastructure.orm import RecordLockORM
from district_console.infrastructure.repositories import LockRepository, _lock_to_domain

DEFAULT_LOCK_TTL_SECONDS: int = 300  # 5 minutes


class LockManager:
    """
    Manages record-level exclusive locks backed by the record_locks table.

    All methods operate within the caller's AsyncSession. The caller is
    responsible for committing the transaction.
    """

    def __init__(self, repo: LockRepository) -> None:
        self._repo = repo

    async def acquire(
        self,
        session: AsyncSession,
        entity_type: str,
        entity_id: uuid.UUID,
        user_id: uuid.UUID,
        ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
    ) -> RecordLock:
        """
        Acquire an exclusive lock on (entity_type, entity_id).

        Steps:
          1. Delete any expired lock for the entity.
          2. Check for an active lock — raise RecordLockedError if found.
          3. Insert a new lock with a fresh nonce and expiry.

        Returns the new RecordLock domain object.
        """
        entity_id_str = str(entity_id)

        # Step 1: clear expired lock if present
        existing = await self._repo.get_active_lock(
            session, entity_type, entity_id_str
        )
        if existing is not None:
            expires_at = datetime.fromisoformat(existing.expires_at)
            if datetime.utcnow() >= expires_at:
                await self._repo.delete_by_id(session, existing.id)
                existing = None

        # Step 2: reject if still locked
        if existing is not None:
            raise RecordLockedError(
                entity_type=entity_type,
                entity_id=entity_id_str,
                lock_holder=existing.locked_by,
                expires_at=datetime.fromisoformat(existing.expires_at),
            )

        # Step 3: insert new lock
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)
        lock_orm = RecordLockORM(
            id=str(uuid.uuid4()),
            entity_type=entity_type,
            entity_id=entity_id_str,
            locked_by=str(user_id),
            locked_at=now.isoformat(),
            expires_at=expires_at.isoformat(),
            nonce=secrets.token_hex(16),
        )
        await self._repo.insert(session, lock_orm)
        return _lock_to_domain(lock_orm)

    async def release(
        self,
        session: AsyncSession,
        entity_type: str,
        entity_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """
        Release the lock held by user_id on (entity_type, entity_id).

        Raises RecordLockedError if the lock is held by a different user.
        Silently succeeds if no lock exists (idempotent release).
        """
        entity_id_str = str(entity_id)
        existing = await self._repo.get_active_lock(
            session, entity_type, entity_id_str
        )
        if existing is None:
            return  # Already released or never acquired

        if existing.locked_by != str(user_id):
            raise RecordLockedError(
                entity_type=entity_type,
                entity_id=entity_id_str,
                lock_holder=existing.locked_by,
                expires_at=datetime.fromisoformat(existing.expires_at),
            )

        await self._repo.delete_by_id(session, existing.id)

    async def refresh(
        self,
        session: AsyncSession,
        entity_type: str,
        entity_id: uuid.UUID,
        user_id: uuid.UUID,
        ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
    ) -> RecordLock:
        """
        Extend the TTL of an existing lock held by user_id.

        Raises RecordLockedError if the lock is held by a different user or
        has expired.
        """
        entity_id_str = str(entity_id)
        existing = await self._repo.get_active_lock(
            session, entity_type, entity_id_str
        )
        if existing is None or datetime.utcnow() >= datetime.fromisoformat(existing.expires_at):
            # Lock expired — must re-acquire
            raise RecordLockedError(
                entity_type=entity_type,
                entity_id=entity_id_str,
                lock_holder="",
                expires_at=datetime.utcnow(),
            )
        if existing.locked_by != str(user_id):
            raise RecordLockedError(
                entity_type=entity_type,
                entity_id=entity_id_str,
                lock_holder=existing.locked_by,
                expires_at=datetime.fromisoformat(existing.expires_at),
            )

        new_expires = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        existing.expires_at = new_expires.isoformat()
        await session.flush()
        return _lock_to_domain(existing)

    async def check(
        self,
        session: AsyncSession,
        entity_type: str,
        entity_id: uuid.UUID,
    ) -> Optional[RecordLock]:
        """
        Return the active non-expired lock for the entity, or None if free.
        """
        entity_id_str = str(entity_id)
        existing = await self._repo.get_active_lock(
            session, entity_type, entity_id_str
        )
        if existing is None:
            return None
        if datetime.utcnow() >= datetime.fromisoformat(existing.expires_at):
            return None
        return _lock_to_domain(existing)
