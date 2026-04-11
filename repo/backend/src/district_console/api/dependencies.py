"""
FastAPI dependency injection functions for the District Console API.

Usage in route handlers:
    @router.get("/protected")
    async def my_route(
        current_user: Annotated[tuple[UUID, list[Role]], Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ): ...

Permission guard:
    @router.post("/resources/{id}/publish",
                 dependencies=[Depends(require_permission("resources.publish"))])
    async def publish_resource(...): ...
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, AsyncGenerator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.auth_service import AuthService
from district_console.application.rbac_service import RbacService
from district_console.domain.entities.role import Role
from district_console.domain.exceptions import IntegrationSigningError, SessionExpiredError
from district_console.infrastructure.hmac_signer import HmacSigner, decrypt_hmac_key
from district_console.infrastructure.rate_limiter import RateLimiter
from district_console.infrastructure.repositories import (
    IntegrationRepository,
    RateLimitRepository,
    ScopeRepository,
)

security = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------

async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an AsyncSession from the app-level session factory.

    The session is committed if no exception occurs; rolled back otherwise.
    """
    container = request.app.state.container
    async with container.session_factory() as session:
        async with session.begin():
            yield session


# ---------------------------------------------------------------------------
# Service accessors
# ---------------------------------------------------------------------------

def get_auth_service(request: Request) -> AuthService:
    """Return the AuthService singleton from the app container."""
    return request.app.state.container.auth_service


def get_rbac_service(request: Request) -> RbacService:
    """Return the RbacService singleton from the app container."""
    return request.app.state.container.rbac_service


def get_resource_service(request: Request):
    """Return the ResourceService singleton from the app container."""
    return request.app.state.container.resource_service


def get_inventory_service(request: Request):
    """Return the InventoryService singleton from the app container."""
    return request.app.state.container.inventory_service


def get_count_session_service(request: Request):
    """Return the CountSessionService singleton from the app container."""
    return request.app.state.container.count_session_service


def get_relocation_service(request: Request):
    """Return the RelocationService singleton from the app container."""
    return request.app.state.container.relocation_service


def get_config_service(request: Request):
    """Return the ConfigService singleton from the app container."""
    return request.app.state.container.config_service


def get_taxonomy_service(request: Request):
    """Return the TaxonomyService singleton from the app container."""
    return request.app.state.container.taxonomy_service


def get_integration_service(request: Request):
    """Return the IntegrationService singleton from the app container."""
    return request.app.state.container.integration_service


def get_update_service(request: Request):
    """Return the UpdateService singleton from the app container."""
    return request.app.state.container.update_service


def get_audit_service(request: Request):
    """Return the AuditService singleton from the app container."""
    return request.app.state.container.audit_service


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> tuple[uuid.UUID, list[Role]]:
    """
    Validate the Bearer token in the Authorization header.

    Returns:
        (user_id, roles) for the authenticated session.

    Raises:
        SessionExpiredError: If no token is provided or the token is invalid/expired.
            The ErrorHandlerMiddleware maps this to 401.
    """
    if credentials is None:
        raise SessionExpiredError()
    result = auth_service.validate_session(credentials.credentials, datetime.utcnow())
    if result is None:
        raise SessionExpiredError()
    return result


# ---------------------------------------------------------------------------
# Permission guard factory
# ---------------------------------------------------------------------------

async def get_current_user_with_scope(
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> tuple:
    """
    Return (user_id, roles, scopes) for the authenticated user.

    Loads scope assignments from the database in addition to the standard
    (user_id, roles) tuple returned by get_current_user.
    """
    user_id, roles = current_user
    scopes = await ScopeRepository.get_user_scopes(session, user_id)
    return user_id, roles, scopes


async def verify_hmac_auth(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> str:
    """
    Verify HMAC-SHA256 request signature and apply per-client rate limiting.

    Required headers:
        X-DC-Client-ID:  UUID of the registered integration client
        X-DC-Signature:  hmac-sha256 <hex_signature>
        X-DC-Timestamp:  Unix epoch seconds (must be within 300s of server time)

    Raises:
        IntegrationSigningError (401): Missing/invalid headers, unknown client,
            or signature verification failure.
        RateLimitExceededError (429): Client exceeded 60 req/min.

    Returns:
        The client_id string on success.
    """
    client_id_hdr = request.headers.get("X-DC-Client-ID")
    sig_hdr = request.headers.get("X-DC-Signature", "")
    ts_hdr = request.headers.get("X-DC-Timestamp")

    if not client_id_hdr or not sig_hdr or not ts_hdr:
        raise IntegrationSigningError()

    # Strip "hmac-sha256 " prefix per spec (allow bare hex too)
    signature = sig_hdr.removeprefix("hmac-sha256 ").strip()

    try:
        client_uuid = uuid.UUID(client_id_hdr)
    except ValueError:
        raise IntegrationSigningError()

    int_repo = IntegrationRepository()
    client = await int_repo.get_client(session, client_uuid)
    if client is None or not client.is_active:
        raise IntegrationSigningError()

    # Try active key first, then next key (supports key rotation window)
    signer = HmacSigner()
    body = await request.body()
    now = datetime.utcnow()
    verified = False
    for key_getter in (
        int_repo.get_active_key_for_client,
        int_repo.get_next_key_for_client,
    ):
        key_entity = await key_getter(session, client_uuid)
        if key_entity is None:
            continue
        if key_entity.expires_at <= now:
            continue
        master_key_hex = request.app.state.container.config.key_encryption_key
        raw_hex = decrypt_hmac_key(key_entity.key_encrypted, master_key_hex)
        key_bytes = HmacSigner.key_from_hex(raw_hex)
        if signer.verify(key_bytes, request.method, request.url.path, ts_hdr, body, signature, now):
            verified = True
            break

    if not verified:
        raise IntegrationSigningError()

    rate_limiter = RateLimiter(RateLimitRepository())
    await rate_limiter.check_and_record(session, client_id_hdr, now)
    return client_id_hdr


def require_permission(permission_name: str):
    """
    Dependency factory that enforces a permission check.

    Usage::
        @router.post("/foo", dependencies=[Depends(require_permission("resources.publish"))])

    Raises:
        InsufficientPermissionError: If the current user lacks the permission.
            The ErrorHandlerMiddleware maps this to 403.
    """
    async def _check(
        current_user: Annotated[
            tuple[uuid.UUID, list[Role]], Depends(get_current_user)
        ],
        rbac: Annotated[RbacService, Depends(get_rbac_service)],
    ) -> None:
        _user_id, roles = current_user
        rbac.check_permission(roles, permission_name)

    return _check
