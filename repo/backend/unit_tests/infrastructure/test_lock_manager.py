"""
Unit tests for LockManager: acquisition, release, expiry, and conflict handling.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from district_console.application.auth_service import AuthService
from district_console.domain.exceptions import RecordLockedError
from district_console.infrastructure.lock_manager import DEFAULT_LOCK_TTL_SECONDS, LockManager
from district_console.infrastructure.orm import UserORM
from district_console.infrastructure.repositories import LockRepository
from district_console.infrastructure.repositories import RoleRepository, UserRepository


async def _seed_user(db_session, user_id: uuid.UUID, username: str) -> None:
    auth = AuthService(UserRepository(), RoleRepository())
    now = datetime.utcnow().isoformat()
    db_session.add(
        UserORM(
            id=str(user_id),
            username=username,
            password_hash=auth.hash_password("SecurePassword1!"),
            is_active=True,
            failed_attempts=0,
            locked_until=None,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.flush()


class TestLockManager:
    async def test_acquire_free_lock_returns_record_lock(self, db_session) -> None:
        manager = LockManager(LockRepository())
        entity_id = uuid.uuid4()
        user_id = uuid.uuid4()
        await _seed_user(db_session, user_id, "lock_user_1")

        lock = await manager.acquire(
            db_session, "Resource", entity_id, user_id
        )

        assert lock.entity_type == "Resource"
        assert lock.entity_id == str(entity_id)
        assert lock.locked_by == user_id
        assert lock.nonce  # non-empty nonce

    async def test_acquire_held_lock_raises_record_locked_error(
        self, db_session
    ) -> None:
        manager = LockManager(LockRepository())
        entity_id = uuid.uuid4()
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        await _seed_user(db_session, user_a, "lock_user_a")
        await _seed_user(db_session, user_b, "lock_user_b")

        # user_a acquires the lock
        await manager.acquire(db_session, "Resource", entity_id, user_a)

        # user_b should be rejected
        with pytest.raises(RecordLockedError) as exc_info:
            await manager.acquire(db_session, "Resource", entity_id, user_b)
        assert exc_info.value.code == "RECORD_LOCKED"
        assert exc_info.value.lock_holder == str(user_a)

    async def test_release_own_lock_frees_entity(self, db_session) -> None:
        manager = LockManager(LockRepository())
        entity_id = uuid.uuid4()
        user_id = uuid.uuid4()
        await _seed_user(db_session, user_id, "lock_owner")

        await manager.acquire(db_session, "Resource", entity_id, user_id)
        await manager.release(db_session, "Resource", entity_id, user_id)

        # Now another user can acquire
        other_user = uuid.uuid4()
        await _seed_user(db_session, other_user, "lock_other")
        lock = await manager.acquire(db_session, "Resource", entity_id, other_user)
        assert lock.locked_by == other_user

    async def test_release_others_lock_raises(self, db_session) -> None:
        manager = LockManager(LockRepository())
        entity_id = uuid.uuid4()
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        await _seed_user(db_session, user_a, "lock_user_release_a")
        await _seed_user(db_session, user_b, "lock_user_release_b")

        await manager.acquire(db_session, "Resource", entity_id, user_a)

        with pytest.raises(RecordLockedError):
            await manager.release(db_session, "Resource", entity_id, user_b)

    async def test_expired_lock_can_be_acquired_by_new_holder(
        self, db_session
    ) -> None:
        """A lock whose expires_at is in the past can be replaced."""
        from district_console.infrastructure.orm import RecordLockORM
        import secrets as _secrets

        manager = LockManager(LockRepository())
        entity_id = uuid.uuid4()
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        await _seed_user(db_session, user_a, "lock_expired_a")
        await _seed_user(db_session, user_b, "lock_expired_b")

        # Manually insert an expired lock for user_a
        past = datetime.utcnow() - timedelta(seconds=10)
        expired_orm = RecordLockORM(
            id=str(uuid.uuid4()),
            entity_type="Resource",
            entity_id=str(entity_id),
            locked_by=str(user_a),
            locked_at=past.isoformat(),
            expires_at=past.isoformat(),
            nonce=_secrets.token_hex(16),
        )
        db_session.add(expired_orm)
        await db_session.flush()

        # user_b should be able to acquire since lock is expired
        lock = await manager.acquire(db_session, "Resource", entity_id, user_b)
        assert lock.locked_by == user_b

    async def test_refresh_extends_expiry(self, db_session) -> None:
        manager = LockManager(LockRepository())
        entity_id = uuid.uuid4()
        user_id = uuid.uuid4()
        await _seed_user(db_session, user_id, "lock_refresh_user")

        original_lock = await manager.acquire(
            db_session, "Resource", entity_id, user_id, ttl_seconds=60
        )
        refreshed_lock = await manager.refresh(
            db_session, "Resource", entity_id, user_id, ttl_seconds=600
        )
        assert refreshed_lock.expires_at > original_lock.expires_at

    async def test_check_returns_none_when_free(self, db_session) -> None:
        manager = LockManager(LockRepository())
        entity_id = uuid.uuid4()
        result = await manager.check(db_session, "Resource", entity_id)
        assert result is None

    async def test_check_returns_lock_when_held(self, db_session) -> None:
        manager = LockManager(LockRepository())
        entity_id = uuid.uuid4()
        user_id = uuid.uuid4()
        await _seed_user(db_session, user_id, "lock_check_user")
        await manager.acquire(db_session, "Resource", entity_id, user_id)
        result = await manager.check(db_session, "Resource", entity_id)
        assert result is not None
        assert result.locked_by == user_id
