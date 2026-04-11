"""
Tests for SystemTray — minimize/restore behavior and safe shutdown check.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QApplication

from district_console.ui.state import AppState
from district_console.ui.tray import SystemTray


@pytest.fixture
def state():
    return AppState()


@pytest.fixture
def tray(qapp, state):
    t = SystemTray(qapp, state)
    return t


class TestTrayInit:
    def test_tray_has_context_menu(self, tray):
        assert tray.contextMenu() is not None

    def test_tray_has_restore_and_quit_actions(self, tray):
        menu = tray.contextMenu()
        actions = [a.text() for a in menu.actions() if a.text()]
        assert any("Open" in a or "Restore" in a for a in actions)
        assert any("Quit" in a for a in actions)

    def test_tray_tooltip_contains_district(self, tray):
        assert "District" in tray.toolTip()


class TestTrayUserLabel:
    def test_update_user_label_shows_username(self, tray):
        tray.update_user_label("alice", ["LIBRARIAN"])
        label_texts = [
            a.text() for a in tray.contextMenu().actions()
        ]
        combined = " ".join(label_texts)
        assert "alice" in combined

    def test_update_user_label_shows_role(self, tray):
        tray.update_user_label("bob", ["ADMINISTRATOR"])
        label_texts = [
            a.text() for a in tray.contextMenu().actions()
        ]
        combined = " ".join(label_texts)
        assert "ADMINISTRATOR" in combined


class TestTrayMainWindow:
    def test_restore_window_does_nothing_without_main_window(self, tray):
        tray._main_window = None
        tray._restore_window()  # Should not raise

    def test_restore_window_calls_show_normal(self, tray):
        mock_window = MagicMock()
        tray.set_main_window(mock_window)
        tray._restore_window()
        mock_window.showNormal.assert_called_once()

    def test_set_main_window_stores_reference(self, tray):
        mock_window = MagicMock()
        tray.set_main_window(mock_window)
        assert tray._main_window is mock_window


class TestTraySafeQuit:
    def test_safe_quit_with_no_resumable_work_calls_app_quit(
        self, qapp, tray, state
    ):
        state.active_workers = 0
        state.pending_checkpoints = []
        with patch.object(QApplication, "quit") as mock_quit:
            tray._safe_quit()
            mock_quit.assert_called_once()

    def test_safe_quit_with_resumable_work_shows_dialog(
        self, qapp, tray, state
    ):
        state.active_workers = 1
        # Patch QMessageBox.question to simulate "No" (cancel quit)
        with patch(
            "district_console.ui.tray.QMessageBox.question",
            return_value=MagicMock()
        ) as mock_q:
            from PyQt6.QtWidgets import QMessageBox
            mock_q.return_value = QMessageBox.StandardButton.No
            with patch.object(QApplication, "quit") as mock_quit:
                tray._safe_quit()
                mock_quit.assert_not_called()
