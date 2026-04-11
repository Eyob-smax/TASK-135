"""
Unit tests for TaxonomyService — category tree and validation rules.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.taxonomy_service import TaxonomyService
from district_console.application.auth_service import AuthService
from district_console.domain.exceptions import DomainValidationError
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.orm import UserORM
from district_console.infrastructure.repositories import AuditRepository, TaxonomyRepository
from district_console.infrastructure.repositories import RoleRepository, UserRepository


def _make_service():
    return TaxonomyService(TaxonomyRepository(), AuditWriter(AuditRepository()))


NOW = datetime(2024, 6, 1, 10, 0, 0)
ACTOR = uuid.uuid4()


@pytest.fixture(autouse=True)
async def _seed_actor_user(db_session: AsyncSession) -> None:
    auth = AuthService(UserRepository(), RoleRepository())
    now = datetime.utcnow().isoformat()
    db_session.add(
        UserORM(
            id=str(ACTOR),
            username="taxonomy_actor",
            password_hash=auth.hash_password("SecurePassword1!"),
            is_active=True,
            failed_attempts=0,
            locked_until=None,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.flush()


async def test_create_root_category(db_session: AsyncSession):
    svc = _make_service()
    cat = await svc.create_category(db_session, name="Fiction", actor_id=ACTOR, now=NOW)
    assert cat.name == "Fiction"
    assert cat.depth == 0
    assert cat.path_slug == "fiction"
    assert cat.parent_id is None
    assert cat.is_active is True


async def test_create_child_category_has_correct_depth_and_slug(db_session: AsyncSession):
    svc = _make_service()
    parent = await svc.create_category(db_session, "Science", actor_id=ACTOR, now=NOW)
    child = await svc.create_category(
        db_session, "Physics", actor_id=ACTOR, now=NOW, parent_id=parent.id
    )
    assert child.depth == 1
    assert child.path_slug == "science/physics"
    assert child.parent_id == parent.id


async def test_create_category_empty_name_raises(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(DomainValidationError) as exc_info:
        await svc.create_category(db_session, name="   ", actor_id=ACTOR, now=NOW)
    assert exc_info.value.field == "name"


async def test_create_category_duplicate_slug_gets_suffix(db_session: AsyncSession):
    svc = _make_service()
    cat1 = await svc.create_category(db_session, "History", actor_id=ACTOR, now=NOW)
    cat2 = await svc.create_category(db_session, "History", actor_id=ACTOR, now=NOW)
    assert cat1.path_slug != cat2.path_slug
    assert cat2.path_slug.startswith("history-")


async def test_update_category_recomputes_slug(db_session: AsyncSession):
    svc = _make_service()
    cat = await svc.create_category(db_session, "Old Name", actor_id=ACTOR, now=NOW)
    updated = await svc.update_category(db_session, cat.id, "New Name", actor_id=ACTOR, now=NOW)
    assert updated.name == "New Name"
    assert "new-name" in updated.path_slug


async def test_save_and_list_validation_rules(db_session: AsyncSession):
    svc = _make_service()
    rule = await svc.save_validation_rule(
        db_session,
        field="copyright",
        rule_type="allowed_values",
        rule_value="CC-BY,CC-BY-SA,Public Domain",
        actor_id=ACTOR,
        now=NOW,
        description="Copyright options",
    )
    assert rule.field == "copyright"
    assert rule.rule_type == "allowed_values"

    rules = await svc.list_validation_rules(db_session, field="copyright")
    assert len(rules) == 1
    assert rules[0].rule_value == "CC-BY,CC-BY-SA,Public Domain"
