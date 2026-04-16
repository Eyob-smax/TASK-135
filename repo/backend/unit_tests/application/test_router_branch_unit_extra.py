from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from district_console.api.routers import inventory as inventory_router
from district_console.api.routers import resources as resources_router
from district_console.api.schemas import (
    AdjustmentRequest,
    ClassifyRequest,
    CorrectionRequest,
    FreezeRequest,
    ResourceCreate,
    ResourceUpdate,
)
from district_console.domain.entities.role import Role
from district_console.domain.entities.role import Permission
from district_console.domain.enums import ResourceStatus, ResourceType, RoleType, ScopeType, StockStatus
from district_console.domain.exceptions import (
    AppendOnlyViolationError,
    DomainValidationError,
    DuplicateResourceError,
    InsufficientStockError,
    ResourceNotFoundError,
    ScopeViolationError,
    StockFrozenError,
)


def _admin_roles() -> list[Role]:
    return [Role(id=uuid.uuid4(), role_type=RoleType.ADMINISTRATOR, display_name="Admin")]


def _librarian_roles() -> list[Role]:
    perms = frozenset(
        {
            Permission(uuid.uuid4(), "resources.view", "resources", "view"),
            Permission(uuid.uuid4(), "inventory.view", "inventory", "view"),
        }
    )
    return [
        Role(
            id=uuid.uuid4(),
            role_type=RoleType.LIBRARIAN,
            display_name="Librarian",
            permissions=perms,
        )
    ]


def _scope_assignment(scope_type: ScopeType, scope_ref_id: uuid.UUID):
    return SimpleNamespace(scope_type=scope_type, scope_ref_id=scope_ref_id)


def _request_with_services(*, resource_service=None, inventory_service=None):
    container = SimpleNamespace(resource_service=resource_service, inventory_service=inventory_service)
    app = SimpleNamespace(state=SimpleNamespace(container=container))
    return SimpleNamespace(app=app)


def _resource_stub(status: ResourceStatus = ResourceStatus.DRAFT):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid.uuid4(),
        title="Stub Resource",
        resource_type=ResourceType.BOOK,
        status=status,
        file_fingerprint="abc123",
        isbn=None,
        dedup_key="dedup-key",
        created_by=uuid.uuid4(),
        created_at=now,
        updated_at=now,
        owner_scope_type=None,
        owner_scope_ref_id=None,
    )


@pytest.mark.asyncio
async def test_create_resource_duplicate_maps_to_409():
    class Svc:
        async def import_file(self, *args, **kwargs):
            raise DuplicateResourceError(existing_id="existing-1", dedup_key="k")

    req = _request_with_services(resource_service=Svc())
    with pytest.raises(HTTPException) as exc_info:
        await resources_router.create_resource(
            body=ResourceCreate(title="A", resource_type="BOOK"),
            current_user=(uuid.uuid4(), _admin_roles()),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "DUPLICATE_RESOURCE"


@pytest.mark.asyncio
async def test_list_resources_non_admin_without_scope_raises_scope_violation():
    class Svc:
        async def list_resources(self, *args, **kwargs):
            return [], 0

        async def get_resource_metadata(self, *args, **kwargs):
            return None

    req = _request_with_services(resource_service=Svc())
    with pytest.raises(ScopeViolationError):
        await resources_router.list_resources(
            user_with_scope=(uuid.uuid4(), _librarian_roles(), []),
            session=None,
            request=req,
        )


@pytest.mark.asyncio
async def test_update_resource_non_draft_maps_to_409():
    class Svc:
        async def get_resource(self, *args, **kwargs):
            return _resource_stub(status=ResourceStatus.PUBLISHED)

    req = _request_with_services(resource_service=Svc())
    with pytest.raises(HTTPException) as exc_info:
        await resources_router.update_resource(
            resource_id=uuid.uuid4(),
            body=ResourceUpdate(title="New"),
            user_with_scope=(uuid.uuid4(), _admin_roles(), []),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "INVALID_STATE_TRANSITION"


@pytest.mark.asyncio
async def test_classify_resource_validation_error_maps_to_400():
    class Svc:
        async def get_resource(self, *args, **kwargs):
            return _resource_stub()

        async def classify_resource(self, *args, **kwargs):
            raise DomainValidationError("min_age", -1, ">= 0")

    req = _request_with_services(resource_service=Svc())
    with pytest.raises(HTTPException) as exc_info:
        await resources_router.classify_resource(
            resource_id=uuid.uuid4(),
            body=ClassifyRequest(min_age=10, max_age=8, timeliness_type="CURRENT"),
            user_with_scope=(uuid.uuid4(), _admin_roles(), []),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_request_allocation_not_found_maps_to_404():
    class Svc:
        async def get_resource(self, *args, **kwargs):
            raise ResourceNotFoundError("missing")

    req = _request_with_services(resource_service=Svc())
    with pytest.raises(HTTPException) as exc_info:
        await resources_router.request_allocation(
            resource_id=uuid.uuid4(),
            user_with_scope=(uuid.uuid4(), _admin_roles(), []),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_revisions_not_found_maps_to_404():
    class Svc:
        async def list_revisions(self, *args, **kwargs):
            raise ResourceNotFoundError("missing")

    req = _request_with_services(resource_service=Svc())
    with pytest.raises(HTTPException) as exc_info:
        await resources_router.list_revisions(
            resource_id=uuid.uuid4(),
            user_with_scope=(uuid.uuid4(), _admin_roles(), []),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_locations_outside_scope_raises_scope_violation(monkeypatch):
    scoped_warehouse = uuid.uuid4()

    async def _resolved_ids(*args, **kwargs):
        return {scoped_warehouse}

    monkeypatch.setattr(inventory_router, "resolve_school_scoped_warehouse_ids", _resolved_ids)

    class Svc:
        async def list_locations(self, *args, **kwargs):
            return []

    req = _request_with_services(inventory_service=Svc())
    outside_warehouse = uuid.uuid4()

    with pytest.raises(ScopeViolationError):
        await inventory_router.list_locations(
            user_with_scope=(uuid.uuid4(), _librarian_roles(), [_scope_assignment(ScopeType.SCHOOL, uuid.uuid4())]),
            session=None,
            request=req,
            warehouse_id=str(outside_warehouse),
        )


@pytest.mark.asyncio
async def test_list_stock_explicit_out_of_scope_location_raises_scope_violation(monkeypatch):
    allowed_location = uuid.uuid4()

    async def _resolved_ids(*args, **kwargs):
        return {allowed_location}

    monkeypatch.setattr(inventory_router, "resolve_school_scoped_location_ids", _resolved_ids)

    class Svc:
        async def list_stock(self, *args, **kwargs):
            return [], 0

    req = _request_with_services(inventory_service=Svc())
    outside_location = uuid.uuid4()

    with pytest.raises(ScopeViolationError):
        await inventory_router.list_stock(
            user_with_scope=(uuid.uuid4(), _librarian_roles(), [_scope_assignment(ScopeType.SCHOOL, uuid.uuid4())]),
            session=None,
            request=req,
            item_id=None,
            location_id=str(outside_location),
            batch_id=None,
            serial_id=None,
            status=None,
            offset=0,
            limit=50,
        )


@pytest.mark.asyncio
async def test_list_ledger_explicit_out_of_scope_location_raises_scope_violation(monkeypatch):
    allowed_location = uuid.uuid4()

    async def _resolved_ids(*args, **kwargs):
        return {allowed_location}

    monkeypatch.setattr(inventory_router, "resolve_school_scoped_location_ids", _resolved_ids)

    class Svc:
        async def list_ledger(self, *args, **kwargs):
            return [], 0

    req = _request_with_services(inventory_service=Svc())
    outside_location = uuid.uuid4()

    with pytest.raises(ScopeViolationError):
        await inventory_router.list_ledger(
            user_with_scope=(uuid.uuid4(), _librarian_roles(), [_scope_assignment(ScopeType.SCHOOL, uuid.uuid4())]),
            session=None,
            request=req,
            item_id=None,
            location_id=str(outside_location),
            entry_type=None,
            offset=0,
            limit=50,
        )


@pytest.mark.asyncio
async def test_freeze_stock_non_admin_balance_not_found_maps_to_404(monkeypatch):
    async def _resolved_ids(*args, **kwargs):
        return {uuid.uuid4()}

    monkeypatch.setattr(inventory_router, "resolve_school_scoped_location_ids", _resolved_ids)

    async def _missing_balance(*args, **kwargs):
        return None

    svc = SimpleNamespace(
        _inventory_repo=SimpleNamespace(get_stock_balance_by_id=_missing_balance),
    )
    req = _request_with_services(inventory_service=svc)

    with pytest.raises(HTTPException) as exc_info:
        await inventory_router.freeze_stock(
            balance_id=uuid.uuid4(),
            body=FreezeRequest(reason="audit"),
            user_with_scope=(uuid.uuid4(), _librarian_roles(), [_scope_assignment(ScopeType.SCHOOL, uuid.uuid4())]),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_unfreeze_stock_non_admin_balance_not_found_maps_to_404(monkeypatch):
    async def _resolved_ids(*args, **kwargs):
        return {uuid.uuid4()}

    monkeypatch.setattr(inventory_router, "resolve_school_scoped_location_ids", _resolved_ids)

    async def _missing_balance(*args, **kwargs):
        return None

    svc = SimpleNamespace(
        _inventory_repo=SimpleNamespace(get_stock_balance_by_id=_missing_balance),
    )
    req = _request_with_services(inventory_service=svc)

    with pytest.raises(HTTPException) as exc_info:
        await inventory_router.unfreeze_stock(
            balance_id=uuid.uuid4(),
            user_with_scope=(uuid.uuid4(), _librarian_roles(), [_scope_assignment(ScopeType.SCHOOL, uuid.uuid4())]),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_add_adjustment_stock_frozen_maps_to_409():
    class Svc:
        async def add_adjustment(self, *args, **kwargs):
            raise StockFrozenError("bal-1")

    req = _request_with_services(inventory_service=Svc())

    with pytest.raises(HTTPException) as exc_info:
        await inventory_router.add_adjustment(
            body=AdjustmentRequest(
                item_id=str(uuid.uuid4()),
                location_id=str(uuid.uuid4()),
                quantity_delta=1,
                reason_code="TEST",
                status=StockStatus.AVAILABLE.value,
            ),
            user_with_scope=(uuid.uuid4(), _admin_roles(), []),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "STOCK_FROZEN"


@pytest.mark.asyncio
async def test_add_adjustment_insufficient_stock_maps_to_400():
    class Svc:
        async def add_adjustment(self, *args, **kwargs):
            raise InsufficientStockError("item", "loc", 0, 5)

    req = _request_with_services(inventory_service=Svc())

    with pytest.raises(HTTPException) as exc_info:
        await inventory_router.add_adjustment(
            body=AdjustmentRequest(
                item_id=str(uuid.uuid4()),
                location_id=str(uuid.uuid4()),
                quantity_delta=-5,
                reason_code="TEST",
                status=StockStatus.AVAILABLE.value,
            ),
            user_with_scope=(uuid.uuid4(), _admin_roles(), []),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "INSUFFICIENT_STOCK"


@pytest.mark.asyncio
async def test_add_correction_append_only_maps_to_400():
    class Svc:
        async def add_correction(self, *args, **kwargs):
            raise AppendOnlyViolationError("ledger_entries", "entry-1")

    req = _request_with_services(inventory_service=Svc())

    with pytest.raises(HTTPException) as exc_info:
        await inventory_router.add_correction(
            entry_id=uuid.uuid4(),
            body=CorrectionRequest(reason_code="FIX"),
            user_with_scope=(uuid.uuid4(), _admin_roles(), []),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "APPEND_ONLY_VIOLATION"
