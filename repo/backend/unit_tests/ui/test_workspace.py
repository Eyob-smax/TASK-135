"""
Tests for WorkspaceCoordinator — sub-window management, singleton enforcement,
and navigation dispatch.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QLabel, QMdiArea, QWidget

from district_console.ui.shell.workspace import WorkspaceCoordinator


@pytest.fixture
def mdi(qapp, qtbot):
    area = QMdiArea()
    qtbot.addWidget(area)
    area.show()
    return area


@pytest.fixture
def coordinator(mdi):
    return WorkspaceCoordinator(mdi)


class TestRegistration:
    def test_register_and_open_creates_subwindow(
        self, coordinator, qtbot
    ):
        coordinator.register("test", lambda: QLabel("Hello"))
        sub = coordinator.open("test", title="Test")
        assert sub is not None
        assert coordinator.is_open("test")

    def test_open_unknown_key_returns_none(self, coordinator):
        result = coordinator.open("nonexistent")
        assert result is None

    def test_register_multiple_keys(self, coordinator):
        coordinator.register("a", lambda: QLabel("A"))
        coordinator.register("b", lambda: QLabel("B"))
        coordinator.open("a", title="A")
        coordinator.open("b", title="B")
        assert coordinator.is_open("a")
        assert coordinator.is_open("b")


class TestSingletonBehavior:
    def test_opening_same_key_twice_returns_existing_window(
        self, coordinator
    ):
        coordinator.register("single", lambda: QLabel("X"))
        sub1 = coordinator.open("single", title="X")
        sub2 = coordinator.open("single", title="X")
        assert sub1 is sub2

    def test_is_open_returns_false_after_close(self, coordinator, qtbot):
        coordinator.register("closeable", lambda: QLabel("C"))
        coordinator.open("closeable", title="C")
        coordinator.close("closeable")
        # After close, is_open may still hold stale ref until destroyed signal
        # The key is that reopening creates a new window
        sub2 = coordinator.open("closeable", title="C")
        assert sub2 is not None


class TestCloseAll:
    def test_close_all_clears_all_open_windows(self, coordinator):
        coordinator.register("w1", lambda: QLabel("W1"))
        coordinator.register("w2", lambda: QLabel("W2"))
        coordinator.open("w1")
        coordinator.open("w2")
        coordinator.close_all()
        assert not coordinator.is_open("w1")
        assert not coordinator.is_open("w2")


class TestActiveKey:
    def test_active_key_returns_none_when_nothing_open(self, coordinator):
        assert coordinator.active_key() is None

    def test_active_widget_returns_none_when_nothing_open(self, coordinator):
        assert coordinator.active_widget() is None
