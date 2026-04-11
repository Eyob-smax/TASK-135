"""
Application-wide session state shared across all UI components.

Holds the authenticated user's token, identity, roles, and computed permissions.
This module is pure Python — no PyQt imports — so it can be used in tests
without a QApplication instance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Role → permission mapping derived from reference_data.sql seeded permissions.
# This is UI-only visibility logic; all real enforcement happens server-side.
_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "ADMINISTRATOR": frozenset({"*"}),
    "LIBRARIAN": frozenset({
        "resources.view", "resources.create", "resources.edit",
        "resources.import", "resources.submit_review",
        "inventory.view", "inventory.adjust", "inventory.freeze",
        "inventory.count", "inventory.relocate",
    }),
    "REVIEWER": frozenset({
        "resources.view", "resources.publish",
        "inventory.approve_count",
    }),
    "TEACHER": frozenset({
        "resources.view",
    }),
    "COUNSELOR": frozenset({
        "resources.view", "resources.classify",
    }),
}


@dataclass
class AppState:
    """
    Mutable session state for the desktop application.

    Created once and passed by reference to every UI component.
    Cleared on logout; repopulated after successful sign-in.
    """
    token: Optional[str] = None
    user_id: Optional[str] = None
    username: Optional[str] = None
    roles: list[str] = field(default_factory=list)
    expires_at: Optional[str] = None

    # Count of in-flight background workers; used for safe-shutdown checks
    active_workers: int = 0

    # Whether minimize goes to tray (default True on Windows)
    tray_mode: bool = True

    # IDs of active checkpoints discovered at startup (job_type → job_id)
    pending_checkpoints: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Computed helpers                                                     #
    # ------------------------------------------------------------------ #

    def set_session(self, token: str, user_id: str, username: str,
                    roles: list[str], expires_at: str) -> None:
        """Populate state after a successful login response."""
        self.token = token
        self.user_id = user_id
        self.username = username
        self.roles = list(roles)
        self.expires_at = expires_at

    def clear(self) -> None:
        """Reset to unauthenticated state."""
        self.token = None
        self.user_id = None
        self.username = None
        self.roles = []
        self.expires_at = None
        self.active_workers = 0

    def is_authenticated(self) -> bool:
        return self.token is not None

    def has_permission(self, permission: str) -> bool:
        """
        Return True if the current user holds the given permission.

        ADMINISTRATOR bypasses all checks. The '*' wildcard in the permission
        set is the sentinel for that bypass.
        """
        for role in self.roles:
            perms = _ROLE_PERMISSIONS.get(role, frozenset())
            if "*" in perms or permission in perms:
                return True
        return False

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def is_administrator(self) -> bool:
        return "ADMINISTRATOR" in self.roles

    def has_resumable_work(self) -> bool:
        """True when background workers are running or checkpoints need review."""
        return self.active_workers > 0 or bool(self.pending_checkpoints)

    def auth_header(self) -> dict[str, str]:
        """Return the Authorization header dict for REST calls."""
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}
