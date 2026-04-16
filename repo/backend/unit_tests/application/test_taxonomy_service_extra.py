"""
Additional TaxonomyService tests covering uncovered branches:

  * create_category: parent not found / parent inactive
  * update_category: empty name + not found
  * deactivate_category: missing / success
  * list_all_categories / get_category / list_categories
  * save_validation_rule: empty field, empty rule_type, update path
  * delete_validation_rule success
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.auth_service import AuthService
from district_console.application.taxonomy_service import TaxonomyService
from district_console.domain.exceptions import DomainValidationError
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.orm import UserORM
from district_console.infrastructure.repositories import (
    AuditRepository,
    RoleRepository,
    TaxonomyRepository,
    UserRepository,
)


def _make_service() -> TaxonomyService:
    return TaxonomyService(TaxonomyRepository(), AuditWriter(AuditRepository()))


NOW = datetime(2024, 6, 1, 10, 0, 0)
ACTOR = uuid.uuid4()


@pytest.fixture(autouse=True)
async def _seed_actor(db_session: AsyncSession) -> None:
    auth = AuthService(UserRepository(), RoleRepository())
    now = datetime.utcnow().isoformat()
    db_session.add(
        UserORM(
            id=str(ACTOR),
            username="tax_extra_actor",
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
# Category tree — failure branches
# ---------------------------------------------------------------------------

async def test_create_category_parent_not_found_raises(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(DomainValidationError) as exc:
        await svc.create_category(
            db_session, "Child", actor_id=ACTOR, now=NOW, parent_id=uuid.uuid4()
        )
    assert exc.value.field == "parent_id"


async def test_create_category_parent_inactive_raises(db_session: AsyncSession):
    svc = _make_service()
    parent = await svc.create_category(db_session, "Parent", actor_id=ACTOR, now=NOW)
    await svc.deactivate_category(db_session, parent.id, ACTOR, NOW)
    with pytest.raises(DomainValidationError, match="inactive"):
        await svc.create_category(
            db_session, "Child", actor_id=ACTOR, now=NOW, parent_id=parent.id
        )


async def test_update_category_empty_name_raises(db_session: AsyncSession):
    svc = _make_service()
    cat = await svc.create_category(db_session, "Name", actor_id=ACTOR, now=NOW)
    with pytest.raises(DomainValidationError) as exc:
        await svc.update_category(db_session, cat.id, "   ", actor_id=ACTOR, now=NOW)
    assert exc.value.field == "name"


async def test_update_category_not_found_raises(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(DomainValidationError) as exc:
        await svc.update_category(db_session, uuid.uuid4(), "X", actor_id=ACTOR, now=NOW)
    assert exc.value.field == "category_id"


async def test_deactivate_missing_category_is_noop(db_session: AsyncSession):
    svc = _make_service()
    result = await svc.deactivate_category(db_session, uuid.uuid4(), ACTOR, NOW)
    assert result is None


async def test_deactivate_category_persists_inactive_flag(db_session: AsyncSession):
    svc = _make_service()
    cat = await svc.create_category(db_session, "To Deactivate", actor_id=ACTOR, now=NOW)
    await svc.deactivate_category(db_session, cat.id, ACTOR, NOW)
    stored = await svc.get_category(db_session, cat.id)
    assert stored is not None and stored.is_active is False


async def test_list_all_and_root_categories(db_session: AsyncSession):
    svc = _make_service()
    p = await svc.create_category(db_session, "Root", actor_id=ACTOR, now=NOW)
    c = await svc.create_category(
        db_session, "Child", actor_id=ACTOR, now=NOW, parent_id=p.id
    )

    all_cats = await svc.list_all_categories(db_session)
    assert {p.id, c.id}.issubset({x.id for x in all_cats})

    roots = await svc.list_categories(db_session, parent_id=None)
    assert any(x.id == p.id for x in roots)

    children = await svc.list_categories(db_session, parent_id=p.id)
    assert any(x.id == c.id for x in children)


# ---------------------------------------------------------------------------
# Validation rules — failure + update branches
# ---------------------------------------------------------------------------

async def test_save_validation_rule_empty_field_raises(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(DomainValidationError) as exc:
        await svc.save_validation_rule(
            db_session, field="   ", rule_type="regex", rule_value="x",
            actor_id=ACTOR, now=NOW,
        )
    assert exc.value.field == "field"


async def test_save_validation_rule_empty_rule_type_raises(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(DomainValidationError) as exc:
        await svc.save_validation_rule(
            db_session, field="keyword", rule_type="   ", rule_value="x",
            actor_id=ACTOR, now=NOW,
        )
    assert exc.value.field == "rule_type"


async def test_save_validation_rule_update_path(db_session: AsyncSession):
    svc = _make_service()
    created = await svc.save_validation_rule(
        db_session,
        field="keyword",
        rule_type="regex",
        rule_value="^[a-z]+$",
        actor_id=ACTOR,
        now=NOW,
    )
    updated = await svc.save_validation_rule(
        db_session,
        field="keyword",
        rule_type="regex",
        rule_value="^[A-Z]+$",
        actor_id=ACTOR,
        now=NOW,
        rule_id=created.id,
    )
    assert updated.id == created.id
    assert updated.rule_value == "^[A-Z]+$"


async def test_delete_validation_rule_removes_record(db_session: AsyncSession):
    svc = _make_service()
    rule = await svc.save_validation_rule(
        db_session, field="f", rule_type="regex", rule_value=".*",
        actor_id=ACTOR, now=NOW,
    )
    await svc.delete_validation_rule(db_session, rule.id, ACTOR, NOW)
    remaining = await svc.list_validation_rules(db_session, field="f")
    assert all(r.id != rule.id for r in remaining)
