from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from district_console.api.routers import auth as auth_router
from district_console.api.routers.admin import config as admin_config_router
from district_console.api.routers.admin import updates as admin_updates_router
from district_console.api.routers import inventory as inventory_router
from district_console.api.routers import resources as resources_router
from district_console.api.schemas import (
    DistrictDescriptorUpsert,
    FreezeRequest,
    LoginRequest,
    NotificationTemplateUpsert,
)
from district_console.application.config_service import SystemEntryProtectedError
from district_console.application.update_service import ManifestValidationError, RollbackError
from district_console.domain.entities.role import Permission, Role
from district_console.domain.enums import ResourceStatus, ResourceType, RoleType, ScopeType
from district_console.domain.exceptions import ResourceNotFoundError, ScopeViolationError, SessionExpiredError


class _UploadStub:
    def __init__(self, content: bytes, filename: str = "pkg.zip"):
        self._content = content
        self.filename = filename

    async def read(self) -> bytes:
        return self._content


def _admin_roles() -> list[Role]:
    return [Role(id=uuid.uuid4(), role_type=RoleType.ADMINISTRATOR, display_name="Admin")]


def _reviewer_roles() -> list[Role]:
    perms = frozenset({Permission(uuid.uuid4(), "resources.view", "resources", "view")})
    return [Role(id=uuid.uuid4(), role_type=RoleType.REVIEWER, display_name="Reviewer", permissions=perms)]


def _resource_stub(scope_type: str | None, scope_ref_id: str | None):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid.uuid4(),
        title="Scoped Resource",
        resource_type=ResourceType.BOOK,
        status=ResourceStatus.DRAFT,
        file_fingerprint="f",
        isbn=None,
        dedup_key="k",
        created_by=uuid.uuid4(),
        created_at=now,
        updated_at=now,
        owner_scope_type=scope_type,
        owner_scope_ref_id=scope_ref_id,
    )


@pytest.mark.asyncio
async def test_delete_config_system_entry_maps_to_403():
    class Svc:
        async def delete_config(self, *args, **kwargs):
            raise SystemEntryProtectedError("System entry is protected")

    with pytest.raises(HTTPException) as exc_info:
        await admin_config_router.delete_config(
            entry_id=str(uuid.uuid4()),
            current_user=(uuid.uuid4(), _admin_roles()),
            session=None,
            svc=Svc(),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "INSUFFICIENT_PERMISSION"


@pytest.mark.asyncio
async def test_upsert_template_direct_route_executes_unreachable_branch():
    template = SimpleNamespace(
        id=uuid.uuid4(),
        name="approval_email",
        event_type="RESOURCE_PUBLISHED",
        subject_template="Subject",
        body_template="Body",
        is_active=True,
    )

    class Svc:
        async def save_template(self, *args, **kwargs):
            return template

    response = await admin_config_router.upsert_template(
        name="approval_email",
        body=NotificationTemplateUpsert(
            name="approval_email",
            event_type="RESOURCE_PUBLISHED",
            subject_template="Subject",
            body_template="Body",
            is_active=True,
        ),
        current_user=(uuid.uuid4(), _admin_roles()),
        session=None,
        svc=Svc(),
    )

    assert response.name == "approval_email"
    assert response.event_type == "RESOURCE_PUBLISHED"


@pytest.mark.asyncio
async def test_upsert_descriptor_direct_route_executes_unreachable_branch():
    descriptor = SimpleNamespace(
        id=uuid.uuid4(),
        key="district_name",
        value="Demo District",
        description="Display label",
        region="US",
    )

    class Svc:
        async def save_descriptor(self, *args, **kwargs):
            return descriptor

    response = await admin_config_router.upsert_descriptor(
        key="district_name",
        body=DistrictDescriptorUpsert(
            value="Demo District",
            description="Display label",
            region="US",
        ),
        current_user=(uuid.uuid4(), _admin_roles()),
        session=None,
        svc=Svc(),
    )

    assert response.key == "district_name"
    assert response.value == "Demo District"


@pytest.mark.asyncio
async def test_updates_import_manifest_error_maps_to_422():
    class Svc:
        async def import_package(self, *args, **kwargs):
            raise ManifestValidationError("bad manifest")

    with pytest.raises(HTTPException) as exc_info:
        await admin_updates_router.import_package(
            file=_UploadStub(b"not-a-zip"),
            current_user=(uuid.uuid4(), _admin_roles()),
            session=None,
            svc=Svc(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "INVALID_MANIFEST"


@pytest.mark.asyncio
async def test_updates_rollback_error_maps_to_409():
    class Svc:
        async def rollback_package(self, *args, **kwargs):
            raise RollbackError("No prior version")

    with pytest.raises(HTTPException) as exc_info:
        await admin_updates_router.rollback_package(
            package_id=str(uuid.uuid4()),
            current_user=(uuid.uuid4(), _admin_roles()),
            session=None,
            svc=Svc(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "ROLLBACK_NOT_POSSIBLE"


@pytest.mark.asyncio
async def test_login_returns_role_values_from_auth_service():
    user = SimpleNamespace(id=uuid.uuid4(), username="alice")
    roles = [Role(id=uuid.uuid4(), role_type=RoleType.REVIEWER, display_name="Reviewer")]

    class AuthSvc:
        async def authenticate(self, *args, **kwargs):
            return user, roles

        def create_session(self, user_id, role_list):
            assert user_id == user.id
            assert role_list == roles
            return "tok-123"

    response = await auth_router.login(
        body=LoginRequest(username="alice", password="SecurePassword1!"),
        session=None,
        auth_service=AuthSvc(),
    )

    assert response.username == "alice"
    assert response.roles == ["REVIEWER"]
    assert response.token == "tok-123"


@pytest.mark.asyncio
async def test_logout_without_bearer_raises_session_expired():
    request = SimpleNamespace(headers={})

    class AuthSvc:
        def validate_session(self, *args, **kwargs):
            return None

        def invalidate_session(self, *args, **kwargs):
            return None

    with pytest.raises(SessionExpiredError):
        await auth_router.logout(request=request, auth_service=AuthSvc())


@pytest.mark.asyncio
async def test_logout_with_invalid_token_raises_session_expired():
    request = SimpleNamespace(headers={"Authorization": "Bearer invalid-token"})

    class AuthSvc:
        def validate_session(self, *args, **kwargs):
            return None

        def invalidate_session(self, *args, **kwargs):
            return None

    with pytest.raises(SessionExpiredError):
        await auth_router.logout(request=request, auth_service=AuthSvc())


@pytest.mark.asyncio
async def test_whoami_when_user_missing_returns_empty_username(monkeypatch):
    async def _get_by_id(self, session, user_id):
        return None

    async def _get_scopes(self, session, user_id):
        return []

    monkeypatch.setattr(auth_router.UserRepository, "get_by_id", _get_by_id)
    monkeypatch.setattr(auth_router.ScopeRepository, "get_user_scopes", _get_scopes)

    user_id = uuid.uuid4()
    response = await auth_router.whoami(
        current_user=(user_id, _admin_roles()),
        session=None,
    )

    assert response.user_id == str(user_id)
    assert response.username == ""


@pytest.mark.asyncio
async def test_resource_get_outside_scope_raises_scope_violation():
    scoped_ref = str(uuid.uuid4())

    class Svc:
        async def get_resource(self, *args, **kwargs):
            return _resource_stub(scope_type=ScopeType.SCHOOL.value, scope_ref_id=scoped_ref)

        async def get_resource_metadata(self, *args, **kwargs):
            return None

    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=SimpleNamespace(resource_service=Svc()))))
    user_scope_ref = uuid.uuid4()

    with pytest.raises(ScopeViolationError):
        await resources_router.get_resource(
            resource_id=uuid.uuid4(),
            user_with_scope=(
                uuid.uuid4(),
                _reviewer_roles(),
                [SimpleNamespace(scope_type=ScopeType.SCHOOL, scope_ref_id=user_scope_ref)],
            ),
            session=None,
            request=req,
        )


@pytest.mark.asyncio
async def test_delete_workflow_node_direct_executes_route():
    called = {"value": False}

    class Svc:
        async def delete_workflow_node(self, *args, **kwargs):
            called["value"] = True

    await admin_config_router.delete_workflow_node(
        node_id=str(uuid.uuid4()),
        current_user=(uuid.uuid4(), _admin_roles()),
        session=None,
        svc=Svc(),
    )
    assert called["value"] is True


@pytest.mark.asyncio
async def test_resource_publish_not_found_maps_to_404():
    class Svc:
        async def get_resource(self, *args, **kwargs):
            raise ResourceNotFoundError("missing")

    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=SimpleNamespace(resource_service=Svc()))))

    from district_console.api.schemas import PublishRequest

    with pytest.raises(HTTPException) as exc_info:
        await resources_router.publish_resource(
            resource_id=uuid.uuid4(),
            body=PublishRequest(reviewer_notes="ok"),
            user_with_scope=(uuid.uuid4(), _admin_roles(), []),
            session=None,
            request=req,
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_inventory_freeze_without_resolved_scope_raises_scope_violation(monkeypatch):
    async def _resolved_ids(*args, **kwargs):
        return set()

    monkeypatch.setattr(inventory_router, "resolve_school_scoped_location_ids", _resolved_ids)

    svc = SimpleNamespace(
        _inventory_repo=SimpleNamespace(get_stock_balance_by_id=lambda *args, **kwargs: None)
    )
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=SimpleNamespace(inventory_service=svc))))

    with pytest.raises(ScopeViolationError):
        await inventory_router.freeze_stock(
            balance_id=uuid.uuid4(),
            body=FreezeRequest(reason="audit"),
            user_with_scope=(uuid.uuid4(), [Role(uuid.uuid4(), RoleType.LIBRARIAN, "Librarian")], [SimpleNamespace(scope_type=ScopeType.SCHOOL, scope_ref_id=uuid.uuid4())]),
            session=None,
            request=req,
        )
