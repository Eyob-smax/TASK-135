"""
Tests for role-based menu and action visibility in the shell and screens.

Verifies that:
- ADMINISTRATOR sees all navigation entries
- TEACHER does not see inventory.adjust / count session / approval actions
- REVIEWER sees publish actions but not adjust actions
- COUNSELOR sees classify but not freeze or count
"""
from __future__ import annotations

import pytest

from district_console.ui.state import AppState


@pytest.fixture
def state_admin():
    s = AppState()
    s.set_session("tok", "uid", "admin", ["ADMINISTRATOR"], "2026-04-10T20:00:00")
    return s


@pytest.fixture
def state_teacher():
    s = AppState()
    s.set_session("tok", "uid", "teacher", ["TEACHER"], "2026-04-10T20:00:00")
    return s


@pytest.fixture
def state_reviewer():
    s = AppState()
    s.set_session("tok", "uid", "reviewer", ["REVIEWER"], "2026-04-10T20:00:00")
    return s


@pytest.fixture
def state_counselor():
    s = AppState()
    s.set_session("tok", "uid", "counselor", ["COUNSELOR"], "2026-04-10T20:00:00")
    return s


@pytest.fixture
def state_librarian():
    s = AppState()
    s.set_session("tok", "uid", "librarian", ["LIBRARIAN"], "2026-04-10T20:00:00")
    return s


class TestAdminPermissions:
    def test_admin_has_all_permissions(self, state_admin):
        for perm in [
            "resources.view", "resources.create", "resources.publish",
            "inventory.view", "inventory.adjust", "inventory.freeze",
            "inventory.count", "inventory.relocate", "inventory.approve_count",
            "admin.manage_config",
        ]:
            assert state_admin.has_permission(perm), f"Admin missing: {perm}"

    def test_admin_is_administrator(self, state_admin):
        assert state_admin.is_administrator()


class TestTeacherPermissions:
    def test_teacher_has_resources_view(self, state_teacher):
        assert state_teacher.has_permission("resources.view")

    def test_teacher_has_inventory_view(self, state_teacher):
        assert state_teacher.has_permission("inventory.view")

    def test_teacher_cannot_adjust_inventory(self, state_teacher):
        assert not state_teacher.has_permission("inventory.adjust")

    def test_teacher_cannot_count(self, state_teacher):
        assert not state_teacher.has_permission("inventory.count")

    def test_teacher_cannot_publish(self, state_teacher):
        assert not state_teacher.has_permission("resources.publish")

    def test_teacher_cannot_freeze(self, state_teacher):
        assert not state_teacher.has_permission("inventory.freeze")

    def test_teacher_is_not_administrator(self, state_teacher):
        assert not state_teacher.is_administrator()


class TestReviewerPermissions:
    def test_reviewer_can_publish(self, state_reviewer):
        assert state_reviewer.has_permission("resources.publish")

    def test_reviewer_can_view_resources(self, state_reviewer):
        assert state_reviewer.has_permission("resources.view")

    def test_reviewer_cannot_adjust_inventory(self, state_reviewer):
        assert not state_reviewer.has_permission("inventory.adjust")

    def test_reviewer_cannot_count(self, state_reviewer):
        assert not state_reviewer.has_permission("inventory.count")

    def test_reviewer_cannot_create_resource(self, state_reviewer):
        assert not state_reviewer.has_permission("resources.create")


class TestCounselorPermissions:
    def test_counselor_can_classify(self, state_counselor):
        assert state_counselor.has_permission("resources.classify")

    def test_counselor_cannot_freeze(self, state_counselor):
        assert not state_counselor.has_permission("inventory.freeze")

    def test_counselor_cannot_count(self, state_counselor):
        assert not state_counselor.has_permission("inventory.count")

    def test_counselor_cannot_publish(self, state_counselor):
        assert not state_counselor.has_permission("resources.publish")


class TestLibrarianPermissions:
    def test_librarian_can_adjust(self, state_librarian):
        assert state_librarian.has_permission("inventory.adjust")

    def test_librarian_can_submit_review(self, state_librarian):
        assert state_librarian.has_permission("resources.submit_review")

    def test_librarian_cannot_approve_count(self, state_librarian):
        # inventory.approve_count is admin-only in seeded data
        assert not state_librarian.has_permission("inventory.approve_count")

    def test_librarian_cannot_publish(self, state_librarian):
        assert not state_librarian.has_permission("resources.publish")


class TestStateHelpers:
    def test_clear_resets_permissions(self, state_librarian):
        state_librarian.clear()
        assert not state_librarian.has_permission("resources.view")
        assert not state_librarian.is_authenticated()

    def test_has_role_returns_true_for_own_role(self, state_reviewer):
        assert state_reviewer.has_role("REVIEWER")

    def test_has_role_returns_false_for_other_role(self, state_reviewer):
        assert not state_reviewer.has_role("ADMINISTRATOR")

    def test_auth_header_returns_bearer_when_authenticated(self, state_librarian):
        headers = state_librarian.auth_header()
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")

    def test_auth_header_empty_when_not_authenticated(self):
        s = AppState()
        assert s.auth_header() == {}
