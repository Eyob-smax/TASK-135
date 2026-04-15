"""
API test fixtures for District Console FastAPI endpoints.

Provides:
  - test_container:    AppContainer wired with the test engine and in-memory sessions.
  - test_app:          FastAPI app created from test_container.
  - http_client:       httpx.AsyncClient backed by the test app (no real HTTP server).
  - auth_headers:      Authorization header with a valid Bearer token for testuser.
  - librarian_headers: Auth headers for a user with LIBRARIAN role.
  - reviewer_headers:  Auth headers for a user with REVIEWER role.
  - admin_headers:     Auth headers for a user with ADMINISTRATOR role.

These fixtures depend on the shared conftest.py fixtures (test_engine,
db_session, seeded_user_orm, sample_password).
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
from district_console.bootstrap import AppContainer
from district_console.bootstrap.config import AppConfig
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.checkpoint_store import CheckpointStore
from district_console.infrastructure.hmac_signer import HmacSigner
from district_console.infrastructure.instrumentation import InstrumentationHooks
from district_console.infrastructure.lock_manager import LockManager
from district_console.infrastructure.orm import UserORM, UserRoleORM
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


TEST_MASTER_KEY_HEX = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


@pytest.fixture
def test_container(test_engine, seeded_user_orm):
    """
    Build an AppContainer wired with the in-memory test engine.

    seeded_user_orm is a dependency so the test user exists before the
    container is used.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    user_repo = UserRepository()
    role_repo = RoleRepository()
    audit_repo = AuditRepository()
    lock_repo = LockRepository()
    checkpoint_repo = CheckpointRepository()
    rate_limit_repo = RateLimitRepository()

    hmac_signer = HmacSigner()
    lock_manager = LockManager(lock_repo)
    checkpoint_store = CheckpointStore(checkpoint_repo)
    audit_writer = AuditWriter(audit_repo)
    rate_limiter = RateLimiter(rate_limit_repo)
    auth_service = AuthService(user_repo, role_repo)
    rbac_service = RbacService()

    resource_service = ResourceService(
        ResourceRepository(), ResourceRevisionRepository(), ReviewTaskRepository(),
        ResourceMetadataRepository(), audit_writer, lock_manager, checkpoint_store,
    )
    inventory_service = InventoryService(
        InventoryRepository(), LedgerRepository(), audit_writer, lock_manager,
    )
    count_session_service = CountSessionService(
        CountSessionRepository(), InventoryRepository(), LedgerRepository(),
        audit_writer, lock_manager, checkpoint_store,
    )
    relocation_service = RelocationService(
        InventoryRepository(), LedgerRepository(), lock_manager, audit_writer,
        RelocationRepository(),
    )

    # Prompt 7 services (wired with disabled outbox)
    outbox_writer = OutboxWriter(lan_events_path=None)
    config_service = ConfigService(
        ConfigRepository(), WorkflowNodeRepository(),
        NotificationTemplateRepository(), DistrictDescriptorRepository(),
        audit_writer,
    )
    taxonomy_service = TaxonomyService(TaxonomyRepository(), audit_writer)
    integration_service = IntegrationService(
        IntegrationRepository(),
        audit_writer,
        outbox_writer,
        master_key_hex=TEST_MASTER_KEY_HEX,
    )
    update_service = UpdateService(UpdatePackageRepository(), audit_writer)
    audit_service = AuditService(AuditQueryRepository(), checkpoint_repo)

    config = AppConfig(db_path=":memory:", key_encryption_key=TEST_MASTER_KEY_HEX)

    container = AppContainer(
        config=config,
        engine=test_engine,
        session_factory=session_factory,
        auth_service=auth_service,
        rbac_service=rbac_service,
        lock_manager=lock_manager,
        checkpoint_store=checkpoint_store,
        audit_writer=audit_writer,
        hmac_signer=hmac_signer,
        rate_limiter=rate_limiter,
        api_app=None,  # type: ignore[arg-type]
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
        instrumentation=InstrumentationHooks(),
    )
    container.api_app = create_app(container)
    return container


@pytest.fixture
def test_app(test_container):
    """Return the FastAPI test application."""
    return test_container.api_app


@pytest.fixture
async def http_client(test_app):
    """
    Yield an httpx AsyncClient backed by the test app.

    No real HTTP server is started — requests go through ASGI transport.
    """
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
async def auth_headers(http_client, sample_password):
    """
    Obtain a valid Authorization header by calling the login endpoint.

    Returns a dict ready for use as request headers.
    """
    response = await http_client.post(
        "/api/v1/auth/login",
        json={"username": "testuser", "password": sample_password},
    )
    assert response.status_code == 200, f"Login failed in fixture: {response.text}"
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


async def _create_user_with_role(
    db_session: AsyncSession,
    http_client,
    username: str,
    password: str,
    role_orm,
    seeded_user_orm,
) -> dict:
    """
    Insert a UserORM + UserRoleORM, log in via the API, return Authorization header dict.
    """
    auth = AuthService(UserRepository(), RoleRepository())
    password_hash = auth.hash_password(password)
    now = datetime.utcnow().isoformat()

    user = UserORM(
        id=str(uuid.uuid4()),
        username=username,
        password_hash=password_hash,
        is_active=True,
        failed_attempts=0,
        locked_until=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(user)
    await db_session.flush()

    user_role = UserRoleORM(
        user_id=user.id,
        role_id=role_orm.id,
        assigned_by=seeded_user_orm.id,
        assigned_at=now,
    )
    db_session.add(user_role)
    await db_session.flush()

    response = await http_client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, f"Role-user login failed: {response.text}"
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def librarian_headers(db_session, http_client, seeded_roles, sample_password, seeded_user_orm) -> dict:
    """Auth headers for a user with LIBRARIAN role."""
    return await _create_user_with_role(
        db_session, http_client, "librarian_user", sample_password,
        seeded_roles["LIBRARIAN"], seeded_user_orm,
    )


@pytest.fixture
async def reviewer_headers(db_session, http_client, seeded_roles, sample_password, seeded_user_orm) -> dict:
    """Auth headers for a user with REVIEWER role."""
    return await _create_user_with_role(
        db_session, http_client, "reviewer_user", sample_password,
        seeded_roles["REVIEWER"], seeded_user_orm,
    )


@pytest.fixture
async def admin_headers(db_session, http_client, seeded_roles, sample_password, seeded_user_orm) -> dict:
    """Auth headers for a user with ADMINISTRATOR role."""
    return await _create_user_with_role(
        db_session, http_client, "admin_user", sample_password,
        seeded_roles["ADMINISTRATOR"], seeded_user_orm,
    )


@pytest.fixture
async def real_http_url(test_app):
    """
    Start the FastAPI test app on a real TCP port using uvicorn as an asyncio
    task within the same event loop.  Yields the base URL string.

    This lets tests exercise the full HTTP stack (real socket, real TCP
    transport, no ASGI short-circuit) without cross-loop SQLAlchemy issues.
    """
    import asyncio
    import socket

    import uvicorn

    # Pick a random free port on the loopback interface
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    config = uvicorn.Config(
        test_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        loop="none",  # reuse the running asyncio loop managed by pytest-asyncio
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())

    # Wait for the server to signal it is ready
    while not server.started:
        await asyncio.sleep(0.05)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    await task
