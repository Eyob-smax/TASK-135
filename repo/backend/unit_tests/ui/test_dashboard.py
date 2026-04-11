"""
Tests for DashboardWidget — role-appropriate card rendering and navigation.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from district_console.ui.screens.dashboard import DashboardWidget
from district_console.ui.state import AppState


@pytest.fixture
def state_librarian():
    s = AppState()
    s.set_session("tok", "uid-1", "alice", ["LIBRARIAN"], "2026-04-10T20:00:00")
    return s


@pytest.fixture
def state_teacher():
    s = AppState()
    s.set_session("tok", "uid-2", "bob", ["TEACHER"], "2026-04-10T20:00:00")
    return s


@pytest.fixture
def state_admin():
    s = AppState()
    s.set_session("tok", "uid-3", "carol", ["ADMINISTRATOR"], "2026-04-10T20:00:00")
    return s


@pytest.fixture
def mock_client():
    client = MagicMock()
    # Default return for list_resources
    client.list_resources.return_value = {"items": [], "total": 0}
    return client


class TestDashboardInit:
    def test_dashboard_shows_username(self, qtbot, mock_client, state_librarian):
        w = DashboardWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        # Find heading text
        from PyQt6.QtWidgets import QLabel
        labels = w.findChildren(QLabel)
        texts = [lbl.text() for lbl in labels]
        assert any("alice" in t for t in texts)

    def test_dashboard_shows_roles(self, qtbot, mock_client, state_librarian):
        w = DashboardWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        from PyQt6.QtWidgets import QLabel
        labels = w.findChildren(QLabel)
        texts = [lbl.text() for lbl in labels]
        assert any("LIBRARIAN" in t for t in texts)


class TestDashboardRoleCards:
    def test_librarian_sees_resource_card(
        self, qtbot, mock_client, state_librarian
    ):
        w = DashboardWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        assert hasattr(w, "_card_resources")

    def test_librarian_sees_count_card(
        self, qtbot, mock_client, state_librarian
    ):
        w = DashboardWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        assert hasattr(w, "_card_counts")

    def test_teacher_does_not_see_count_card(
        self, qtbot, mock_client, state_teacher
    ):
        w = DashboardWidget(mock_client, state_teacher)
        qtbot.addWidget(w)
        assert not hasattr(w, "_card_counts")

    def test_admin_sees_review_card(
        self, qtbot, mock_client, state_admin
    ):
        w = DashboardWidget(mock_client, state_admin)
        qtbot.addWidget(w)
        # Admin has resources.publish → sees review card
        assert hasattr(w, "_card_reviews")


class TestDashboardDataLoad:
    def test_load_data_calls_list_resources_for_librarian(
        self, qtbot, mock_client, state_librarian
    ):
        w = DashboardWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        # load_data is called in __init__; at least one list_resources call made
        assert mock_client.list_resources.called

    def test_resource_count_card_shows_total_on_success(
        self, qtbot, mock_client, state_librarian
    ):
        mock_client.list_resources.return_value = {"items": [], "total": 42}
        w = DashboardWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        # Simulate the result
        w._on_resources_loaded({"total": 42})
        assert w._card_resources._value_label.text() == "42"
