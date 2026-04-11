"""
Unit tests for RbacService: permission checks and scope enforcement.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from district_console.application.rbac_service import RbacService
from district_console.domain.entities.role import Permission, Role
from district_console.domain.entities.user import ScopeAssignment
from district_console.domain.enums import RoleType, ScopeType
from district_console.domain.exceptions import (
    InsufficientPermissionError,
    ScopeViolationError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_permission(name: str) -> Permission:
    resource, action = name.split(".", 1)
    return Permission(id=uuid.uuid4(), name=name, resource_name=resource, action=action)


def make_role(role_type: RoleType, *permission_names: str) -> Role:
    perms = frozenset(make_permission(n) for n in permission_names)
    return Role(
        id=uuid.uuid4(),
        role_type=role_type,
        display_name=role_type.value.capitalize(),
        permissions=perms,
    )


def make_scope(scope_type: ScopeType, ref_id: uuid.UUID) -> ScopeAssignment:
    return ScopeAssignment(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        scope_type=scope_type,
        scope_ref_id=ref_id,
        granted_by=uuid.uuid4(),
        granted_at=datetime.utcnow(),
    )


# ---------------------------------------------------------------------------
# Permission checks
# ---------------------------------------------------------------------------

class TestPermissions:
    def test_has_permission_true_for_matching_role(self) -> None:
        svc = RbacService()
        roles = [make_role(RoleType.LIBRARIAN, "resources.publish")]
        assert svc.has_permission(roles, "resources.publish") is True

    def test_has_permission_false_when_not_granted(self) -> None:
        svc = RbacService()
        roles = [make_role(RoleType.TEACHER, "resources.read")]
        assert svc.has_permission(roles, "resources.publish") is False

    def test_has_permission_false_for_empty_roles(self) -> None:
        svc = RbacService()
        assert svc.has_permission([], "resources.publish") is False

    def test_check_permission_raises_insufficient_permission(self) -> None:
        svc = RbacService()
        roles = [make_role(RoleType.TEACHER, "resources.read")]
        with pytest.raises(InsufficientPermissionError) as exc_info:
            svc.check_permission(roles, "resources.publish")
        assert exc_info.value.code == "INSUFFICIENT_PERMISSION"
        assert exc_info.value.required_permission == "resources.publish"

    def test_check_permission_succeeds_without_raising(self) -> None:
        svc = RbacService()
        roles = [make_role(RoleType.LIBRARIAN, "resources.publish")]
        svc.check_permission(roles, "resources.publish")  # Should not raise


class TestAdministratorBypass:
    def test_administrator_bypasses_permission_check(self) -> None:
        svc = RbacService()
        # Admin role has no explicit permissions in this role object
        admin_role = make_role(RoleType.ADMINISTRATOR)
        # But has_permission should return True due to admin bypass
        assert svc.has_permission([admin_role], "any.permission") is True

    def test_administrator_check_permission_does_not_raise(self) -> None:
        svc = RbacService()
        admin_role = make_role(RoleType.ADMINISTRATOR)
        svc.check_permission([admin_role], "resources.delete")  # Should not raise

    def test_is_administrator_true_for_admin_role(self) -> None:
        svc = RbacService()
        admin_role = make_role(RoleType.ADMINISTRATOR)
        assert svc.is_administrator([admin_role]) is True

    def test_is_administrator_false_for_non_admin(self) -> None:
        svc = RbacService()
        roles = [make_role(RoleType.LIBRARIAN), make_role(RoleType.TEACHER)]
        assert svc.is_administrator(roles) is False


# ---------------------------------------------------------------------------
# Scope enforcement
# ---------------------------------------------------------------------------

class TestScopeEnforcement:
    def test_filter_by_scope_returns_only_assigned_ids(self) -> None:
        svc = RbacService()
        school_a = uuid.uuid4()
        school_b = uuid.uuid4()
        school_c = uuid.uuid4()
        scopes = [make_scope(ScopeType.SCHOOL, school_a)]
        result = svc.filter_by_scope(scopes, ScopeType.SCHOOL, [school_a, school_b, school_c])
        assert result == [school_a]

    def test_filter_by_scope_empty_for_no_assignments(self) -> None:
        svc = RbacService()
        school_id = uuid.uuid4()
        result = svc.filter_by_scope([], ScopeType.SCHOOL, [school_id])
        assert result == []

    def test_check_scope_raises_scope_violation(self) -> None:
        svc = RbacService()
        school_a = uuid.uuid4()
        school_b = uuid.uuid4()
        scopes = [make_scope(ScopeType.SCHOOL, school_a)]
        with pytest.raises(ScopeViolationError) as exc_info:
            svc.check_scope(scopes, ScopeType.SCHOOL, school_b)
        assert exc_info.value.code == "SCOPE_VIOLATION"

    def test_check_scope_succeeds_for_assigned_ref(self) -> None:
        svc = RbacService()
        school_id = uuid.uuid4()
        scopes = [make_scope(ScopeType.SCHOOL, school_id)]
        svc.check_scope(scopes, ScopeType.SCHOOL, school_id)  # Should not raise

    def test_administrator_bypasses_scope_check(self) -> None:
        """Administrator role_type bypass is in rbac_service.is_administrator,
        but scope check itself does not have admin bypass — that is done by
        the calling service after checking is_administrator(). This test
        confirms scope violation is raised when check_scope is called
        directly (bypassing admin logic intentionally)."""
        svc = RbacService()
        school_id = uuid.uuid4()
        other_school = uuid.uuid4()
        scopes = [make_scope(ScopeType.SCHOOL, school_id)]
        # Direct scope check raises even for an admin role if called directly
        with pytest.raises(ScopeViolationError):
            svc.check_scope(scopes, ScopeType.SCHOOL, other_school)
