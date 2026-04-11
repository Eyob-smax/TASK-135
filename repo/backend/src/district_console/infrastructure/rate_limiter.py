"""
Fixed-window rate limiter for integration client API calls.

Algorithm:
  - Each integration client has one row in rate_limit_state.
  - A "window" is a 60-second interval starting at window_start.
  - On each request, if now - window_start >= 60s, the window resets.
  - If request_count > RATE_LIMIT_RPM (60), RateLimitExceededError is raised.

The limit is 60 requests per minute (RATE_LIMIT_RPM from domain policies).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from district_console.domain.exceptions import RateLimitExceededError
from district_console.domain.policies import RATE_LIMIT_RPM
from district_console.infrastructure.repositories import RateLimitRepository

WINDOW_SECONDS: int = 60


class RateLimiter:
    """
    Checks and records API usage against the per-client rate limit.

    Uses the RateLimitRepository to persist window state between requests.
    """

    def __init__(self, repo: RateLimitRepository) -> None:
        self._repo = repo

    async def check_and_record(
        self,
        session: AsyncSession,
        client_id: str,
        now: datetime,
    ) -> None:
        """
        Increment the request counter for the client. Raise RateLimitExceededError
        if the client has exceeded RATE_LIMIT_RPM requests in the current window.

        Resets the window automatically when the 60-second interval expires.

        Args:
            session:   Open AsyncSession (caller manages transaction).
            client_id: Integration client ID string.
            now:       Current UTC datetime (injected for testability).

        Raises:
            RateLimitExceededError: If the client has exceeded the rate limit.
        """
        existing = await self._repo.get_state(session, client_id)

        if existing is None:
            # First request from this client
            await self._repo.upsert_state(
                session,
                client_id=client_id,
                window_start=now,
                request_count=1,
            )
            return

        window_start = datetime.fromisoformat(existing.window_start)
        window_age = (now - window_start).total_seconds()

        if window_age >= WINDOW_SECONDS:
            # Window expired — reset counter
            await self._repo.upsert_state(
                session,
                client_id=client_id,
                window_start=now,
                request_count=1,
                existing_orm=existing,
            )
            return

        # Within the current window — check and increment
        new_count = existing.request_count + 1
        if new_count > RATE_LIMIT_RPM:
            raise RateLimitExceededError(client_id=client_id, limit=RATE_LIMIT_RPM)

        await self._repo.upsert_state(
            session,
            client_id=client_id,
            window_start=window_start,
            request_count=new_count,
            existing_orm=existing,
        )
