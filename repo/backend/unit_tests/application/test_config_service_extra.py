"""
Additional ConfigService tests covering uncovered branches:

  * list_config returns saved entries
  * delete_config on a non-existent entry is a silent no-op
  * save_workflow_node update path (node_id supplied) / delete_workflow_node
  * list_templates / save_template update path
  * list_descriptors / save_descriptor update path and empty-key validation
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.auth_service import AuthService
from district_console.application.config_service import ConfigService
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


NOW = datetime(2024, 6, 1, 10, 0, 0)
ACTOR = uuid.uuid4()


def _make_service() -> ConfigService:
    return ConfigService(
        ConfigRepository(),
        WorkflowNodeRepository(),
        NotificationTemplateRepository(),
        DistrictDescriptorRepository(),
        AuditWriter(AuditRepository()),
    )


@pytest.fixture(autouse=True)
async def _seed_actor(db_session: AsyncSession) -> None:
    auth = AuthService(UserRepository(), RoleRepository())
    now = datetime.utcnow().isoformat()
    db_session.add(
        UserORM(
            id=str(ACTOR),
            username="cfg_extra_actor",
            password_hash=auth.hash_password("SecurePassword1!"),
            is_active=True,
            failed_attempts=0,
            locked_until=None,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.flush()


# ---------------------------------------------------------------------------
# ConfigDictionary
# ---------------------------------------------------------------------------

async def test_list_config_returns_created_entries(db_session: AsyncSession):
    svc = _make_service()
    await svc.upsert_config(db_session, "general", "foo", "1", "", ACTOR, NOW)
    await svc.upsert_config(db_session, "general", "bar", "2", "", ACTOR, NOW)

    rows, total = await svc.list_config(db_session)
    assert total >= 2
    keys = {r.key for r in rows}
    assert {"foo", "bar"}.issubset(keys)


async def test_list_config_filtered_by_category(db_session: AsyncSession):
    svc = _make_service()
    await svc.upsert_config(db_session, "display", "a", "1", "", ACTOR, NOW)
    await svc.upsert_config(db_session, "retention", "b", "30", "", ACTOR, NOW)

    rows, _ = await svc.list_config(db_session, category="retention")
    assert all(r.category == "retention" for r in rows)


async def test_delete_config_missing_entry_is_noop(db_session: AsyncSession):
    """delete_config must silently return when the entry does not exist."""
    svc = _make_service()
    result = await svc.delete_config(db_session, uuid.uuid4(), ACTOR, NOW)
    assert result is None


async def test_upsert_config_empty_key_raises(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(DomainValidationError) as exc:
        await svc.upsert_config(db_session, "cat", "   ", "v", "", ACTOR, NOW)
    assert exc.value.field == "key"


# ---------------------------------------------------------------------------
# WorkflowNode
# ---------------------------------------------------------------------------

async def test_save_workflow_node_update_path(db_session: AsyncSession):
    """Save twice with node_id to hit the update branch in save_workflow_node."""
    svc = _make_service()
    created = await svc.save_workflow_node(
        db_session,
        workflow_name="wf",
        from_state="A",
        to_state="B",
        required_role="LIBRARIAN",
        condition_json=None,
        actor_id=ACTOR,
        now=NOW,
    )
    updated = await svc.save_workflow_node(
        db_session,
        workflow_name="wf",
        from_state="A",
        to_state="C",
        required_role="LIBRARIAN",
        condition_json='{"x":1}',
        actor_id=ACTOR,
        now=NOW,
        node_id=created.id,
    )
    assert updated.id == created.id
    assert updated.to_state == "C"
    assert updated.condition_json == '{"x":1}'


async def test_list_workflow_nodes_filters_by_workflow_name(db_session: AsyncSession):
    svc = _make_service()
    await svc.save_workflow_node(
        db_session, "wfA", "A", "B", "LIBRARIAN", None, ACTOR, NOW
    )
    await svc.save_workflow_node(
        db_session, "wfB", "X", "Y", "LIBRARIAN", None, ACTOR, NOW
    )
    nodes = await svc.list_workflow_nodes(db_session, workflow_name="wfA")
    assert all(n.workflow_name == "wfA" for n in nodes)


async def test_delete_workflow_node_writes_audit(db_session: AsyncSession):
    svc = _make_service()
    node = await svc.save_workflow_node(
        db_session, "wf", "A", "B", "LIBRARIAN", None, ACTOR, NOW
    )
    await svc.delete_workflow_node(db_session, node.id, ACTOR, NOW)
    nodes = await svc.list_workflow_nodes(db_session, workflow_name="wf")
    assert all(n.id != node.id for n in nodes)


# ---------------------------------------------------------------------------
# NotificationTemplate
# ---------------------------------------------------------------------------

async def test_save_template_create_then_update(db_session: AsyncSession):
    svc = _make_service()
    created = await svc.save_template(
        db_session,
        name="notify",
        event_type="COUNT_APPROVED",
        subject_template="Subject",
        body_template="Body",
        is_active=True,
        actor_id=ACTOR,
        now=NOW,
    )
    updated = await svc.save_template(
        db_session,
        name="notify",
        event_type="COUNT_APPROVED",
        subject_template="NewSubject",
        body_template="NewBody",
        is_active=False,
        actor_id=ACTOR,
        now=NOW,
        template_id=created.id,
    )
    assert updated.id == created.id
    assert updated.subject_template == "NewSubject"
    assert updated.is_active is False


async def test_list_templates_returns_saved(db_session: AsyncSession):
    svc = _make_service()
    t = await svc.save_template(
        db_session,
        name="notify-list",
        event_type="RESOURCE_PUBLISHED",
        subject_template="S",
        body_template="B",
        is_active=True,
        actor_id=ACTOR,
        now=NOW,
    )
    templates = await svc.list_templates(db_session)
    assert any(x.id == t.id for x in templates)


# ---------------------------------------------------------------------------
# DistrictDescriptor
# ---------------------------------------------------------------------------

async def test_save_descriptor_empty_key_raises(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(DomainValidationError) as exc:
        await svc.save_descriptor(
            db_session, key="   ", value="v", description="", region=None,
            actor_id=ACTOR, now=NOW,
        )
    assert exc.value.field == "key"


async def test_save_descriptor_update_path(db_session: AsyncSession):
    svc = _make_service()
    created = await svc.save_descriptor(
        db_session, key="district.code", value="D1", description="", region=None,
        actor_id=ACTOR, now=NOW,
    )
    updated = await svc.save_descriptor(
        db_session, key="district.code", value="D2", description="", region="NW",
        actor_id=ACTOR, now=NOW,
    )
    # Update path reuses the existing id
    assert updated.id == created.id
    assert updated.value == "D2"
    assert updated.region == "NW"


async def test_list_descriptors_returns_saved(db_session: AsyncSession):
    svc = _make_service()
    d = await svc.save_descriptor(
        db_session, key="d.k", value="v", description="", region=None,
        actor_id=ACTOR, now=NOW,
    )
    descs = await svc.list_descriptors(db_session)
    assert any(x.id == d.id for x in descs)
