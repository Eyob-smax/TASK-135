"""
Async database engine and session factory for District Console.

Creates an aiosqlite-backed async SQLAlchemy engine with the required SQLite
pragmas applied on every new connection:
  - WAL journal mode for concurrent read/write
  - Foreign key enforcement
  - NORMAL synchronous mode (crash-safe + performant for local desktop)
  - 5-second busy timeout to handle brief lock contention
"""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(db_path: str) -> AsyncEngine:
    """
    Create an async SQLAlchemy engine for the given SQLite database path.

    Uses sqlite+aiosqlite driver. SQLite pragmas are applied via a sync
    event listener on the underlying synchronous connection, which is the
    correct pattern for async SQLAlchemy + aiosqlite.
    """
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _apply_pragmas(dbapi_conn, _connection_record) -> None:  # type: ignore[type-arg]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """
    Create an async session factory bound to the given engine.

    expire_on_commit=False prevents DetachedInstanceError when accessing
    ORM attributes after a commit — important for returning domain objects
    from repository methods.
    """
    return async_sessionmaker(engine, expire_on_commit=False)
