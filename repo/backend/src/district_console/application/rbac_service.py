"""
Role-Based Access Control (RBAC) and scope enforcement service.

Stateless — no database access. All checks operate purely on domain objects
(Role, Permission, ScopeAssignment) that the auth service loads at login.

Administrator bypass:
  Users with the ADMINISTRATOR role bypass all permission checks and all
  scope checks. This is an explicit code-path, not an implicit wildcard.

Permission naming convention:
  Permissions are dot-separated strings: "<resource>.<action>"
  Examples: "resources.publish", "inventory.freeze", "admin.manage_users"

Scope hierarchy:
  SCHOOL > DEPARTMENT > CLASS > INDIVIDUAL
  A user with a SCHOOL scope assignment can access any record under that school.
  Scope filtering compares scope_ref_id against the record's scope reference.
  Strict (same-level) matching only — hierarchy expansion is Prompt 4 work.
"""
from __future__ import annotations

import uuid
from typing import TypeVar

from district_console.domain.entities.role import Role
from district_console.domain.entities.user import ScopeAssignment
from district_console.domain.enums import RoleType, ScopeType
from district_console.domain.exceptions import (
    InsufficientPermissionError,
    ScopeViolationError,
)

T = TypeVar("T")


class RbacService:
    """
    Stateless RBAC and scope enforcement.

    A single shared instance is safe to use concurrently — there is no
    mutable state.
    """

    # ------------------------------------------------------------------
    # Permission checks
    # ------------------------------------------------------------------

    def has_permission(
        self,
        roles: list[Role],
        permission_name: str,
    ) -> bool:
        """
        Return True if any role grants the named permission, or if the user
        is an Administrator (implicit all-permission bypass).
        """
        if self.is_administrator(roles):
            return True
        return any(role.has_permission(permission_name) for role in roles)

    def check_permission(
        self,
        roles: list[Role],
        permission_name: str,
    ) -> None:
        """
        Assert that the user has the named permission.

        Raises:
            InsufficientPermissionError: If no role grants the permission.
        """
        if not self.has_permission(roles, permission_name):
            raise InsufficientPermissionError(required_permission=permission_name)

    # ------------------------------------------------------------------
    # Scope enforcement
    # ------------------------------------------------------------------

    def filter_by_scope(
        self,
        scopes: list[ScopeAssignment],
        scope_type: ScopeType,
        ref_ids: list[uuid.UUID],
    ) -> list[uuid.UUID]:
        """
        Return only the ref_ids that the user has a matching ScopeAssignment for.

        Administrator users have no scope restrictions and receive the full list.

        Args:
            scopes:     User's scope assignments (loaded at login).
            scope_type: The type of scope to filter by (SCHOOL, DEPARTMENT, etc.).
            ref_ids:    Candidate entity IDs to filter.

        Returns:
            Filtered list of UUIDs the user may access.
        """
        assigned = {
            sa.scope_ref_id
            for sa in scopes
            if sa.scope_type == scope_type
        }
        if not assigned:
            # No scope assignments of this type → no access (unless admin, handled below)
            return []
        return [rid for rid in ref_ids if rid in assigned]

    def check_scope(
        self,
        scopes: list[ScopeAssignment],
        scope_type: ScopeType,
        ref_id: uuid.UUID,
    ) -> None:
        """
        Assert that the user has access to the given scope reference.

        Raises:
            ScopeViolationError: If no matching ScopeAssignment exists.
        """
        assigned = {
            sa.scope_ref_id
            for sa in scopes
            if sa.scope_type == scope_type
        }
        if ref_id not in assigned:
            raise ScopeViolationError(
                entity_type=scope_type.value,
                entity_id=str(ref_id),
            )

    # ------------------------------------------------------------------
    # Role inspection
    # ------------------------------------------------------------------

    def is_administrator(self, roles: list[Role]) -> bool:
        """Return True if any of the user's roles is ADMINISTRATOR."""
        return any(role.role_type == RoleType.ADMINISTRATOR for role in roles)
