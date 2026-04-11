"""
Inventory item detail panel.

Shows full item record plus all stock balance rows for that item.
The stock table has the same right-click context menu as LedgerViewer
(Freeze / Unfreeze / Relocate).
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from district_console.ui.client import ApiClient, ApiError
from district_console.ui.state import AppState
from district_console.ui.utils.async_worker import ApiWorker
from district_console.ui.widgets.loading_overlay import LoadingOverlay
from district_console.ui.widgets.notification_bar import NotificationBar


class ItemDetailWidget(QWidget):
    """Item form + stock balance table for a single inventory item."""

    def __init__(self, client: ApiClient, state: AppState,
                 item_id: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._item_id = item_id
        self._worker: Optional[ApiWorker] = None

        self._build_ui()
        self.load_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        self._notif = NotificationBar(self)
        root.addWidget(self._notif)

        form = QFormLayout()
        self._sku_lbl = QLabel()
        form.addRow("SKU:", self._sku_lbl)
        self._name_lbl = QLabel()
        form.addRow("Name:", self._name_lbl)
        self._cost_lbl = QLabel()
        form.addRow("Unit Cost:", self._cost_lbl)
        self._created_lbl = QLabel()
        form.addRow("Created:", self._created_lbl)
        root.addLayout(form)

        root.addWidget(QLabel("Stock Balances"))
        self._stock_table = QTableWidget(0, 5)
        self._stock_table.setHorizontalHeaderLabels(
            ["Location ID", "Quantity", "Status", "Frozen", "Balance ID"]
        )
        self._stock_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._stock_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._stock_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._stock_table.customContextMenuRequested.connect(
            self._show_context_menu
        )
        root.addWidget(self._stock_table, stretch=1)

        self._overlay = LoadingOverlay(self)

    def load_data(self) -> None:
        self._overlay.show()
        self._worker = ApiWorker(self._client.get_inventory_item, self._item_id)
        self._worker.result.connect(self._on_item_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.finished_clean.connect(self._overlay.hide)
        self._worker.start()

    def _on_item_loaded(self, data: dict) -> None:
        self._sku_lbl.setText(data.get("sku", ""))
        self._name_lbl.setText(data.get("name", ""))
        self._cost_lbl.setText(data.get("unit_cost", ""))
        created = data.get("created_at", "")
        self._created_lbl.setText(created[:19] if created else "")
        self._load_stock()

    def _load_stock(self) -> None:
        worker = ApiWorker(
            self._client.list_stock, item_id=self._item_id, offset=0, limit=100
        )
        worker.result.connect(self._on_stock_loaded)
        worker.error.connect(self._on_error)
        worker.start()

    def _on_stock_loaded(self, data: dict) -> None:
        rows = data.get("items", [])
        self._stock_table.setRowCount(0)
        for r in rows:
            row = self._stock_table.rowCount()
            self._stock_table.insertRow(row)
            self._stock_table.setItem(row, 0, QTableWidgetItem(r.get("location_id", "")))
            self._stock_table.setItem(row, 1, QTableWidgetItem(str(r.get("quantity", 0))))
            self._stock_table.setItem(row, 2, QTableWidgetItem(r.get("status", "")))
            self._stock_table.setItem(row, 3, QTableWidgetItem("Yes" if r.get("is_frozen") else "No"))
            self._stock_table.setItem(row, 4, QTableWidgetItem(r.get("balance_id", "")))
            self._stock_table.item(row, 4).setData(Qt.ItemDataRole.UserRole, r)

    def _show_context_menu(self, pos) -> None:
        row = self._stock_table.rowAt(pos.y())
        if row < 0:
            return
        record = self._stock_table.item(row, 4).data(Qt.ItemDataRole.UserRole)
        if not isinstance(record, dict):
            return
        balance_id = record.get("balance_id", "")
        is_frozen = record.get("is_frozen", False)

        menu = QMenu(self)
        if self._state.has_permission("inventory.freeze"):
            if is_frozen:
                a = menu.addAction("Unfreeze")
                a.triggered.connect(lambda: self._do_unfreeze(balance_id))
            else:
                a = menu.addAction("Freeze…")
                a.triggered.connect(lambda: self._do_freeze(balance_id))
        if self._state.has_permission("inventory.relocate"):
            a2 = menu.addAction("Relocate…")
            a2.triggered.connect(lambda: self._do_relocate(record))
        menu.exec(self._stock_table.viewport().mapToGlobal(pos))

    def _do_freeze(self, balance_id: str) -> None:
        from PyQt6.QtWidgets import QInputDialog
        reason, ok = QInputDialog.getText(self, "Freeze", "Reason:")
        if ok and reason.strip():
            worker = ApiWorker(self._client.freeze_stock, balance_id, reason.strip())
            worker.result.connect(lambda _: self._load_stock())
            worker.error.connect(self._on_error)
            worker.start()
            self._worker = worker

    def _do_unfreeze(self, balance_id: str) -> None:
        worker = ApiWorker(self._client.unfreeze_stock, balance_id)
        worker.result.connect(lambda _: self._load_stock())
        worker.error.connect(self._on_error)
        worker.start()

    def _do_relocate(self, record: dict) -> None:
        from PyQt6.QtWidgets import QInputDialog
        to_loc, ok = QInputDialog.getText(self, "Relocate", "Destination Location ID:")
        if not ok or not to_loc.strip():
            return
        qty_str, ok2 = QInputDialog.getText(self, "Relocate", "Quantity:")
        if not ok2 or not qty_str.strip().isdigit():
            return
        worker = ApiWorker(
            self._client.create_relocation,
            record.get("item_id", self._item_id),
            record.get("location_id", ""),
            to_loc.strip(),
            int(qty_str.strip()),
        )
        worker.result.connect(lambda _: (
            self._notif.show_message("Relocation created.", "success"),
            self._load_stock(),
        ))
        worker.error.connect(self._on_error)
        worker.start()

    def _on_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Error: {msg}", "error")
