"""Basic repository-level unit coverage for infrastructure.repositories."""
from __future__ import annotations

import uuid
from datetime import datetime

from district_console.domain.entities.user import User
from district_console.domain.enums import ScopeType
from district_console.infrastructure.orm import ScopeAssignmentORM, UserRoleORM
from district_console.infrastructure.repositories import RoleRepository, ScopeRepository, UserRepository


async def test_user_repository_save_and_get_by_username(db_session):
    repo = UserRepository()
    user = User(
        id=uuid.uuid4(),
        username="repo_user",
        password_hash="hash",
        is_active=True,
        failed_attempts=0,
        locked_until=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    await repo.save(db_session, user)

    loaded = await repo.get_by_username(db_session, "repo_user")
    assert loaded is not None
    assert loaded.id == user.id
    assert loaded.username == "repo_user"


async def test_scope_repository_returns_user_scopes(db_session, seeded_user_orm):
    granted_by = seeded_user_orm.id
    user_id = seeded_user_orm.id
    assignment_id = str(uuid.uuid4())
    scope_ref_id = str(uuid.uuid4())

    db_session.add(
        ScopeAssignmentORM(
            id=assignment_id,
            user_id=user_id,
            scope_type="SCHOOL",
            scope_ref_id=scope_ref_id,
            granted_by=granted_by,
            granted_at=datetime.utcnow().isoformat(),
        )
    )
    await db_session.flush()

    repo = ScopeRepository()
    scopes = await repo.get_user_scopes(db_session, uuid.UUID(user_id))

    assert len(scopes) >= 1
    assert any(s.scope_type == ScopeType.SCHOOL and str(s.scope_ref_id) == scope_ref_id for s in scopes)


async def test_role_repository_returns_permissions_for_user(db_session, seeded_user_orm, seeded_roles):
    db_session.add(
        UserRoleORM(
            user_id=seeded_user_orm.id,
            role_id=seeded_roles["LIBRARIAN"].id,
            assigned_by=seeded_user_orm.id,
            assigned_at=datetime.utcnow().isoformat(),
        )
    )
    await db_session.flush()

    roles = await RoleRepository().get_roles_for_user(db_session, uuid.UUID(seeded_user_orm.id))

    assert len(roles) >= 1
    librarian = next((r for r in roles if r.role_type.value == "LIBRARIAN"), None)
    assert librarian is not None
    perm_names = {p.name for p in librarian.permissions}
    assert "resources.view" in perm_names
    assert "inventory.adjust" in perm_names
