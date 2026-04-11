"""
Count session REST endpoints.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.api.dependencies import (
    get_current_user,
    get_current_user_with_scope,
    get_db_session,
    require_permission,
)
from district_console.api.scope_filters import resolve_school_scoped_warehouse_ids
from district_console.api.schemas import (
    CountApprovalRequest,
    CountLineCreate,
    CountLineResponse,
    CountLineUpdate,
    CountSessionCreate,
    CountSessionDetailResponse,
    CountSessionResponse,
    PaginatedResponse,
)
from district_console.application.count_session_service import CountSessionService
from district_console.domain.entities.role import Role
from district_console.domain.enums import CountMode
from district_console.domain.exceptions import (
    DomainValidationError,
    InsufficientPermissionError,
    ScopeViolationError,
)

router = APIRouter()


def _get_count_service(request: Request) -> CountSessionService:
    return request.app.state.container.count_session_service


def _session_to_schema(cs) -> CountSessionResponse:
    return CountSessionResponse(
        session_id=str(cs.id),
        mode=cs.mode.value,
        status=cs.status.value,
        warehouse_id=str(cs.warehouse_id),
        created_by=str(cs.created_by),
        created_at=cs.created_at.isoformat(),
        last_activity_at=cs.last_activity_at.isoformat(),
        closed_at=cs.closed_at.isoformat() if cs.closed_at else None,
        approved_by=str(cs.approved_by) if cs.approved_by else None,
        approved_at=cs.approved_at.isoformat() if cs.approved_at else None,
        expires_at=cs.expires_at.isoformat(),
    )


def _line_to_schema(line, mode: CountMode) -> CountLineResponse:
    # Blind mode: hide expected_qty from API callers
    expected = None if mode == CountMode.BLIND else line.expected_qty
    return CountLineResponse(
        line_id=str(line.id),
        session_id=str(line.session_id),
        item_id=str(line.item_id),
        location_id=str(line.location_id),
        expected_qty=expected,
        counted_qty=line.counted_qty,
        variance_qty=line.variance_qty,
        variance_value=str(line.variance_value),
        requires_approval=line.requires_approval,
        reason_code=line.reason_code,
    )


@router.get(
    "/count-sessions/",
    response_model=PaginatedResponse[CountSessionResponse],
    dependencies=[Depends(require_permission("inventory.view"))],
)
async def list_count_sessions(
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
    status: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[CountSessionResponse]:
    from district_console.application.rbac_service import RbacService
    _, roles, scopes = user_with_scope
    svc = _get_count_service(request)
    warehouse_ids: Optional[list[uuid.UUID]] = None
    if not RbacService().is_administrator(roles):
        allowed_warehouse_ids = await resolve_school_scoped_warehouse_ids(session, scopes)
        if not allowed_warehouse_ids:
            raise ScopeViolationError("count_sessions", "all")
        warehouse_ids = list(allowed_warehouse_ids)
    items, total = await svc.list_sessions(
        session,
        status=status,
        warehouse_ids=warehouse_ids,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse(
        items=[_session_to_schema(s) for s in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/count-sessions/",
    status_code=201,
    response_model=CountSessionResponse,
    dependencies=[Depends(require_permission("inventory.count"))],
)
async def open_count_session(
    body: CountSessionCreate,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> CountSessionResponse:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    warehouse_id = uuid.UUID(body.warehouse_id)
    if not RbacService().is_administrator(roles):
        allowed_warehouse_ids = await resolve_school_scoped_warehouse_ids(session, scopes)
        if warehouse_id not in allowed_warehouse_ids:
            raise ScopeViolationError("count_sessions", body.warehouse_id)
    svc = _get_count_service(request)
    now = datetime.utcnow()
    count_session = await svc.open_session(
        session,
        mode=CountMode(body.mode),
        warehouse_id=warehouse_id,
        created_by=actor_id,
        now=now,
    )
    return _session_to_schema(count_session)


@router.get(
    "/count-sessions/{session_id}",
    response_model=CountSessionDetailResponse,
    dependencies=[Depends(require_permission("inventory.view"))],
)
async def get_count_session(
    session_id: uuid.UUID,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> CountSessionDetailResponse:
    from district_console.application.rbac_service import RbacService
    _, roles, scopes = user_with_scope
    svc = _get_count_service(request)
    count_session = await svc._count_repo.get_by_id(session, session_id)
    if count_session is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Count session not found."})
    if not RbacService().is_administrator(roles):
        allowed_warehouse_ids = await resolve_school_scoped_warehouse_ids(session, scopes)
        if count_session.warehouse_id not in allowed_warehouse_ids:
            raise ScopeViolationError("count_sessions", str(session_id))

    lines = await svc._count_repo.get_lines(session, session_id)

    return CountSessionDetailResponse(
        session_id=str(count_session.id),
        mode=count_session.mode.value,
        status=count_session.status.value,
        warehouse_id=str(count_session.warehouse_id),
        created_by=str(count_session.created_by),
        created_at=count_session.created_at.isoformat(),
        last_activity_at=count_session.last_activity_at.isoformat(),
        closed_at=count_session.closed_at.isoformat() if count_session.closed_at else None,
        approved_by=str(count_session.approved_by) if count_session.approved_by else None,
        approved_at=count_session.approved_at.isoformat() if count_session.approved_at else None,
        expires_at=count_session.expires_at.isoformat(),
        lines=[_line_to_schema(ln, count_session.mode) for ln in lines],
    )


@router.post(
    "/count-sessions/{session_id}/line",
    status_code=201,
    response_model=CountLineResponse,
    dependencies=[Depends(require_permission("inventory.count"))],
)
async def add_count_line(
    session_id: uuid.UUID,
    body: CountLineCreate,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> CountLineResponse:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    svc = _get_count_service(request)
    if not RbacService().is_administrator(roles):
        allowed_warehouse_ids = await resolve_school_scoped_warehouse_ids(session, scopes)
        cs = await svc._count_repo.get_by_id(session, session_id)
        if cs is None or cs.warehouse_id not in allowed_warehouse_ids:
            raise ScopeViolationError("count_sessions", str(session_id))
    now = datetime.utcnow()
    try:
        line = await svc.add_count_line(
            session,
            session_id=session_id,
            item_id=uuid.UUID(body.item_id),
            location_id=uuid.UUID(body.location_id),
            counted_qty=body.counted_qty,
            reason_code=body.reason_code,
            operator_id=actor_id,
            now=now,
        )
    except DomainValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": "VALIDATION_ERROR", "message": exc.message})

    # Get mode for blind check
    count_session = await svc._count_repo.get_by_id(session, session_id)
    mode = count_session.mode if count_session else CountMode.OPEN
    return _line_to_schema(line, mode)


@router.put(
    "/count-sessions/{session_id}/lines/{line_id}",
    response_model=CountLineResponse,
    dependencies=[Depends(require_permission("inventory.count"))],
)
async def update_count_line(
    session_id: uuid.UUID,
    line_id: uuid.UUID,
    body: CountLineUpdate,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> CountLineResponse:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    svc = _get_count_service(request)
    if not RbacService().is_administrator(roles):
        allowed_warehouse_ids = await resolve_school_scoped_warehouse_ids(session, scopes)
        cs = await svc._count_repo.get_by_id(session, session_id)
        if cs is None or cs.warehouse_id not in allowed_warehouse_ids:
            raise ScopeViolationError("count_sessions", str(session_id))
    now = datetime.utcnow()
    try:
        line = await svc.update_count_line(
            session,
            session_id=session_id,
            line_id=line_id,
            counted_qty=body.counted_qty,
            operator_id=actor_id,
            now=now,
        )
    except DomainValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": "VALIDATION_ERROR", "message": exc.message})

    count_session = await svc._count_repo.get_by_id(session, session_id)
    mode = count_session.mode if count_session else CountMode.OPEN
    return _line_to_schema(line, mode)


@router.post(
    "/count-sessions/{session_id}/close",
    response_model=CountSessionResponse,
    dependencies=[Depends(require_permission("inventory.count"))],
)
async def close_count_session(
    session_id: uuid.UUID,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> CountSessionResponse:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    svc = _get_count_service(request)
    if not RbacService().is_administrator(roles):
        allowed_warehouse_ids = await resolve_school_scoped_warehouse_ids(session, scopes)
        cs = await svc._count_repo.get_by_id(session, session_id)
        if cs is None or cs.warehouse_id not in allowed_warehouse_ids:
            raise ScopeViolationError("count_sessions", str(session_id))
    try:
        count_session = await svc.close_session(session, session_id, actor_id, datetime.utcnow())
    except DomainValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": "VALIDATION_ERROR", "message": exc.message})
    return _session_to_schema(count_session)


@router.post(
    "/count-sessions/{session_id}/approve",
    response_model=CountSessionResponse,
    dependencies=[Depends(require_permission("inventory.approve_count"))],
)
async def approve_count_session(
    session_id: uuid.UUID,
    body: CountApprovalRequest,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> CountSessionResponse:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    svc = _get_count_service(request)
    if not RbacService().is_administrator(roles):
        allowed_warehouse_ids = await resolve_school_scoped_warehouse_ids(session, scopes)
        if not allowed_warehouse_ids:
            raise ScopeViolationError("count_sessions", "all")
        cs = await svc._count_repo.get_by_id(session, session_id)
        if cs is None:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Count session not found."})
        if cs.warehouse_id not in allowed_warehouse_ids:
            raise ScopeViolationError("count_sessions", str(session_id))
    try:
        count_session = await svc.approve_session(
            session, session_id, body.notes, actor_id, roles, datetime.utcnow()
        )
    except InsufficientPermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "INSUFFICIENT_PERMISSION", "message": exc.message})
    except DomainValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": "VALIDATION_ERROR", "message": exc.message})
    return _session_to_schema(count_session)
