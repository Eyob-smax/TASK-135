"""
Role and Permission domain entities.

Permissions are named capabilities (e.g. "resources.publish") scoped to a
resource name and action. Roles aggregate a set of permissions and are
assigned to users via UserRole.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from district_console.domain.enums import RoleType


@dataclass(frozen=True)
class Permission:
    """
    A named capability that controls access to a specific resource action.

    Examples:
        Permission(id=..., name="resources.publish", resource_name="resources", action="publish")
        Permission(id=..., name="inventory.freeze", resource_name="inventory", action="freeze")
        Permission(id=..., name="admin.manage_users", resource_name="admin", action="manage_users")
    """
    id: uuid.UUID
    name: str          # Dot-separated: "<resource>.<action>"
    resource_name: str
    action: str


@dataclass(frozen=True)
class Role:
    """
    A named role with a fixed set of permissions.

    The five system roles (Administrator, Librarian, Teacher, Counselor,
    Reviewer) are seeded on first run. Custom roles may be added by
    Administrators if supported by future configuration.
    """
    id: uuid.UUID
    role_type: RoleType
    display_name: str
    permissions: frozenset[Permission] = field(default_factory=frozenset)

    def has_permission(self, permission_name: str) -> bool:
        """Return True if this role includes the named permission."""
        return any(p.name == permission_name for p in self.permissions)
