from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from district_console.api.routers import count_sessions as count_router
from district_console.api.schemas import (
    CountApprovalRequest,
    CountLineCreate,
    CountLineUpdate,
    CountSessionCreate,
)
from district_console.domain.entities.role import Permission, Role
from district_console.domain.enums import CountMode, CountSessionStatus, RoleType, ScopeType
from district_console.domain.exceptions import DomainValidationError, InsufficientPermissionError, ScopeViolationError


def _librarian_roles() -> list[Role]:
    perms = frozenset(
        {
            Permission(uuid.uuid4(), "inventory.view", "inventory", "view"),
            Permission(uuid.uuid4(), "inventory.count", "inventory", "count"),
            Permission(uuid.uuid4(), "inventory.approve_count", "inventory", "approve_count"),
        }
    )
    return [Role(id=uuid.uuid4(), role_type=RoleType.LIBRARIAN, display_name="Librarian", permissions=perms)]


def _request_with_service(service):
    app = SimpleNamespace(state=SimpleNamespace(container=SimpleNamespace(count_session_service=service)))
    return SimpleNamespace(app=app)


def _count_session_stub(warehouse_id: uuid.UUID):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid.uuid4(),
        mode=CountMode.OPEN,
        status=CountSessionStatus.ACTIVE,
        warehouse_id=warehouse_id,
        created_by=uuid.uuid4(),
        created_at=now,
        last_activity_at=now,
        closed_at=None,
        approved_by=None,
        approved_at=None,
        expires_at=now,
    )


@pytest.mark.asyncio
async def test_list_count_sessions_non_admin_no_scope_raises(monkeypatch):
    async def _resolved_ids(*args, **kwargs):
        return set()

    monkeypatch.setattr(count_router, "resolve_school_scoped_warehouse_ids", _resolved_ids)

    class Svc:
        async def list_sessions(self, *args, **kwargs):
            return [], 0

    req = _request_with_service(Svc())

    with pytest.raises(ScopeViolationError):
        await count_router.list_count_sessions(
            user_with_scope=(uuid.uuid4(), _librarian_roles(), []),
            session=None,
            request=req,
            status=None,
            offset=0,
            limit=50,
        )


@pytest.mark.asyncio
async def test_open_count_session_non_admin_out_of_scope_raises(monkeypatch):
    allowed_warehouse = uuid.uuid4()

    async def _resolved_ids(*args, **kwargs):
        return {allowed_warehouse}

    monkeypatch.setattr(count_router, "resolve_school_scoped_warehouse_ids", _resolved_ids)

    class Svc:
        async def open_session(self, *args, **kwargs):
            raise AssertionError("should not be called")

    req = _request_with_service(Svc())

    with pytest.raises(ScopeViolationError):
        await count_router.open_count_session(
            body=CountSessionCreate(mode="OPEN", warehouse_id=str(uuid.uuid4())),
            user_with_scope=(uuid.uuid4(), _librarian_roles(), [_scope_assignment()]),
            session=None,
            request=req,
        )


@pytest.mark.asyncio
async def test_get_count_session_not_found_maps_to_404():
    class Repo:
        async def get_by_id(self, *args, **kwargs):
            return None

    svc = SimpleNamespace(_count_repo=Repo())
    req = _request_with_service(svc)

    with pytest.raises(HTTPException) as exc_info:
        await count_router.get_count_session(
            session_id=uuid.uuid4(),
            user_with_scope=(uuid.uuid4(), _librarian_roles(), [_scope_assignment()]),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_add_count_line_domain_validation_maps_to_400(monkeypatch):
    warehouse_id = uuid.uuid4()

    async def _resolved_ids(*args, **kwargs):
        return {warehouse_id}

    monkeypatch.setattr(count_router, "resolve_school_scoped_warehouse_ids", _resolved_ids)

    cs = _count_session_stub(warehouse_id)

    class Repo:
        async def get_by_id(self, *args, **kwargs):
            return cs

    class Svc:
        _count_repo = Repo()

        async def add_count_line(self, *args, **kwargs):
            raise DomainValidationError("counted_qty", -1, ">= 0")

    req = _request_with_service(Svc())

    with pytest.raises(HTTPException) as exc_info:
        await count_router.add_count_line(
            session_id=uuid.uuid4(),
            body=CountLineCreate(
                item_id=str(uuid.uuid4()),
                location_id=str(uuid.uuid4()),
                counted_qty=5,
                reason_code="COUNT",
            ),
            user_with_scope=(uuid.uuid4(), _librarian_roles(), [_scope_assignment()]),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_update_count_line_domain_validation_maps_to_400(monkeypatch):
    warehouse_id = uuid.uuid4()

    async def _resolved_ids(*args, **kwargs):
        return {warehouse_id}

    monkeypatch.setattr(count_router, "resolve_school_scoped_warehouse_ids", _resolved_ids)

    cs = _count_session_stub(warehouse_id)

    class Repo:
        async def get_by_id(self, *args, **kwargs):
            return cs

    class Svc:
        _count_repo = Repo()

        async def update_count_line(self, *args, **kwargs):
            raise DomainValidationError("counted_qty", -1, ">= 0")

    req = _request_with_service(Svc())

    with pytest.raises(HTTPException) as exc_info:
        await count_router.update_count_line(
            session_id=uuid.uuid4(),
            line_id=uuid.uuid4(),
            body=CountLineUpdate(counted_qty=3),
            user_with_scope=(uuid.uuid4(), _librarian_roles(), [_scope_assignment()]),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_close_count_session_domain_validation_maps_to_400(monkeypatch):
    warehouse_id = uuid.uuid4()

    async def _resolved_ids(*args, **kwargs):
        return {warehouse_id}

    monkeypatch.setattr(count_router, "resolve_school_scoped_warehouse_ids", _resolved_ids)

    class Repo:
        async def get_by_id(self, *args, **kwargs):
            return _count_session_stub(warehouse_id)

    class Svc:
        _count_repo = Repo()

        async def close_session(self, *args, **kwargs):
            raise DomainValidationError("status", "ACTIVE", "must be closeable")

    req = _request_with_service(Svc())

    with pytest.raises(HTTPException) as exc_info:
        await count_router.close_count_session(
            session_id=uuid.uuid4(),
            user_with_scope=(uuid.uuid4(), _librarian_roles(), [_scope_assignment()]),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_approve_count_session_without_scope_raises(monkeypatch):
    async def _resolved_ids(*args, **kwargs):
        return set()

    monkeypatch.setattr(count_router, "resolve_school_scoped_warehouse_ids", _resolved_ids)

    class Svc:
        async def approve_session(self, *args, **kwargs):
            raise AssertionError("should not be called")

    req = _request_with_service(Svc())

    with pytest.raises(ScopeViolationError):
        await count_router.approve_count_session(
            session_id=uuid.uuid4(),
            body=CountApprovalRequest(notes="approve"),
            user_with_scope=(uuid.uuid4(), _librarian_roles(), [_scope_assignment()]),
            session=None,
            request=req,
        )


@pytest.mark.asyncio
async def test_approve_count_session_missing_session_maps_to_404(monkeypatch):
    warehouse_id = uuid.uuid4()

    async def _resolved_ids(*args, **kwargs):
        return {warehouse_id}

    monkeypatch.setattr(count_router, "resolve_school_scoped_warehouse_ids", _resolved_ids)

    class Repo:
        async def get_by_id(self, *args, **kwargs):
            return None

    svc = SimpleNamespace(_count_repo=Repo(), approve_session=None)
    req = _request_with_service(svc)

    with pytest.raises(HTTPException) as exc_info:
        await count_router.approve_count_session(
            session_id=uuid.uuid4(),
            body=CountApprovalRequest(notes="approve"),
            user_with_scope=(uuid.uuid4(), _librarian_roles(), [_scope_assignment()]),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_approve_count_session_permission_error_maps_to_403(monkeypatch):
    warehouse_id = uuid.uuid4()

    async def _resolved_ids(*args, **kwargs):
        return {warehouse_id}

    monkeypatch.setattr(count_router, "resolve_school_scoped_warehouse_ids", _resolved_ids)

    class Repo:
        async def get_by_id(self, *args, **kwargs):
            return _count_session_stub(warehouse_id)

    class Svc:
        _count_repo = Repo()

        async def approve_session(self, *args, **kwargs):
            raise InsufficientPermissionError("inventory.approve_count")

    req = _request_with_service(Svc())

    with pytest.raises(HTTPException) as exc_info:
        await count_router.approve_count_session(
            session_id=uuid.uuid4(),
            body=CountApprovalRequest(notes="approve"),
            user_with_scope=(uuid.uuid4(), _librarian_roles(), [_scope_assignment()]),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 403


def _scope_assignment():
    return SimpleNamespace(scope_type=ScopeType.SCHOOL, scope_ref_id=uuid.uuid4())
