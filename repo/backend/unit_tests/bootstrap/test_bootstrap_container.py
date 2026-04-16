"""
Test the full `bootstrap()` composition root.

These exercise the large untested wiring block in bootstrap/__init__.py
(lines ~301-425) where all repositories, services, and the FastAPI app
are composed. Alembic migrations are stubbed out — the test uses an
in-memory SQLite database and a real ORM schema created via
`Base.metadata.create_all`.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

import district_console.bootstrap as bootstrap_mod
from district_console.bootstrap.config import AppConfig
from district_console.infrastructure.orm import Base


async def _create_schema(db_path: str) -> None:
    """Build the ORM schema inline so bootstrap can open connections to it."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


async def test_bootstrap_composes_container(monkeypatch, tmp_path):
    """bootstrap() wires every service, attaches FastAPI, and starts the scheduler."""
    # Patch _run_migrations — we'll create the schema ourselves via Base.metadata
    monkeypatch.setattr(bootstrap_mod, "_run_migrations", lambda db_path: None)

    # Prevent the real APScheduler from firing real triggers during the test
    class _FakeScheduler:
        def __init__(self):
            self.jobs = {}
            self.started = False

        def add_job(self, fn, trigger, id, replace_existing):
            self.jobs[id] = fn

        def start(self):
            self.started = True

    import apscheduler.schedulers.background as bg
    monkeypatch.setattr(bg, "BackgroundScheduler", _FakeScheduler)

    # Cross-platform temp DB path
    db_file = tmp_path / "bootstrap_test.db"
    db_path = str(db_file)

    # Create the schema up front so bootstrap's opens succeed
    await _create_schema(db_path)

    # Synthetic config: valid 32-byte hex master key, in-memory log level
    config = AppConfig(
        db_path=db_path,
        key_encryption_key="0" * 64,
        log_level="WARNING",
    )

    container = await bootstrap_mod.bootstrap(config=config)

    # Every service field is populated
    assert container.auth_service is not None
    assert container.rbac_service is not None
    assert container.resource_service is not None
    assert container.inventory_service is not None
    assert container.count_session_service is not None
    assert container.relocation_service is not None
    assert container.config_service is not None
    assert container.taxonomy_service is not None
    assert container.integration_service is not None
    assert container.update_service is not None
    assert container.audit_service is not None
    assert container.outbox_writer is not None
    assert container.instrumentation is not None
    # FastAPI app is attached and has state.container pointing back
    assert container.api_app is not None
    assert container.api_app.state.container is container
    # Scheduler was started
    assert container.scheduler is not None
    assert container.scheduler.started is True
    # Registered jobs: expire, retry, lifecycle
    assert set(container.scheduler.jobs.keys()) == {
        "expire_count_sessions",
        "retry_pending_events",
        "enforce_hmac_key_lifecycle",
    }

    # Graceful engine cleanup for the test
    await container.engine.dispose()


async def test_bootstrap_rejects_invalid_master_key(monkeypatch, tmp_path):
    """An invalid master key must abort bootstrap before any DB work happens."""
    monkeypatch.setattr(bootstrap_mod, "_run_migrations", lambda db_path: None)
    db_path = str(tmp_path / "nope.db")

    bad_config = AppConfig(db_path=db_path, key_encryption_key="not-hex!")
    with pytest.raises(ValueError, match="hex"):
        await bootstrap_mod.bootstrap(config=bad_config)
