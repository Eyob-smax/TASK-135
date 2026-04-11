"""
Tests for LedgerViewerWidget and CountSessionWidget.

Covers: table rendering, blind mode masking, approval gating, error display.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from district_console.ui.screens.inventory.ledger_viewer import LedgerViewerWidget
from district_console.ui.screens.inventory.count_session import CountSessionWidget
from district_console.ui.state import AppState


@pytest.fixture
def state_librarian():
    s = AppState()
    s.set_session("tok", "uid", "alice", ["LIBRARIAN"], "2026-04-10T20:00:00")
    return s


@pytest.fixture
def state_admin():
    s = AppState()
    s.set_session("tok", "uid", "carol", ["ADMINISTRATOR"], "2026-04-10T20:00:00")
    return s


@pytest.fixture
def state_teacher():
    s = AppState()
    s.set_session("tok", "uid", "dave", ["TEACHER"], "2026-04-10T20:00:00")
    return s


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.list_stock.return_value = {"items": [], "total": 0}
    client.list_ledger.return_value = {"items": [], "total": 0}
    client.list_warehouses.return_value = {"items": [], "total": 0}
    return client


class TestLedgerViewerInit:
    def test_stock_table_has_correct_columns(
        self, qtbot, mock_client, state_librarian
    ):
        w = LedgerViewerWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        from district_console.ui.screens.inventory.ledger_viewer import _STOCK_COLS
        assert w._stock_table.columnCount() == len(_STOCK_COLS)

    def test_ledger_table_has_correct_columns(
        self, qtbot, mock_client, state_librarian
    ):
        w = LedgerViewerWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        from district_console.ui.screens.inventory.ledger_viewer import _LEDGER_COLS
        assert w._ledger_table.columnCount() == len(_LEDGER_COLS)

    def test_adjustment_button_visible_for_librarian(
        self, qtbot, mock_client, state_librarian
    ):
        w = LedgerViewerWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        from PyQt6.QtWidgets import QPushButton
        buttons = [b.text() for b in w.findChildren(QPushButton)]
        assert any("Adjustment" in b for b in buttons)

    def test_adjustment_button_not_visible_for_teacher(
        self, qtbot, mock_client, state_teacher
    ):
        w = LedgerViewerWidget(mock_client, state_teacher)
        qtbot.addWidget(w)
        from PyQt6.QtWidgets import QPushButton
        buttons = [b.text() for b in w.findChildren(QPushButton)]
        assert not any("Adjustment" in b for b in buttons)


class TestLedgerViewerDataLoad:
    def test_stock_table_populated_on_load(
        self, qtbot, mock_client, state_librarian
    ):
        mock_client.list_stock.return_value = {
            "items": [
                {
                    "item_id": "item-001",
                    "location_id": "loc-001",
                    "quantity": 50,
                    "status": "AVAILABLE",
                    "is_frozen": False,
                    "balance_id": "bal-001",
                }
            ],
            "total": 1,
        }
        w = LedgerViewerWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        w._on_stock_loaded(mock_client.list_stock.return_value)
        assert w._stock_table.rowCount() == 1

    def test_ledger_positive_delta_green(
        self, qtbot, mock_client, state_librarian
    ):
        w = LedgerViewerWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        w._on_ledger_loaded({
            "items": [
                {
                    "entry_type": "ADJUSTMENT",
                    "quantity_delta": 10,
                    "quantity_after": 110,
                    "operator_id": "op-001",
                    "reason_code": "RESTOCK",
                    "is_reversed": False,
                    "created_at": "2024-06-01T10:00:00",
                }
            ]
        })
        delta_cell = w._ledger_table.item(0, 1)
        assert "+10" in delta_cell.text()

    def test_ledger_negative_delta_shows_sign(
        self, qtbot, mock_client, state_librarian
    ):
        w = LedgerViewerWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        w._on_ledger_loaded({
            "items": [
                {
                    "entry_type": "ADJUSTMENT",
                    "quantity_delta": -5,
                    "quantity_after": 95,
                    "operator_id": "op-001",
                    "reason_code": "WRITE_OFF",
                    "is_reversed": False,
                    "created_at": "2024-06-01T10:00:00",
                }
            ]
        })
        delta_cell = w._ledger_table.item(0, 1)
        assert "-5" in delta_cell.text()


class TestCountSessionWidget:
    def test_approve_button_hidden_for_librarian(
        self, qtbot, mock_client, state_librarian
    ):
        w = CountSessionWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        assert not hasattr(w, "_approve_btn")

    def test_approve_button_visible_for_admin(
        self, qtbot, mock_client, state_admin
    ):
        w = CountSessionWidget(mock_client, state_admin)
        qtbot.addWidget(w)
        assert hasattr(w, "_approve_btn")

    def test_blind_mode_masks_expected_qty(
        self, qtbot, mock_client, state_librarian
    ):
        w = CountSessionWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        w._active_mode = "BLIND"
        w._populate_lines([
            {
                "item_id": "item-001",
                "location_id": "loc-001",
                "expected_qty": 100,
                "counted_qty": 95,
                "variance_qty": -5,
                "variance_value": "49.95",
                "requires_approval": False,
                "line_id": "line-001",
            }
        ])
        expected_cell = w._lines_table.item(0, 2)
        assert expected_cell.text() == "—"

    def test_open_mode_shows_expected_qty(
        self, qtbot, mock_client, state_librarian
    ):
        w = CountSessionWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        w._active_mode = "OPEN"
        w._populate_lines([
            {
                "item_id": "item-001",
                "location_id": "loc-001",
                "expected_qty": 100,
                "counted_qty": 95,
                "variance_qty": -5,
                "variance_value": "49.95",
                "requires_approval": False,
                "line_id": "line-001",
            }
        ])
        expected_cell = w._lines_table.item(0, 2)
        assert expected_cell.text() == "100"

    def test_requires_approval_line_shows_yes(
        self, qtbot, mock_client, state_librarian
    ):
        w = CountSessionWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        w._active_mode = "OPEN"
        w._populate_lines([
            {
                "item_id": "i", "location_id": "l",
                "expected_qty": 10, "counted_qty": 5,
                "variance_qty": -5, "variance_value": "500.00",
                "requires_approval": True, "line_id": "ln-1",
            }
        ])
        appr_cell = w._lines_table.item(0, 6)
        assert appr_cell.text() == "YES"

    def test_expired_session_shows_notification(
        self, qtbot, mock_client, state_librarian
    ):
        w = CountSessionWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        w._on_session_loaded({
            "session_id": "sess-001",
            "mode": "OPEN",
            "status": "EXPIRED",
            "lines": [],
        })
        assert w._notif._message_label.text() != ""

    def test_add_line_button_disabled_when_no_session(
        self, qtbot, mock_client, state_librarian
    ):
        w = CountSessionWidget(mock_client, state_librarian)
        qtbot.addWidget(w)
        assert not w._add_line_btn.isEnabled()
