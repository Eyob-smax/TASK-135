"""
Tests for ResourceListWidget and ResourceDetailWidget.

Covers: table population, empty state, filter changes, action gating.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton

from district_console.ui.screens.resources.resource_list import ResourceListWidget
from district_console.ui.screens.resources.resource_detail import ResourceDetailWidget
from district_console.ui.state import AppState


@pytest.fixture
def state_librarian():
    s = AppState()
    s.set_session("tok", "uid", "alice", ["LIBRARIAN"], "2026-04-10T20:00:00")
    return s


@pytest.fixture
def state_reviewer():
    s = AppState()
    s.set_session("tok", "uid", "bob", ["REVIEWER"], "2026-04-10T20:00:00")
    return s


@pytest.fixture
def state_teacher():
    s = AppState()
    s.set_session("tok", "uid", "carol", ["TEACHER"], "2026-04-10T20:00:00")
    return s


@pytest.fixture
def mock_client_empty():
    client = MagicMock()
    client.list_resources.return_value = {"items": [], "total": 0}
    return client


@pytest.fixture
def mock_client_with_resources():
    client = MagicMock()
    client.list_resources.return_value = {
        "items": [
            {
                "resource_id": "res-001",
                "title": "Test Book",
                "resource_type": "BOOK",
                "status": "DRAFT",
                "created_by": "alice",
                "updated_at": "2024-06-01T10:00:00",
            }
        ],
        "total": 1,
    }
    return client


class TestResourceListInit:
    def test_table_has_correct_columns(
        self, qtbot, mock_client_empty, state_librarian
    ):
        w = ResourceListWidget(mock_client_empty, state_librarian)
        qtbot.addWidget(w)
        assert w._table.columnCount() == 5

    def test_new_resource_button_visible_for_librarian(
        self, qtbot, mock_client_empty, state_librarian
    ):
        w = ResourceListWidget(mock_client_empty, state_librarian)
        qtbot.addWidget(w)
        assert hasattr(w, "_new_btn")
        assert w._new_btn.isVisible()

    def test_new_resource_button_hidden_for_teacher(
        self, qtbot, mock_client_empty, state_teacher
    ):
        w = ResourceListWidget(mock_client_empty, state_teacher)
        qtbot.addWidget(w)
        assert not hasattr(w, "_new_btn")


class TestResourceListDataLoad:
    def test_table_populated_on_data_loaded(
        self, qtbot, mock_client_with_resources, state_librarian
    ):
        w = ResourceListWidget(mock_client_with_resources, state_librarian)
        qtbot.addWidget(w)
        # Simulate result
        w._on_data_loaded(mock_client_with_resources.list_resources.return_value)
        assert w._table.rowCount() == 1

    def test_table_row_contains_title(
        self, qtbot, mock_client_with_resources, state_librarian
    ):
        w = ResourceListWidget(mock_client_with_resources, state_librarian)
        qtbot.addWidget(w)
        w._on_data_loaded(mock_client_with_resources.list_resources.return_value)
        assert w._table.item(0, 0).text() == "Test Book"

    def test_empty_result_shows_empty_state_widget(
        self, qtbot, mock_client_empty, state_librarian
    ):
        w = ResourceListWidget(mock_client_empty, state_librarian)
        qtbot.addWidget(w)
        w._on_data_loaded({"items": [], "total": 0})
        from district_console.ui.widgets.empty_state import EmptyStateWidget
        assert w._stack.currentWidget() is w._empty

    def test_status_label_shows_count(
        self, qtbot, mock_client_with_resources, state_librarian
    ):
        w = ResourceListWidget(mock_client_with_resources, state_librarian)
        qtbot.addWidget(w)
        w._on_data_loaded(mock_client_with_resources.list_resources.return_value)
        assert "1" in w._status_label.text()

    def test_load_more_shown_when_more_available(
        self, qtbot, mock_client_empty, state_librarian
    ):
        w = ResourceListWidget(mock_client_empty, state_librarian)
        qtbot.addWidget(w)
        w._on_data_loaded({"items": [{"resource_id": "r", "title": "T",
                                       "resource_type": "BOOK", "status": "DRAFT",
                                       "created_by": "", "updated_at": ""}],
                           "total": 100})
        assert w._load_more_btn.isVisible()

    def test_load_more_hidden_when_all_loaded(
        self, qtbot, mock_client_with_resources, state_librarian
    ):
        w = ResourceListWidget(mock_client_with_resources, state_librarian)
        qtbot.addWidget(w)
        w._on_data_loaded({"items": [{"resource_id": "r", "title": "T",
                                       "resource_type": "BOOK", "status": "DRAFT",
                                       "created_by": "", "updated_at": ""}],
                           "total": 1})
        assert not w._load_more_btn.isVisible()


class TestResourceListFocusSearch:
    def test_focus_search_focuses_search_field(
        self, qtbot, mock_client_empty, state_librarian
    ):
        w = ResourceListWidget(mock_client_empty, state_librarian)
        qtbot.addWidget(w)
        w.show()
        w.focus_search()
        assert w._search_edit.hasFocus()


class TestResourceDetailInit:
    def test_detail_widget_loads_on_init(
        self, qtbot, state_librarian
    ):
        client = MagicMock()
        client.get_resource.return_value = {
            "resource_id": "res-001",
            "title": "My Book",
            "resource_type": "BOOK",
            "status": "DRAFT",
            "isbn": None,
            "dedup_key": "abc123def456abc123def456abc123de",
            "created_at": "2024-06-01T10:00:00",
            "updated_at": "2024-06-01T12:00:00",
        }
        client.list_revisions.return_value = {"items": []}
        w = ResourceDetailWidget(client, state_librarian, "res-001")
        qtbot.addWidget(w)
        # Simulate the loaded result
        w._on_resource_loaded(client.get_resource.return_value)
        assert w._title_edit.text() == "My Book"

    def test_submit_button_visible_for_draft_with_permission(
        self, qtbot, state_librarian
    ):
        client = MagicMock()
        client.get_resource.return_value = {
            "resource_id": "res-001",
            "title": "Draft Book",
            "resource_type": "BOOK",
            "status": "DRAFT",
            "isbn": None,
            "dedup_key": "abc" * 12,
            "created_at": "",
            "updated_at": "",
        }
        client.list_revisions.return_value = {"items": []}
        w = ResourceDetailWidget(client, state_librarian, "res-001")
        qtbot.addWidget(w)
        w._on_resource_loaded(client.get_resource.return_value)
        assert w._submit_btn.isVisible()

    def test_publish_button_hidden_for_draft(
        self, qtbot, state_librarian
    ):
        client = MagicMock()
        client.get_resource.return_value = {
            "resource_id": "r", "title": "Draft", "resource_type": "BOOK",
            "status": "DRAFT", "isbn": None,
            "dedup_key": "x" * 32, "created_at": "", "updated_at": "",
        }
        client.list_revisions.return_value = {"items": []}
        w = ResourceDetailWidget(client, state_librarian, "r")
        qtbot.addWidget(w)
        w._update_action_buttons("DRAFT")
        assert not w._publish_btn.isVisible()

    def test_publish_button_visible_for_in_review_reviewer(
        self, qtbot, state_reviewer
    ):
        client = MagicMock()
        client.get_resource.return_value = {
            "resource_id": "r", "title": "IR", "resource_type": "BOOK",
            "status": "IN_REVIEW", "isbn": None,
            "dedup_key": "x" * 32, "created_at": "", "updated_at": "",
        }
        client.list_revisions.return_value = {"items": []}
        w = ResourceDetailWidget(client, state_reviewer, "r")
        qtbot.addWidget(w)
        w._update_action_buttons("IN_REVIEW")
        assert w._publish_btn.isVisible()

    def test_reviewer_notes_required_shown_on_empty_publish(
        self, qtbot, state_reviewer
    ):
        client = MagicMock()
        client.get_resource.return_value = {
            "resource_id": "r", "title": "IR", "resource_type": "BOOK",
            "status": "IN_REVIEW", "isbn": None,
            "dedup_key": "x" * 32, "created_at": "", "updated_at": "",
        }
        client.list_revisions.return_value = {"items": []}
        w = ResourceDetailWidget(client, state_reviewer, "r")
        qtbot.addWidget(w)
        # Simulate clicking publish with empty notes (patch QInputDialog)
        from unittest.mock import patch
        with patch(
            "district_console.ui.screens.resources.resource_detail.QInputDialog.getMultiLineText",
            return_value=("", True)  # ok=True but empty notes
        ):
            w._do_publish()
        # Notification bar should show warning
        assert w._notif._message_label.text() != ""
