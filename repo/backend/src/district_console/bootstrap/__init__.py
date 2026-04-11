"""
Bootstrap layer — startup composition, config loading, and dependency wiring.

Responsible for:
- Loading AppConfig from environment variables with safe defaults
- Initialising the SQLite database and running pending Alembic migrations
- Composing application services with their infrastructure dependencies
- Creating the FastAPI app (starting the HTTP server is the caller's responsibility)
- Registering APScheduler jobs and recovering active checkpoints (Prompt 5+)
- Launching the PyQt6 main window and system tray (Prompt 5+)
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from district_console.api.app import create_app
from district_console.application.audit_service import AuditService
from district_console.application.auth_service import AuthService
from district_console.application.config_service import ConfigService
from district_console.application.count_session_service import CountSessionService
from district_console.application.integration_service import IntegrationService
from district_console.application.inventory_service import InventoryService
from district_console.application.rbac_service import RbacService
from district_console.application.relocation_service import RelocationService
from district_console.application.resource_service import ResourceService
from district_console.application.taxonomy_service import TaxonomyService
from district_console.application.update_service import UpdateService
from district_console.bootstrap.config import AppConfig
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.barcode_input import BarcodeInputHandler  # noqa: F401 (re-exported)
from district_console.infrastructure.checkpoint_store import CheckpointStore
from district_console.infrastructure.database import create_engine, create_session_factory
from district_console.infrastructure.hmac_signer import HmacSigner
from district_console.infrastructure.instrumentation import InstrumentationHooks
from district_console.infrastructure.lock_manager import LockManager
from district_console.infrastructure.logging_config import configure_logging
from district_console.infrastructure.orm import Base
from district_console.infrastructure.outbox_writer import OutboxWriter
from district_console.infrastructure.rate_limiter import RateLimiter
from district_console.infrastructure.repositories import (
    AuditQueryRepository,
    AuditRepository,
    CheckpointRepository,
    ConfigRepository,
    CountSessionRepository,
    DistrictDescriptorRepository,
    IntegrationRepository,
    InventoryRepository,
    LedgerRepository,
    LockRepository,
    NotificationTemplateRepository,
    RateLimitRepository,
    RelocationRepository,
    ResourceMetadataRepository,
    ResourceRepository,
    ResourceRevisionRepository,
    ReviewTaskRepository,
    RoleRepository,
    TaxonomyRepository,
    UpdatePackageRepository,
    UserRepository,
    WorkflowNodeRepository,
)


@dataclass
class AppContainer:
    """
    Holds all wired application services and infrastructure objects.

    Created once per application lifetime by bootstrap().
    Tests create their own containers with lightweight in-memory databases.
    """
    config: AppConfig
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    auth_service: AuthService
    rbac_service: RbacService
    lock_manager: LockManager
    checkpoint_store: CheckpointStore
    audit_writer: AuditWriter
    hmac_signer: HmacSigner
    rate_limiter: RateLimiter
    api_app: FastAPI
    resource_service: ResourceService = None  # type: ignore[assignment]
    inventory_service: InventoryService = None  # type: ignore[assignment]
    count_session_service: CountSessionService = None  # type: ignore[assignment]
    relocation_service: RelocationService = None  # type: ignore[assignment]
    # Prompt 7 services
    config_service: ConfigService = None  # type: ignore[assignment]
    taxonomy_service: TaxonomyService = None  # type: ignore[assignment]
    integration_service: IntegrationService = None  # type: ignore[assignment]
    update_service: UpdateService = None  # type: ignore[assignment]
    audit_service: AuditService = None  # type: ignore[assignment]
    outbox_writer: OutboxWriter = None  # type: ignore[assignment]
    instrumentation: InstrumentationHooks = None  # type: ignore[assignment]
    scheduler: Any = None  # APScheduler BackgroundScheduler, started in bootstrap
    _active_checkpoints: list = field(default_factory=list)


def _run_migrations(db_path: str) -> None:
    """Run pending Alembic migrations to head before opening service connections."""
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    ini_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "alembic.ini")
    ini_path = os.path.normpath(ini_path)
    alembic_cfg = AlembicConfig(ini_path)
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    alembic_command.upgrade(alembic_cfg, "head")


def _validate_key_encryption_key(key_hex: str) -> None:
    """Validate DC_KEY_ENCRYPTION_KEY format (32-byte hex)."""
    if not key_hex:
        raise ValueError(
            "DC_KEY_ENCRYPTION_KEY is required and must be 64 hex characters."
        )
    try:
        raw = bytes.fromhex(key_hex)
    except ValueError as exc:
        raise ValueError("DC_KEY_ENCRYPTION_KEY must be a valid hex string.") from exc
    if len(raw) != 32:
        raise ValueError("DC_KEY_ENCRYPTION_KEY must decode to exactly 32 bytes.")


async def _recover_checkpoints(container: "AppContainer") -> list[dict]:
    """Load ACTIVE checkpoints and return them for UI state population."""
    import json

    async with container.session_factory() as session:
        checkpoints = await container.checkpoint_store.get_active(session)
    recovered: list[dict] = []
    for cp in checkpoints:
        state_json = cp.state_json
        state: Any = state_json
        if isinstance(state_json, str):
            try:
                state = json.loads(state_json)
            except ValueError:
                state = {}
        recovered.append(
            {
                "checkpoint_id": str(cp.id),
                "job_type": cp.job_type,
                "job_id": cp.job_id,
                "state_json": state,
            }
        )
    return recovered


async def _resume_recovered_checkpoints(
    container: "AppContainer", checkpoints: list[dict]
) -> None:
    """Run service-level resume handlers for recovered startup checkpoints."""
    for cp in checkpoints:
        job_type = str(cp.get("job_type", ""))
        job_id = str(cp.get("job_id", ""))
        state = cp.get("state_json")
        if not isinstance(state, dict):
            state = {}

        checkpoint_id: Optional[uuid.UUID] = None
        checkpoint_id_raw = cp.get("checkpoint_id")
        if checkpoint_id_raw is not None:
            try:
                checkpoint_id = uuid.UUID(str(checkpoint_id_raw))
            except (TypeError, ValueError):
                checkpoint_id = None

        outcome = "skipped"
        async with container.session_factory() as session:
            async with session.begin():
                try:
                    now = datetime.utcnow()
                    if job_type == "import":
                        outcome = await container.resource_service.resume_import_checkpoint(
                            session, job_id, state, now
                        )
                    elif job_type == "count":
                        outcome = await container.count_session_service.resume_count_checkpoint(
                            session, uuid.UUID(job_id), now
                        )
                    elif job_type == "approval":
                        outcome = await container.count_session_service.resume_approval_checkpoint(
                            session, uuid.UUID(job_id)
                        )

                    if checkpoint_id is not None:
                        if outcome == "completed":
                            await container.checkpoint_store.mark_completed(
                                session, checkpoint_id
                            )
                        elif outcome == "abandoned":
                            await container.checkpoint_store.mark_failed(
                                session,
                                checkpoint_id,
                                "Unable to resume checkpoint during startup recovery.",
                            )
                except Exception as exc:
                    if checkpoint_id is not None:
                        await container.checkpoint_store.mark_failed(
                            session, checkpoint_id, str(exc)[:240] or "Resume failed."
                        )
                    outcome = "failed"

        container.instrumentation.record_recovery_event(job_type or "unknown", job_id, outcome)


def _start_scheduler(container: "AppContainer"):
    """Start the APScheduler BackgroundScheduler with periodic maintenance jobs."""
    import asyncio
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = BackgroundScheduler()

    async def _expire_sessions() -> None:
        from datetime import datetime
        import uuid as _uuid
        from sqlalchemy import select
        from district_console.infrastructure.orm import CountSessionORM
        async with container.session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    select(CountSessionORM).where(CountSessionORM.status == "ACTIVE")
                )
                active_orns = result.scalars().all()
                now = datetime.utcnow()
                for orm in active_orns:
                    await container.count_session_service.check_and_expire(
                        session, _uuid.UUID(orm.id), now
                    )

    async def _retry_events() -> None:
        from datetime import datetime
        async with container.session_factory() as session:
            async with session.begin():
                await container.integration_service.retry_pending_events(
                    session, datetime.utcnow()
                )

    async def _enforce_key_lifecycle() -> None:
        from datetime import datetime
        async with container.session_factory() as session:
            async with session.begin():
                await container.integration_service.enforce_key_lifecycle(
                    session, datetime.utcnow()
                )

    def _run_async(coro_fn):
        """Run an async coroutine function in a new event loop (scheduler thread)."""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro_fn())
        finally:
            loop.close()

    scheduler.add_job(
        lambda: _run_async(_expire_sessions),
        trigger=IntervalTrigger(hours=1),
        id="expire_count_sessions",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run_async(_retry_events),
        trigger=IntervalTrigger(minutes=5),
        id="retry_pending_events",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run_async(_enforce_key_lifecycle),
        trigger=IntervalTrigger(hours=24),
        id="enforce_hmac_key_lifecycle",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler


async def bootstrap(config: AppConfig | None = None) -> AppContainer:
    """
    Compose and return a fully wired AppContainer.

    Does NOT start the HTTP server or PyQt event loop — those are the
    caller's responsibility (separate thread for FastAPI, main thread
    for PyQt).

    Args:
        config: Optional AppConfig override (e.g. for tests). If None,
                loads from environment variables via AppConfig.from_env().
    """
    config = config or AppConfig.from_env()

    _validate_key_encryption_key(config.key_encryption_key)

    # Configure logging first so all subsequent log output is sanitized
    configure_logging(config.log_level)

    # Run Alembic migrations before opening any DB connections
    _run_migrations(config.db_path)

    # Database engine and session factory
    engine = create_engine(config.db_path)
    session_factory = create_session_factory(engine)

    # Infrastructure repositories (stateless, shared)
    user_repo = UserRepository()
    role_repo = RoleRepository()
    audit_repo = AuditRepository()
    lock_repo = LockRepository()
    checkpoint_repo = CheckpointRepository()
    rate_limit_repo = RateLimitRepository()

    # Infrastructure services
    hmac_signer = HmacSigner()
    lock_manager = LockManager(lock_repo)
    checkpoint_store = CheckpointStore(checkpoint_repo)
    audit_writer = AuditWriter(audit_repo)
    rate_limiter = RateLimiter(rate_limit_repo)

    # Application services — auth
    auth_service = AuthService(user_repo, role_repo)
    rbac_service = RbacService()

    # Infrastructure repositories for Prompt 4 services
    resource_repo = ResourceRepository()
    revision_repo = ResourceRevisionRepository()
    review_task_repo = ReviewTaskRepository()
    metadata_repo = ResourceMetadataRepository()
    inventory_repo = InventoryRepository()
    ledger_repo = LedgerRepository()
    count_repo = CountSessionRepository()
    relocation_repo = RelocationRepository()

    # Application services — business workflows (Prompt 4)
    resource_service = ResourceService(
        resource_repo, revision_repo, review_task_repo,
        metadata_repo, audit_writer, lock_manager, checkpoint_store,
    )
    inventory_service = InventoryService(
        inventory_repo, ledger_repo, audit_writer, lock_manager,
    )
    count_session_service = CountSessionService(
        count_repo, inventory_repo, ledger_repo,
        audit_writer, lock_manager, checkpoint_store,
    )
    relocation_service = RelocationService(
        inventory_repo, ledger_repo, lock_manager, audit_writer, relocation_repo,
    )

    # Infrastructure repositories for Prompt 7 services
    config_repo = ConfigRepository()
    workflow_repo = WorkflowNodeRepository()
    template_repo = NotificationTemplateRepository()
    descriptor_repo = DistrictDescriptorRepository()
    taxonomy_repo = TaxonomyRepository()
    integration_repo = IntegrationRepository()
    update_pkg_repo = UpdatePackageRepository()
    audit_query_repo = AuditQueryRepository()

    # Outbox writer — disabled if lan_events_path not configured
    outbox_writer = OutboxWriter(lan_events_path=config.lan_events_path)

    # Instrumentation hooks — collects structured metrics logs
    instrumentation = InstrumentationHooks()

    # Application services — secondary modules (Prompt 7)
    config_service = ConfigService(
        config_repo, workflow_repo, template_repo, descriptor_repo, audit_writer,
    )
    taxonomy_service = TaxonomyService(taxonomy_repo, audit_writer)
    integration_service = IntegrationService(
        integration_repo, audit_writer, outbox_writer,
        master_key_hex=config.key_encryption_key,
    )
    update_service = UpdateService(update_pkg_repo, audit_writer)
    audit_service = AuditService(audit_query_repo, checkpoint_repo)

    # Assemble container (needed before create_app so app.state.container is set)
    container = AppContainer(
        config=config,
        engine=engine,
        session_factory=session_factory,
        auth_service=auth_service,
        rbac_service=rbac_service,
        lock_manager=lock_manager,
        checkpoint_store=checkpoint_store,
        audit_writer=audit_writer,
        hmac_signer=hmac_signer,
        rate_limiter=rate_limiter,
        api_app=None,  # type: ignore[arg-type]  # set below
        resource_service=resource_service,
        inventory_service=inventory_service,
        count_session_service=count_session_service,
        relocation_service=relocation_service,
        config_service=config_service,
        taxonomy_service=taxonomy_service,
        integration_service=integration_service,
        update_service=update_service,
        audit_service=audit_service,
        outbox_writer=outbox_writer,
        instrumentation=instrumentation,
    )

    container.api_app = create_app(container)

    # Recover and actively resume startup checkpoints before hydrating UI state.
    active_checkpoints = await _recover_checkpoints(container)
    await _resume_recovered_checkpoints(container, active_checkpoints)
    container._active_checkpoints = await _recover_checkpoints(container)

    # Start background scheduler (expiry + retry jobs)
    scheduler = _start_scheduler(container)
    container.scheduler = scheduler

    return container
