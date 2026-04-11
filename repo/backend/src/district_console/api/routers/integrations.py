"""
Integration client management and outbound event REST endpoints.

Prefix: /api/v1/integrations
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.api.dependencies import (
    get_current_user,
    get_db_session,
    get_integration_service,
    require_permission,
)
from district_console.api.schemas import (
    HmacKeyResponse,
    IntegrationClientCreate,
    IntegrationClientResponse,
    OutboundEventCreate,
    OutboundEventResponse,
    PaginatedResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Integration clients
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=List[IntegrationClientResponse],
    dependencies=[Depends(require_permission("integrations.manage"))],
)
async def list_clients(
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_integration_service),
):
    clients = await svc.list_clients(session)
    return [_client_resp(c) for c in clients]


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("integrations.manage"))],
)
async def create_client(
    body: IntegrationClientCreate,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_integration_service),
):
    client, key, raw_key = await svc.create_client(
        session, body.name, body.description, current_user[0], datetime.utcnow()
    )
    return {
        "client": _client_resp(client),
        "initial_key": _key_resp(key, raw_key),
    }


@router.delete(
    "/{client_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("integrations.manage"))],
)
async def deactivate_client(
    client_id: str,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_integration_service),
):
    await svc.deactivate_client(
        session, uuid.UUID(client_id), current_user[0], datetime.utcnow()
    )


@router.post(
    "/{client_id}/rotate-key",
    response_model=HmacKeyResponse,
    dependencies=[Depends(require_permission("integrations.manage"))],
)
async def rotate_key(
    client_id: str,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_integration_service),
):
    key, raw_key = await svc.rotate_key(
        session, uuid.UUID(client_id), current_user[0], datetime.utcnow()
    )
    return _key_resp(key, raw_key)


@router.post(
    "/{client_id}/commit-rotation",
    response_model=HmacKeyResponse,
    dependencies=[Depends(require_permission("integrations.manage"))],
)
async def commit_rotation(
    client_id: str,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_integration_service),
):
    key = await svc.commit_rotation(
        session, uuid.UUID(client_id), current_user[0], datetime.utcnow()
    )
    # Raw key was already disclosed at rotate_key time; not re-exposed here
    return _key_resp(key, None)


# ---------------------------------------------------------------------------
# Outbound events
# ---------------------------------------------------------------------------

@router.get(
    "/events/",
    response_model=PaginatedResponse[OutboundEventResponse],
    dependencies=[Depends(require_permission("integrations.manage"))],
)
async def list_events(
    client_id: Optional[str] = None,
    event_status: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_integration_service),
):
    cid = uuid.UUID(client_id) if client_id else None
    events, total = await svc.list_events(
        session, client_id=cid, status=event_status, offset=offset, limit=limit
    )
    return PaginatedResponse(
        items=[_event_resp(e) for e in events],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/events/{client_id}/emit",
    response_model=OutboundEventResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("integrations.manage"))],
)
async def emit_event(
    client_id: str,
    body: OutboundEventCreate,
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_integration_service),
):
    cid = uuid.UUID(client_id)
    clients = await svc.list_clients(session)
    client = next((c for c in clients if c.id == cid and c.is_active), None)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "NOT_FOUND",
                "message": f"Integration client '{client_id}' was not found or is inactive.",
            },
        )
    event = await svc.write_outbound_event(
        session,
        client.id,
        body.event_type,
        body.payload,
        datetime.utcnow(),
    )
    return _event_resp(event)


@router.post(
    "/events/retry",
    dependencies=[Depends(require_permission("integrations.manage"))],
)
async def retry_events(
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_integration_service),
):
    result = await svc.retry_pending_events(session, datetime.utcnow())
    return result


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _client_resp(c) -> IntegrationClientResponse:
    return IntegrationClientResponse(
        client_id=str(c.id),
        name=c.name,
        description=c.description,
        is_active=c.is_active,
        created_at=c.created_at.isoformat(),
    )


def _key_resp(k, raw_key: Optional[str] = None) -> HmacKeyResponse:
    return HmacKeyResponse(
        key_id=str(k.id),
        client_id=str(k.client_id),
        key_value=raw_key,  # None unless this is a create/rotate response
        created_at=k.created_at.isoformat(),
        expires_at=k.expires_at.isoformat(),
        is_active=k.is_active,
        is_next=k.is_next,
    )


def _event_resp(e) -> OutboundEventResponse:
    return OutboundEventResponse(
        event_id=str(e.id),
        client_id=str(e.client_id),
        event_type=e.event_type,
        status=e.status,
        created_at=e.created_at.isoformat(),
        delivered_at=e.delivered_at.isoformat() if e.delivered_at else None,
        retry_count=e.retry_count,
        last_error=e.last_error,
    )
