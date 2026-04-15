"""
Unit tests for infrastructure.database — create_engine / create_session_factory.

Verifies that the SQLite engine applies the required pragmas (WAL,
foreign_keys, synchronous, busy_timeout) on every new connection and
that the session factory produces AsyncSession instances bound to the
engine with expire_on_commit=False.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from district_console.infrastructure.database import create_engine, create_session_factory


def test_create_engine_returns_async_engine(tmp_path: Path) -> None:
    db_path = tmp_path / "pragmas.db"
    engine = create_engine(str(db_path))
    assert isinstance(engine, AsyncEngine)


async def test_create_engine_applies_sqlite_pragmas(tmp_path: Path) -> None:
    db_path = tmp_path / "pragmas.db"
    engine = create_engine(str(db_path))
    try:
        async with engine.connect() as conn:
            journal = (await conn.execute(text("PRAGMA journal_mode"))).scalar_one()
            fks = (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one()
            synchronous = (await conn.execute(text("PRAGMA synchronous"))).scalar_one()
            busy = (await conn.execute(text("PRAGMA busy_timeout"))).scalar_one()
    finally:
        await engine.dispose()

    # journal_mode returns a lowercase string like 'wal' or 'memory' depending on
    # whether the path is :memory: or a real file. For a real file path,
    # SQLite must honour WAL.
    assert str(journal).lower() == "wal"
    assert int(fks) == 1
    # synchronous=NORMAL is mode 1
    assert int(synchronous) == 1
    assert int(busy) == 5000


def test_create_session_factory_returns_async_sessionmaker(tmp_path: Path) -> None:
    db_path = tmp_path / "factory.db"
    engine = create_engine(str(db_path))
    factory = create_session_factory(engine)
    assert isinstance(factory, async_sessionmaker)


async def test_session_factory_yields_async_session_with_expire_off(tmp_path: Path) -> None:
    db_path = tmp_path / "factory.db"
    engine = create_engine(str(db_path))
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            assert isinstance(session, AsyncSession)
            # expire_on_commit must be False so objects remain usable post-commit
            assert session.sync_session.expire_on_commit is False
    finally:
        await engine.dispose()
