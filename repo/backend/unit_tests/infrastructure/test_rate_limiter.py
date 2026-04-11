"""
Unit tests for RateLimiter: fixed-window 60 rpm enforcement.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from district_console.domain.exceptions import RateLimitExceededError
from district_console.infrastructure.orm import IntegrationClientORM
from district_console.infrastructure.rate_limiter import WINDOW_SECONDS, RateLimiter
from district_console.infrastructure.repositories import RateLimitRepository


async def _seed_client(db_session, client_id: str) -> None:
    """Insert a minimal IntegrationClientORM so FK constraints pass."""
    from district_console.infrastructure.orm import IntegrationClientORM
    orm = IntegrationClientORM(
        id=client_id,
        name=f"client_{client_id[:8]}",
        description="",
        is_active=True,
        created_at=datetime.utcnow().isoformat(),
    )
    db_session.add(orm)
    await db_session.flush()


class TestRateLimiter:
    async def test_requests_within_limit_allowed(self, db_session) -> None:
        """60 requests in one window should all succeed."""
        limiter = RateLimiter(RateLimitRepository())
        client_id = str(uuid.uuid4())
        await _seed_client(db_session, client_id)
        now = datetime.utcnow()

        for _ in range(60):
            await limiter.check_and_record(db_session, client_id, now)

        # If we get here without exception, all 60 requests were allowed

    async def test_61st_request_raises_rate_limit_exceeded(self, db_session) -> None:
        """The 61st request in a window should raise RateLimitExceededError."""
        limiter = RateLimiter(RateLimitRepository())
        client_id = str(uuid.uuid4())
        await _seed_client(db_session, client_id)
        now = datetime.utcnow()

        for _ in range(60):
            await limiter.check_and_record(db_session, client_id, now)

        with pytest.raises(RateLimitExceededError) as exc_info:
            await limiter.check_and_record(db_session, client_id, now)
        assert exc_info.value.code == "RATE_LIMIT_EXCEEDED"

    async def test_new_window_after_60s_resets_count(self, db_session) -> None:
        """After WINDOW_SECONDS, the counter resets and requests succeed again."""
        limiter = RateLimiter(RateLimitRepository())
        client_id = str(uuid.uuid4())
        await _seed_client(db_session, client_id)
        now = datetime.utcnow()

        # Fill the first window
        for _ in range(60):
            await limiter.check_and_record(db_session, client_id, now)

        # Move time forward past the window
        next_window = now + timedelta(seconds=WINDOW_SECONDS + 1)
        # First request in new window should succeed
        await limiter.check_and_record(db_session, client_id, next_window)

    async def test_different_clients_have_independent_windows(
        self, db_session
    ) -> None:
        """Rate limit state is per-client."""
        limiter = RateLimiter(RateLimitRepository())
        client_a = str(uuid.uuid4())
        client_b = str(uuid.uuid4())
        await _seed_client(db_session, client_a)
        await _seed_client(db_session, client_b)
        now = datetime.utcnow()

        # Fill client_a's window
        for _ in range(60):
            await limiter.check_and_record(db_session, client_a, now)

        # client_b should still be able to make requests
        await limiter.check_and_record(db_session, client_b, now)
