"""
Unit tests for ConfigService — config dictionary, workflow nodes, and descriptors.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.config_service import ConfigService, SystemEntryProtectedError
from district_console.application.auth_service import AuthService
from district_console.domain.exceptions import DomainValidationError
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.orm import UserORM
from district_console.infrastructure.repositories import (
    AuditRepository,
    ConfigRepository,
    DistrictDescriptorRepository,
    NotificationTemplateRepository,
    RoleRepository,
    UserRepository,
    WorkflowNodeRepository,
)


def _make_service():
    audit_writer = AuditWriter(AuditRepository())
    return ConfigService(
        ConfigRepository(),
        WorkflowNodeRepository(),
        NotificationTemplateRepository(),
        DistrictDescriptorRepository(),
        audit_writer,
    )


NOW = datetime(2024, 6, 1, 10, 0, 0)
ACTOR = uuid.uuid4()


@pytest.fixture(autouse=True)
async def _seed_actor_user(db_session: AsyncSession) -> None:
    auth = AuthService(UserRepository(), RoleRepository())
    now = datetime.utcnow().isoformat()
    db_session.add(
        UserORM(
            id=str(ACTOR),
            username="config_actor",
            password_hash=auth.hash_password("SecurePassword1!"),
            is_active=True,
            failed_attempts=0,
            locked_until=None,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.flush()


async def test_upsert_config_creates_new_entry(db_session: AsyncSession):
    svc = _make_service()
    entry = await svc.upsert_config(
        db_session,
        category="display",
        key="page_size",
        value="25",
        description="Items per page",
        actor_id=ACTOR,
        now=NOW,
    )
    assert entry.category == "display"
    assert entry.key == "page_size"
    assert entry.value == "25"
    assert entry.is_system is False


async def test_upsert_config_updates_existing_entry(db_session: AsyncSession):
    svc = _make_service()
    await svc.upsert_config(db_session, "display", "page_size", "25", "", ACTOR, NOW)
    updated = await svc.upsert_config(db_session, "display", "page_size", "50", "Updated", ACTOR, NOW)
    assert updated.value == "50"


async def test_upsert_config_empty_category_raises(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(DomainValidationError) as exc_info:
        await svc.upsert_config(db_session, "   ", "key", "val", "", ACTOR, NOW)
    assert exc_info.value.field == "category"


async def test_upsert_config_empty_value_raises(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(DomainValidationError) as exc_info:
        await svc.upsert_config(db_session, "cat", "key", "   ", "", ACTOR, NOW)
    assert exc_info.value.field == "value"


async def test_delete_config_removes_entry(db_session: AsyncSession):
    svc = _make_service()
    entry = await svc.upsert_config(db_session, "general", "timeout", "300", "", ACTOR, NOW)
    await svc.delete_config(db_session, entry.id, ACTOR, NOW)
    result = await svc.get_config(db_session, "general", "timeout")
    assert result is None


async def test_delete_system_entry_raises(db_session: AsyncSession):
    svc = _make_service()
    # Insert a system entry directly via repo
    from district_console.domain.entities.config import ConfigDictionary
    repo = ConfigRepository()
    sys_entry = ConfigDictionary(
        id=uuid.uuid4(),
        category="system",
        key="version",
        value="1.0",
        description="System version",
        is_system=True,
        updated_by=ACTOR,
        updated_at=NOW,
    )
    sys_entry = await repo.save(db_session, sys_entry)
    with pytest.raises(SystemEntryProtectedError):
        await svc.delete_config(db_session, sys_entry.id, ACTOR, NOW)


async def test_save_workflow_node_persists(db_session: AsyncSession):
    svc = _make_service()
    node = await svc.save_workflow_node(
        db_session,
        workflow_name="resource_review",
        from_state="DRAFT",
        to_state="IN_REVIEW",
        required_role="LIBRARIAN",
        condition_json=None,
        actor_id=ACTOR,
        now=NOW,
    )
    assert node.workflow_name == "resource_review"
    assert node.from_state == "DRAFT"


async def test_save_descriptor_persists(db_session: AsyncSession):
    svc = _make_service()
    desc = await svc.save_descriptor(
        db_session,
        key="district.name",
        value="Springfield USD",
        description="District name",
        region=None,
        actor_id=ACTOR,
        now=NOW,
    )
    assert desc.key == "district.name"
    assert desc.value == "Springfield USD"
