"""
Unit tests for AuthService: password hashing, verification, lockout, and sessions.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from district_console.application.auth_service import SESSION_TTL_HOURS, AuthService
from district_console.domain.exceptions import (
    InvalidCredentialsError,
    LockoutError,
    PasswordTooShortError,
)
from district_console.infrastructure.orm import UserORM
from district_console.infrastructure.repositories import RoleRepository, UserRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_auth_service() -> AuthService:
    return AuthService(UserRepository(), RoleRepository())


async def insert_user(db_session, auth_service: AuthService, password: str) -> UserORM:
    """Insert a test user with a hashed password."""
    password_hash = auth_service.hash_password(password)
    user_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    orm = UserORM(
        id=user_id,
        username=f"user_{user_id[:8]}",
        password_hash=password_hash,
        is_active=True,
        failed_attempts=0,
        locked_until=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(orm)
    await db_session.flush()
    return orm


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

class TestHashPassword:
    def test_hash_password_produces_argon2id_format(self) -> None:
        auth = make_auth_service()
        hashed = auth.hash_password("ValidPassword1!")
        assert hashed.startswith("$argon2id$"), (
            f"Expected Argon2id hash prefix, got: {hashed[:20]!r}"
        )

    def test_hash_password_too_short_raises(self) -> None:
        auth = make_auth_service()
        with pytest.raises(PasswordTooShortError) as exc_info:
            auth.hash_password("short")
        assert exc_info.value.min_length == 12

    def test_hash_password_exactly_min_length_succeeds(self) -> None:
        auth = make_auth_service()
        # 12 characters — meets minimum exactly
        result = auth.hash_password("Abcdefghij1!")
        assert result.startswith("$argon2id$")


class TestVerifyPassword:
    def test_verify_password_correct_returns_true(self) -> None:
        auth = make_auth_service()
        pw = "CorrectPassword1!"
        hashed = auth.hash_password(pw)
        assert auth.verify_password(pw, hashed) is True

    def test_verify_password_wrong_returns_false(self) -> None:
        auth = make_auth_service()
        hashed = auth.hash_password("OriginalPassword1!")
        assert auth.verify_password("WrongPassword1!", hashed) is False

    def test_verify_password_empty_returns_false(self) -> None:
        auth = make_auth_service()
        hashed = auth.hash_password("SomeValidPassword1!")
        assert auth.verify_password("", hashed) is False


# ---------------------------------------------------------------------------
# Authentication flow
# ---------------------------------------------------------------------------

class TestAuthenticate:
    async def test_authenticate_unknown_user_raises_invalid_credentials(
        self, db_session
    ) -> None:
        auth = make_auth_service()
        with pytest.raises(InvalidCredentialsError):
            await auth.authenticate(db_session, "nobody", "password", datetime.utcnow())

    async def test_authenticate_wrong_password_increments_failed_attempts(
        self, db_session
    ) -> None:
        auth = make_auth_service()
        orm = await insert_user(db_session, auth, "RightPassword1!")

        with pytest.raises(InvalidCredentialsError):
            await auth.authenticate(
                db_session, orm.username, "WrongPassword1!", datetime.utcnow()
            )

        await db_session.refresh(orm)
        assert orm.failed_attempts == 1

    async def test_authenticate_locked_account_raises_lockout_error(
        self, db_session
    ) -> None:
        auth = make_auth_service()
        orm = await insert_user(db_session, auth, "ValidPassword1!")
        # Set locked_until to the future
        future = datetime.utcnow() + timedelta(minutes=10)
        orm.locked_until = future.isoformat()
        orm.failed_attempts = 5
        await db_session.flush()

        with pytest.raises(LockoutError) as exc_info:
            await auth.authenticate(
                db_session, orm.username, "ValidPassword1!", datetime.utcnow()
            )
        assert exc_info.value.code == "ACCOUNT_LOCKED"

    async def test_authenticate_5th_failure_locks_account(
        self, db_session
    ) -> None:
        auth = make_auth_service()
        orm = await insert_user(db_session, auth, "GoodPassword1!")
        # Prime 4 failed attempts
        orm.failed_attempts = 4
        await db_session.flush()

        # 5th failure should set locked_until
        with pytest.raises((InvalidCredentialsError, LockoutError)):
            await auth.authenticate(
                db_session, orm.username, "WrongPassword1!", datetime.utcnow()
            )

        await db_session.refresh(orm)
        assert orm.failed_attempts >= 5
        assert orm.locked_until is not None

    async def test_authenticate_success_resets_failed_attempts(
        self, db_session
    ) -> None:
        auth = make_auth_service()
        pw = "GoodPassword1!"
        orm = await insert_user(db_session, auth, pw)
        orm.failed_attempts = 3
        await db_session.flush()

        user, roles = await auth.authenticate(
            db_session, orm.username, pw, datetime.utcnow()
        )
        assert user.failed_attempts == 0
        assert user.locked_until is None


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

class TestSessionManagement:
    def test_session_token_roundtrip_and_expiry(self) -> None:
        auth = make_auth_service()
        user_id = uuid.uuid4()
        token = auth.create_session(user_id, [])

        # Valid token returns (user_id, roles)
        result = auth.validate_session(token, datetime.utcnow())
        assert result is not None
        returned_uid, returned_roles = result
        assert returned_uid == user_id
        assert returned_roles == []

    def test_expired_session_returns_none(self) -> None:
        auth = make_auth_service()
        user_id = uuid.uuid4()
        token = auth.create_session(user_id, [])

        # Validate with a time far in the future (past expiry)
        future = datetime.utcnow() + timedelta(hours=SESSION_TTL_HOURS + 1)
        result = auth.validate_session(token, future)
        assert result is None

    def test_invalidated_session_returns_none(self) -> None:
        auth = make_auth_service()
        user_id = uuid.uuid4()
        token = auth.create_session(user_id, [])
        auth.invalidate_session(token)
        result = auth.validate_session(token, datetime.utcnow())
        assert result is None

    def test_unknown_token_returns_none(self) -> None:
        auth = make_auth_service()
        result = auth.validate_session("not-a-real-token", datetime.utcnow())
        assert result is None
