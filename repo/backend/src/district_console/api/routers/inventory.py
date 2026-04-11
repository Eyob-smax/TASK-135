"""
Inventory REST endpoints — items, warehouses, locations, stock, and ledger.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.api.dependencies import (
    get_current_user,
    get_current_user_with_scope,
    get_db_session,
    require_permission,
)
from district_console.api.scope_filters import (
    resolve_scoped_school_ids,
    resolve_school_scoped_location_ids,
    resolve_school_scoped_warehouse_ids,
)
from district_console.api.schemas import (
    AdjustmentRequest,
    CorrectionRequest,
    FreezeRequest,
    InventoryItemCreate,
    InventoryItemResponse,
    InventoryItemUpdate,
    LedgerEntryResponse,
    LocationCreate,
    LocationResponse,
    PaginatedResponse,
    StockBalanceResponse,
    WarehouseCreate,
    WarehouseResponse,
)
from district_console.application.inventory_service import InventoryService
from district_console.domain.entities.role import Role
from district_console.domain.enums import ScopeType, StockStatus
from district_console.domain.exceptions import (
    DomainValidationError,
    ScopeViolationError,
    StockFrozenError,
)

router = APIRouter()


def _get_inventory_service(request: Request) -> InventoryService:
    return request.app.state.container.inventory_service


def _item_to_schema(item) -> InventoryItemResponse:
    return InventoryItemResponse(
        item_id=str(item.id),
        sku=item.sku,
        name=item.name,
        description=item.description,
        unit_cost=str(item.unit_cost),
        created_at=item.created_at.isoformat(),
    )


def _warehouse_to_schema(warehouse) -> WarehouseResponse:
    return WarehouseResponse(
        warehouse_id=str(warehouse.id),
        name=warehouse.name,
        school_id=str(warehouse.school_id),
        address=warehouse.address,
        is_active=warehouse.is_active,
    )


def _location_to_schema(location) -> LocationResponse:
    return LocationResponse(
        location_id=str(location.id),
        warehouse_id=str(location.warehouse_id),
        zone=location.zone,
        aisle=location.aisle,
        bin_label=location.bin_label,
        is_active=location.is_active,
    )


def _stock_to_schema(balance) -> StockBalanceResponse:
    return StockBalanceResponse(
        balance_id=str(balance.id),
        item_id=str(balance.item_id),
        location_id=str(balance.location_id),
        status=balance.status.value,
        quantity=balance.quantity,
        is_frozen=balance.is_frozen,
        freeze_reason=balance.freeze_reason,
        batch_id=balance.batch_id,
        serial_id=balance.serial_id,
    )


def _ledger_to_schema(entry) -> LedgerEntryResponse:
    return LedgerEntryResponse(
        entry_id=str(entry.id),
        item_id=str(entry.item_id),
        location_id=str(entry.location_id),
        entry_type=entry.entry_type.value,
        quantity_delta=entry.quantity_delta,
        quantity_after=entry.quantity_after,
        operator_id=str(entry.operator_id),
        reason_code=entry.reason_code,
        created_at=entry.created_at.isoformat(),
        reference_id=entry.reference_id,
        is_reversed=entry.is_reversed,
        reversal_of_id=str(entry.reversal_of_id) if entry.reversal_of_id else None,
    )


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

@router.get("/items/", response_model=PaginatedResponse[InventoryItemResponse])
async def list_items(
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[InventoryItemResponse]:
    from district_console.application.rbac_service import RbacService
    _, roles, scopes = user_with_scope
    rbac = RbacService()
    rbac.check_permission(roles, "inventory.view")
    if not rbac.is_administrator(roles):
        # Inventory items are district-wide catalogue entries (no per-item scope FK).
        # Require at least one effective school derived from any supported scope type.
        if not await resolve_scoped_school_ids(session, scopes):
            raise ScopeViolationError("inventory", "all")
    svc = _get_inventory_service(request)
    items, total = await svc.list_items(session, offset, limit)
    return PaginatedResponse(
        items=[_item_to_schema(i) for i in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/items/",
    status_code=201,
    response_model=InventoryItemResponse,
    dependencies=[Depends(require_permission("inventory.adjust"))],
)
async def create_item(
    body: InventoryItemCreate,
    current_user: Annotated[tuple[uuid.UUID, list[Role]], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> InventoryItemResponse:
    actor_id, _ = current_user
    svc = _get_inventory_service(request)
    try:
        item = await svc.create_item(
            session,
            sku=body.sku,
            name=body.name,
            description=body.description,
            unit_cost=Decimal(body.unit_cost),
            created_by=actor_id,
            now=datetime.utcnow(),
        )
    except DomainValidationError as exc:
        raise HTTPException(status_code=409, detail={"code": "DUPLICATE_RESOURCE", "message": exc.message})
    return _item_to_schema(item)


@router.get(
    "/items/{item_id}",
    response_model=InventoryItemResponse,
    dependencies=[Depends(require_permission("inventory.view"))],
)
async def get_item(
    item_id: uuid.UUID,
    current_user: Annotated[tuple[uuid.UUID, list[Role]], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> InventoryItemResponse:
    svc = _get_inventory_service(request)
    try:
        item = await svc.get_item(session, item_id)
    except DomainValidationError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Item not found."})
    return _item_to_schema(item)


@router.put(
    "/items/{item_id}",
    response_model=InventoryItemResponse,
    dependencies=[Depends(require_permission("inventory.adjust"))],
)
async def update_item(
    item_id: uuid.UUID,
    body: InventoryItemUpdate,
    current_user: Annotated[tuple[uuid.UUID, list[Role]], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> InventoryItemResponse:
    actor_id, _ = current_user
    svc = _get_inventory_service(request)
    try:
        item = await svc.update_item(
            session,
            item_id,
            name=body.name,
            description=body.description,
            unit_cost=Decimal(body.unit_cost) if body.unit_cost is not None else None,
            actor_id=actor_id,
        )
    except DomainValidationError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Item not found."})
    return _item_to_schema(item)


# ---------------------------------------------------------------------------
# Warehouses
# ---------------------------------------------------------------------------

@router.get("/warehouses/", response_model=PaginatedResponse[WarehouseResponse])
async def list_warehouses(
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> PaginatedResponse[WarehouseResponse]:
    from district_console.application.rbac_service import RbacService
    _, roles, scopes = user_with_scope
    rbac = RbacService()
    rbac.check_permission(roles, "inventory.view")
    svc = _get_inventory_service(request)
    warehouses = await svc.list_warehouses(session)
    # Per-school scope filtering: non-admin users only see warehouses in their assigned schools.
    # filter_by_scope returns only school IDs the user is permitted to access.
    if not rbac.is_administrator(roles):
        if not scopes:
            raise ScopeViolationError("warehouses", "all")
        all_school_ids = [w.school_id for w in warehouses]
        allowed_ids = rbac.filter_by_scope(scopes, ScopeType.SCHOOL, all_school_ids)
        allowed_set = set(allowed_ids)
        warehouses = [w for w in warehouses if w.school_id in allowed_set]
    items = [_warehouse_to_schema(w) for w in warehouses]
    return PaginatedResponse(items=items, total=len(items), offset=0, limit=len(items))


@router.post(
    "/warehouses/",
    status_code=201,
    response_model=WarehouseResponse,
    dependencies=[Depends(require_permission("admin.manage_config"))],
)
async def create_warehouse(
    body: WarehouseCreate,
    current_user: Annotated[tuple[uuid.UUID, list[Role]], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> WarehouseResponse:
    actor_id, _ = current_user
    svc = _get_inventory_service(request)
    warehouse = await svc.create_warehouse(
        session,
        name=body.name,
        school_id=uuid.UUID(body.school_id),
        address=body.address,
        actor_id=actor_id,
    )
    return _warehouse_to_schema(warehouse)


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

@router.get("/locations/", response_model=list[LocationResponse])
async def list_locations(
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
    warehouse_id: Optional[str] = Query(None),
) -> list[LocationResponse]:
    from district_console.application.rbac_service import RbacService
    _, roles, scopes = user_with_scope
    rbac = RbacService()
    rbac.check_permission(roles, "inventory.view")

    svc = _get_inventory_service(request)
    allowed_warehouse_ids: Optional[set[uuid.UUID]] = None
    if not rbac.is_administrator(roles):
        resolved_ids = await resolve_school_scoped_warehouse_ids(session, scopes)
        if not resolved_ids:
            raise ScopeViolationError("locations", "all")
        allowed_warehouse_ids = resolved_ids

    if warehouse_id:
        wid = uuid.UUID(warehouse_id)
        if allowed_warehouse_ids is not None and wid not in allowed_warehouse_ids:
            raise ScopeViolationError("locations", warehouse_id)
        locations = await svc.list_locations(session, warehouse_id=wid)
    else:
        warehouse_ids_filter = list(allowed_warehouse_ids) if allowed_warehouse_ids is not None else None
        locations = await svc.list_locations(session, warehouse_ids=warehouse_ids_filter)

    return [_location_to_schema(loc) for loc in locations]


@router.post(
    "/locations/",
    status_code=201,
    response_model=LocationResponse,
    dependencies=[Depends(require_permission("admin.manage_config"))],
)
async def create_location(
    body: LocationCreate,
    current_user: Annotated[tuple[uuid.UUID, list[Role]], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> LocationResponse:
    actor_id, _ = current_user
    svc = _get_inventory_service(request)
    location = await svc.create_location(
        session,
        warehouse_id=uuid.UUID(body.warehouse_id),
        zone=body.zone,
        aisle=body.aisle,
        bin_label=body.bin_label,
        actor_id=actor_id,
    )
    return _location_to_schema(location)


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------

@router.get("/stock/", response_model=PaginatedResponse[StockBalanceResponse])
async def list_stock(
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
    item_id: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None),
    batch_id: Optional[str] = Query(None),
    serial_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[StockBalanceResponse]:
    from district_console.application.rbac_service import RbacService
    _, roles, scopes = user_with_scope
    rbac = RbacService()
    rbac.check_permission(roles, "inventory.view")
    svc = _get_inventory_service(request)
    iid = uuid.UUID(item_id) if item_id else None
    lid = uuid.UUID(location_id) if location_id else None
    location_ids_filter: Optional[list[uuid.UUID]] = None
    if not rbac.is_administrator(roles):
        allowed_location_ids = await resolve_school_scoped_location_ids(session, scopes)
        if not allowed_location_ids:
            raise ScopeViolationError("inventory", "all")
        if lid is not None:
            # Object-level: explicit location_id must be within the user's scope
            if lid not in allowed_location_ids:
                raise ScopeViolationError("inventory", str(lid))
        else:
            # No location filter specified: restrict results to user's scoped locations
            location_ids_filter = list(allowed_location_ids)
    balances, total = await svc.list_stock(
        session,
        iid,
        lid,
        batch_id,
        serial_id,
        status,
        offset,
        limit,
        location_ids=location_ids_filter,
    )
    return PaginatedResponse(
        items=[_stock_to_schema(b) for b in balances],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/stock/{balance_id}/freeze",
    response_model=StockBalanceResponse,
    dependencies=[Depends(require_permission("inventory.freeze"))],
)
async def freeze_stock(
    balance_id: uuid.UUID,
    body: FreezeRequest,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> StockBalanceResponse:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    svc = _get_inventory_service(request)
    if not RbacService().is_administrator(roles):
        allowed_location_ids = await resolve_school_scoped_location_ids(session, scopes)
        if not allowed_location_ids:
            raise ScopeViolationError("inventory", "all")
        balance = await svc._inventory_repo.get_stock_balance_by_id(session, balance_id)
        if balance is None:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Stock balance not found."})
        if balance.location_id not in allowed_location_ids:
            raise ScopeViolationError("inventory", str(balance_id))
    try:
        balance = await svc.freeze_stock(session, balance_id, body.reason, actor_id, datetime.utcnow())
    except StockFrozenError as exc:
        raise HTTPException(status_code=409, detail={"code": "STOCK_FROZEN", "message": exc.message})
    except DomainValidationError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": exc.message})
    return _stock_to_schema(balance)


@router.post(
    "/stock/{balance_id}/unfreeze",
    response_model=StockBalanceResponse,
    dependencies=[Depends(require_permission("inventory.freeze"))],
)
async def unfreeze_stock(
    balance_id: uuid.UUID,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> StockBalanceResponse:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    svc = _get_inventory_service(request)
    if not RbacService().is_administrator(roles):
        allowed_location_ids = await resolve_school_scoped_location_ids(session, scopes)
        if not allowed_location_ids:
            raise ScopeViolationError("inventory", "all")
        balance = await svc._inventory_repo.get_stock_balance_by_id(session, balance_id)
        if balance is None:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Stock balance not found."})
        if balance.location_id not in allowed_location_ids:
            raise ScopeViolationError("inventory", str(balance_id))
    try:
        balance = await svc.unfreeze_stock(session, balance_id, actor_id, datetime.utcnow())
    except DomainValidationError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": exc.message})
    return _stock_to_schema(balance)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

@router.get("/ledger/", response_model=PaginatedResponse[LedgerEntryResponse])
async def list_ledger(
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
    item_id: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None),
    entry_type: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[LedgerEntryResponse]:
    from district_console.application.rbac_service import RbacService
    _, roles, scopes = user_with_scope
    rbac = RbacService()
    rbac.check_permission(roles, "inventory.view")

    svc = _get_inventory_service(request)
    iid = uuid.UUID(item_id) if item_id else None
    lid = uuid.UUID(location_id) if location_id else None
    location_ids_filter: Optional[list[uuid.UUID]] = None
    if not rbac.is_administrator(roles):
        allowed_location_ids = await resolve_school_scoped_location_ids(session, scopes)
        if not allowed_location_ids:
            raise ScopeViolationError("inventory", "all")
        if lid is not None:
            if lid not in allowed_location_ids:
                raise ScopeViolationError("inventory", str(lid))
        else:
            location_ids_filter = list(allowed_location_ids)

    entries, total = await svc.list_ledger(
        session,
        item_id=iid,
        location_id=lid,
        location_ids=location_ids_filter,
        entry_type=entry_type,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse(
        items=[_ledger_to_schema(e) for e in entries],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/ledger/adjustment",
    status_code=201,
    response_model=LedgerEntryResponse,
    dependencies=[Depends(require_permission("inventory.adjust"))],
)
async def add_adjustment(
    body: AdjustmentRequest,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> LedgerEntryResponse:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    svc = _get_inventory_service(request)
    location_id = uuid.UUID(body.location_id)
    try:
        stock_status = StockStatus(body.status) if body.status is not None else StockStatus.AVAILABLE
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "Invalid stock status for adjustment partition.",
            },
        )
    if not RbacService().is_administrator(roles):
        allowed_location_ids = await resolve_school_scoped_location_ids(session, scopes)
        if not allowed_location_ids:
            raise ScopeViolationError("inventory", "all")
        if location_id not in allowed_location_ids:
            raise ScopeViolationError("inventory", str(location_id))
    try:
        entry = await svc.add_adjustment(
            session,
            item_id=uuid.UUID(body.item_id),
            location_id=location_id,
            quantity_delta=body.quantity_delta,
            reason_code=body.reason_code,
            operator_id=actor_id,
            now=datetime.utcnow(),
            batch_id=body.batch_id,
            serial_id=body.serial_id,
            status=stock_status,
        )
    except Exception as exc:
        from district_console.domain.exceptions import InsufficientStockError, StockFrozenError as SFE
        if isinstance(exc, SFE):
            raise HTTPException(status_code=409, detail={"code": "STOCK_FROZEN", "message": str(exc)})
        if isinstance(exc, InsufficientStockError):
            raise HTTPException(status_code=400, detail={"code": "INSUFFICIENT_STOCK", "message": str(exc)})
        raise
    return _ledger_to_schema(entry)


@router.post(
    "/ledger/correction/{entry_id}",
    status_code=201,
    response_model=LedgerEntryResponse,
    dependencies=[Depends(require_permission("inventory.adjust"))],
)
async def add_correction(
    entry_id: uuid.UUID,
    body: CorrectionRequest,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> LedgerEntryResponse:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    svc = _get_inventory_service(request)
    if not RbacService().is_administrator(roles):
        allowed_location_ids = await resolve_school_scoped_location_ids(session, scopes)
        if not allowed_location_ids:
            raise ScopeViolationError("inventory", "all")
        original = await svc._ledger_repo.get_by_id(session, entry_id)
        if original is None:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Ledger entry not found."})
        if original.location_id not in allowed_location_ids:
            raise ScopeViolationError("inventory", str(entry_id))
    try:
        entry = await svc.add_correction(
            session,
            entry_id=entry_id,
            reason_code=body.reason_code,
            operator_id=actor_id,
            now=datetime.utcnow(),
        )
    except Exception as exc:
        from district_console.domain.exceptions import AppendOnlyViolationError
        if isinstance(exc, AppendOnlyViolationError):
            raise HTTPException(status_code=400, detail={"code": "APPEND_ONLY_VIOLATION", "message": str(exc)})
        raise
    return _ledger_to_schema(entry)
