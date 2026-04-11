"""
Audit trail and admin visibility REST endpoints.

All routes require admin.view_audit_log permission (ADMINISTRATOR only).

Prefix: /api/v1/admin/audit
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.api.dependencies import (
    get_audit_service,
    get_current_user,
    get_db_session,
    require_permission,
)
from district_console.api.schemas import (
    AuditEventResponse,
    CheckpointStatusResponse,
    PaginatedResponse,
)

router = APIRouter()


@router.get(
    "/events/",
    response_model=PaginatedResponse[AuditEventResponse],
    dependencies=[Depends(require_permission("admin.view_audit_log"))],
)
async def list_audit_events(
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    action: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_audit_service),
):
    df = datetime.fromisoformat(date_from) if date_from else None
    dt = datetime.fromisoformat(date_to) if date_to else None
    events, total = await svc.list_audit_events(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        date_from=df,
        date_to=dt,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse(
        items=[_event_resp(e) for e in events],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/events/security/",
    response_model=PaginatedResponse[AuditEventResponse],
    dependencies=[Depends(require_permission("admin.view_audit_log"))],
)
async def list_security_events(
    offset: int = 0,
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_audit_service),
):
    events, total = await svc.list_security_events(session, offset=offset, limit=limit)
    return PaginatedResponse(
        items=[_event_resp(e) for e in events],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/approval-queue/",
    response_model=List[CheckpointStatusResponse],
    dependencies=[Depends(require_permission("admin.view_audit_log"))],
)
async def list_approval_queue(
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_audit_service),
):
    checkpoints = await svc.list_approval_queue(session)
    return [_checkpoint_resp(c) for c in checkpoints]


@router.get(
    "/checkpoints/",
    response_model=List[CheckpointStatusResponse],
    dependencies=[Depends(require_permission("admin.view_audit_log"))],
)
async def list_checkpoints(
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_audit_service),
):
    checkpoints = await svc.list_checkpoint_status(session)
    return [_checkpoint_resp(c) for c in checkpoints]


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _event_resp(e) -> AuditEventResponse:
    return AuditEventResponse(
        event_id=str(e.id),
        entity_type=e.entity_type,
        entity_id=str(e.entity_id),
        action=e.action,
        actor_id=str(e.actor_id),
        timestamp=e.timestamp.isoformat(),
        metadata=e.metadata if isinstance(e.metadata, dict) else {},
    )


def _checkpoint_resp(c) -> CheckpointStatusResponse:
    return CheckpointStatusResponse(
        checkpoint_id=str(c.id),
        job_type=c.job_type,
        job_id=c.job_id,
        status=c.status.value if hasattr(c.status, "value") else c.status,
        created_at=c.created_at.isoformat(),
        updated_at=c.updated_at.isoformat(),
        state_json=c.state_json,
    )
