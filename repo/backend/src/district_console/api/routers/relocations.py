"""
Relocation REST endpoints.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.api.dependencies import (
    get_current_user_with_scope,
    get_db_session,
    require_permission,
)
from district_console.api.scope_filters import resolve_school_scoped_location_ids
from district_console.api.schemas import PaginatedResponse, RelocationCreate, RelocationResponse
from district_console.application.relocation_service import RelocationService
from district_console.domain.enums import DeviceSource, StockStatus
from district_console.domain.exceptions import (
    DomainValidationError,
    InsufficientStockError,
    ScopeViolationError,
    StockFrozenError,
)

router = APIRouter()


def _get_relocation_service(request: Request) -> RelocationService:
    return request.app.state.container.relocation_service


def _relocation_to_schema(relocation) -> RelocationResponse:
    return RelocationResponse(
        relocation_id=str(relocation.id),
        item_id=str(relocation.item_id),
        from_location_id=str(relocation.from_location_id),
        to_location_id=str(relocation.to_location_id),
        quantity=relocation.quantity,
        operator_id=str(relocation.operator_id),
        device_source=relocation.device_source.value,
        created_at=relocation.created_at.isoformat(),
        ledger_debit_entry_id=str(relocation.ledger_debit_entry_id),
        ledger_credit_entry_id=str(relocation.ledger_credit_entry_id),
    )


@router.post(
    "/relocations/",
    status_code=201,
    response_model=RelocationResponse,
    dependencies=[Depends(require_permission("inventory.relocate"))],
)
async def create_relocation(
    body: RelocationCreate,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> RelocationResponse:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    from_location_id = uuid.UUID(body.from_location_id)
    to_location_id = uuid.UUID(body.to_location_id)
    if not RbacService().is_administrator(roles):
        allowed_location_ids = await resolve_school_scoped_location_ids(session, scopes)
        if (
            from_location_id not in allowed_location_ids
            or to_location_id not in allowed_location_ids
        ):
            raise ScopeViolationError("relocations", "all")

    try:
        stock_status = (
            StockStatus(body.status) if body.status is not None else StockStatus.AVAILABLE
        )
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "Invalid stock status for relocation partition.",
            },
        )

    svc = _get_relocation_service(request)
    try:
        relocation = await svc.relocate(
            session,
            item_id=uuid.UUID(body.item_id),
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            quantity=body.quantity,
            operator_id=actor_id,
            device_source=DeviceSource(body.device_source),
            now=datetime.utcnow(),
            batch_id=body.batch_id,
            serial_id=body.serial_id,
            status=stock_status,
        )
    except DomainValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": "VALIDATION_ERROR", "message": exc.message})
    except InsufficientStockError as exc:
        raise HTTPException(status_code=400, detail={"code": "INSUFFICIENT_STOCK", "message": str(exc)})
    except StockFrozenError as exc:
        raise HTTPException(status_code=409, detail={"code": "STOCK_FROZEN", "message": str(exc)})
    return _relocation_to_schema(relocation)


@router.get(
    "/relocations/",
    response_model=PaginatedResponse[RelocationResponse],
    dependencies=[Depends(require_permission("inventory.view"))],
)
async def list_relocations(
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
    item_id: Optional[str] = Query(None),
    operator_id: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[RelocationResponse]:
    from district_console.application.rbac_service import RbacService
    _, roles, scopes = user_with_scope
    svc = _get_relocation_service(request)
    iid = uuid.UUID(item_id) if item_id else None
    oid = uuid.UUID(operator_id) if operator_id else None
    location_ids: Optional[list[uuid.UUID]] = None
    if not RbacService().is_administrator(roles):
        allowed_location_ids = await resolve_school_scoped_location_ids(session, scopes)
        if not allowed_location_ids:
            raise ScopeViolationError("relocations", "all")
        location_ids = list(allowed_location_ids)

    relocations, total = await svc.list_relocations(
        session,
        item_id=iid,
        operator_id=oid,
        location_ids=location_ids,
        date_from=None,
        date_to=None,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse(
        items=[_relocation_to_schema(r) for r in relocations],
        total=total,
        offset=offset,
        limit=limit,
    )
