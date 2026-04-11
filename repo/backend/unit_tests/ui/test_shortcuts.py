"""
Tests for ShortcutManager — shortcut registration, dispatch, and connection.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QMainWindow

from district_console.ui.shortcuts import SHORTCUT_MAP, ShortcutManager


@pytest.fixture
def main_window(qapp, qtbot):
    w = QMainWindow()
    qtbot.addWidget(w)
    return w


@pytest.fixture
def shortcut_mgr(main_window):
    return ShortcutManager(main_window)


class TestShortcutRegistration:
    def test_all_shortcut_names_registered(self, shortcut_mgr):
        for name in SHORTCUT_MAP:
            action = shortcut_mgr.action(name)
            assert action is not None, f"Shortcut '{name}' not registered"

    def test_global_search_is_ctrl_f(self, shortcut_mgr):
        action = shortcut_mgr.action("global_search")
        assert action.shortcut() == QKeySequence("Ctrl+F")

    def test_new_record_is_ctrl_n(self, shortcut_mgr):
        action = shortcut_mgr.action("new_record")
        assert action.shortcut() == QKeySequence("Ctrl+N")

    def test_logout_is_ctrl_shift_o(self, shortcut_mgr):
        action = shortcut_mgr.action("logout")
        assert action.shortcut() == QKeySequence("Ctrl+Shift+O")

    def test_open_inventory_ledger_is_ctrl_shift_l(self, shortcut_mgr):
        action = shortcut_mgr.action("open_inventory_ledger")
        assert action is not None
        assert action.shortcut() == QKeySequence("Ctrl+Shift+L")

    def test_unknown_shortcut_returns_none(self, shortcut_mgr):
        assert shortcut_mgr.action("nonexistent_key") is None


class TestShortcutConnect:
    def test_connect_attaches_slot(self, shortcut_mgr):
        slot = MagicMock()
        shortcut_mgr.connect("global_search", slot)
        shortcut_mgr.trigger("global_search")
        slot.assert_called_once()

    def test_connect_multiple_slots(self, shortcut_mgr):
        slot1 = MagicMock()
        slot2 = MagicMock()
        shortcut_mgr.connect("new_record", slot1)
        shortcut_mgr.connect("new_record", slot2)
        shortcut_mgr.trigger("new_record")
        slot1.assert_called_once()
        slot2.assert_called_once()

    def test_connect_unknown_name_does_not_raise(self, shortcut_mgr):
        shortcut_mgr.connect("does_not_exist", MagicMock())  # no error

    def test_trigger_unknown_name_does_not_raise(self, shortcut_mgr):
        shortcut_mgr.trigger("does_not_exist")  # no error


class TestShortcutHint:
    def test_hint_for_global_search(self):
        assert ShortcutManager.shortcut_hint("global_search") == "Ctrl+F"

    def test_hint_for_unknown_returns_empty(self):
        assert ShortcutManager.shortcut_hint("nonexistent") == ""


class TestShortcutEnabled:
    def test_set_enabled_false_disables_action(self, shortcut_mgr):
        shortcut_mgr.set_enabled("logout", False)
        assert not shortcut_mgr.action("logout").isEnabled()

    def test_set_enabled_true_re_enables_action(self, shortcut_mgr):
        shortcut_mgr.set_enabled("logout", False)
        shortcut_mgr.set_enabled("logout", True)
        assert shortcut_mgr.action("logout").isEnabled()
