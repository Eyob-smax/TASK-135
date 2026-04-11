"""
Inventory ledger viewer.

Shows a paginated, filterable, read-only view of ledger entries (append-only).
The toolbar lets users filter by item, location, and entry type.
Double-clicking an entry opens item detail for the associated item.
Right-click on a stock balance row offers Freeze / Unfreeze / Relocate actions
(gated on role).
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from district_console.ui.client import ApiClient, ApiError
from district_console.ui.state import AppState
from district_console.ui.utils.async_worker import ApiWorker
from district_console.ui.widgets.empty_state import EmptyStateWidget
from district_console.ui.widgets.loading_overlay import LoadingOverlay
from district_console.ui.widgets.notification_bar import NotificationBar

_LEDGER_COLS = ["Type", "Δ Qty", "After", "Operator", "Reason", "Reversed", "Created At"]
_STOCK_COLS = ["Item", "Location", "Qty", "Status", "Frozen", "Balance ID"]


class _FreezeDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Freeze Stock")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Freeze reason (required):"))
        self.reason_edit = QLineEdit()
        layout.addWidget(self.reason_edit)
        self._err = QLabel("")
        self._err.setProperty("error", True)
        self._err.hide()
        layout.addWidget(self._err)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_ok(self) -> None:
        if not self.reason_edit.text().strip():
            self._err.setText("Reason is required.")
            self._err.show()
            return
        self.accept()


class LedgerViewerWidget(QWidget):
    """
    Split view: stock balances (top) + ledger entries (bottom).
    """

    def __init__(self, client: ApiClient, state: AppState,
                 parent_window=None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._parent_window = parent_window
        self._stock_worker: Optional[ApiWorker] = None
        self._ledger_worker: Optional[ApiWorker] = None
        self._selected_item_id: Optional[str] = None
        self._ledger_offset = 0
        self._ledger_limit = 50

        self._build_ui()
        self.load_data()

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        self._notif = NotificationBar(self)
        root.addWidget(self._notif)

        # Filter bar
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Item ID:"))
        self._item_filter = QLineEdit()
        self._item_filter.setPlaceholderText("Paste item UUID…")
        self._item_filter.setMaximumWidth(300)
        filter_row.addWidget(self._item_filter)

        self._refresh_btn = QPushButton("↻ Load")
        self._refresh_btn.clicked.connect(self._on_filter_applied)
        filter_row.addWidget(self._refresh_btn)

        if self._state.has_permission("inventory.adjust"):
            adj_btn = QPushButton("＋ Adjustment")
            adj_btn.clicked.connect(self._do_adjustment)
            filter_row.addWidget(adj_btn)

        filter_row.addStretch()
        root.addLayout(filter_row)

        # Splitter: stock top, ledger bottom
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Stock balances panel
        stock_panel = QWidget()
        sp_layout = QVBoxLayout(stock_panel)
        sp_layout.setContentsMargins(0, 0, 0, 0)
        sp_layout.addWidget(QLabel("Stock Balances"))
        self._stock_table = QTableWidget(0, len(_STOCK_COLS))
        self._stock_table.setHorizontalHeaderLabels(_STOCK_COLS)
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
            self._show_stock_context_menu
        )
        self._stock_table.cellClicked.connect(self._on_stock_row_selected)
        sp_layout.addWidget(self._stock_table)
        splitter.addWidget(stock_panel)

        # Ledger panel
        ledger_panel = QWidget()
        lp_layout = QVBoxLayout(ledger_panel)
        lp_layout.setContentsMargins(0, 0, 0, 0)
        lp_layout.addWidget(QLabel("Ledger Entries (append-only)"))
        self._ledger_table = QTableWidget(0, len(_LEDGER_COLS))
        self._ledger_table.setHorizontalHeaderLabels(_LEDGER_COLS)
        self._ledger_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        lp_layout.addWidget(self._ledger_table)
        splitter.addWidget(ledger_panel)

        splitter.setSizes([300, 400])
        root.addWidget(splitter, stretch=1)

        self._overlay = LoadingOverlay(self)

    # ------------------------------------------------------------------ #
    # Data                                                                #
    # ------------------------------------------------------------------ #

    def load_data(self) -> None:
        self._load_stock()

    def _load_stock(self) -> None:
        item_id = self._item_filter.text().strip() or None
        self._stock_worker = ApiWorker(
            self._client.list_stock,
            item_id=item_id, offset=0, limit=50
        )
        self._stock_worker.result.connect(self._on_stock_loaded)
        self._stock_worker.error.connect(self._on_error)
        self._stock_worker.start()

    def _on_stock_loaded(self, data: dict) -> None:
        items = data.get("items", [])
        self._stock_table.setRowCount(0)
        for r in items:
            row = self._stock_table.rowCount()
            self._stock_table.insertRow(row)
            self._stock_table.setItem(row, 0, QTableWidgetItem(r.get("item_id", "")[:8] + "…"))
            self._stock_table.setItem(row, 1, QTableWidgetItem(r.get("location_id", "")[:8] + "…"))
            self._stock_table.setItem(row, 2, QTableWidgetItem(str(r.get("quantity", 0))))
            self._stock_table.setItem(row, 3, QTableWidgetItem(r.get("status", "")))
            frozen = "Yes" if r.get("is_frozen") else "No"
            self._stock_table.setItem(row, 4, QTableWidgetItem(frozen))
            self._stock_table.setItem(row, 5, QTableWidgetItem(r.get("balance_id", "")))
            self._stock_table.item(row, 5).setData(
                Qt.ItemDataRole.UserRole, r
            )

    def _on_stock_row_selected(self, row: int, col: int) -> None:
        item_cell = self._stock_table.item(row, 5)
        if not item_cell:
            return
        record = item_cell.data(Qt.ItemDataRole.UserRole)
        if isinstance(record, dict):
            self._selected_item_id = record.get("item_id")
            self._load_ledger(item_id=self._selected_item_id)

    def _load_ledger(self, item_id: Optional[str] = None) -> None:
        self._ledger_worker = ApiWorker(
            self._client.list_ledger,
            item_id=item_id,
            offset=0, limit=self._ledger_limit,
        )
        self._ledger_worker.result.connect(self._on_ledger_loaded)
        self._ledger_worker.error.connect(self._on_error)
        self._ledger_worker.start()

    def _on_ledger_loaded(self, data: dict) -> None:
        entries = data.get("items", [])
        self._ledger_table.setRowCount(0)
        for e in entries:
            row = self._ledger_table.rowCount()
            self._ledger_table.insertRow(row)
            self._ledger_table.setItem(row, 0, QTableWidgetItem(e.get("entry_type", "")))
            delta = e.get("quantity_delta", 0)
            cell = QTableWidgetItem(f"{'+' if delta >= 0 else ''}{delta}")
            cell.setForeground(
                Qt.GlobalColor.darkGreen if delta >= 0 else Qt.GlobalColor.red
            )
            self._ledger_table.setItem(row, 1, cell)
            self._ledger_table.setItem(row, 2, QTableWidgetItem(str(e.get("quantity_after", ""))))
            self._ledger_table.setItem(row, 3, QTableWidgetItem(e.get("operator_id", "")[:8] + "…"))
            self._ledger_table.setItem(row, 4, QTableWidgetItem(e.get("reason_code", "")))
            self._ledger_table.setItem(row, 5, QTableWidgetItem("Yes" if e.get("is_reversed") else "No"))
            created = e.get("created_at", "")
            self._ledger_table.setItem(row, 6, QTableWidgetItem(created[:19] if created else ""))

    def _on_filter_applied(self) -> None:
        self._load_stock()

    def _on_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Error: {msg}", "error")

    # ------------------------------------------------------------------ #
    # Context menu                                                        #
    # ------------------------------------------------------------------ #

    def _show_stock_context_menu(self, pos) -> None:
        row = self._stock_table.rowAt(pos.y())
        if row < 0:
            return
        record = self._stock_table.item(row, 5).data(Qt.ItemDataRole.UserRole)
        if not isinstance(record, dict):
            return
        balance_id = record.get("balance_id", "")
        is_frozen = record.get("is_frozen", False)

        menu = QMenu(self)
        if self._state.has_permission("inventory.freeze"):
            if is_frozen:
                unf = menu.addAction("Unfreeze Stock")
                unf.triggered.connect(lambda: self._do_unfreeze(balance_id))
            else:
                fr = menu.addAction("Freeze Stock…")
                fr.triggered.connect(lambda: self._do_freeze(balance_id))

        if self._state.has_permission("inventory.relocate"):
            rel = menu.addAction("Relocate…")
            rel.triggered.connect(
                lambda: self._do_relocate(record)
            )

        menu.exec(self._stock_table.viewport().mapToGlobal(pos))

    def _do_freeze(self, balance_id: str) -> None:
        dialog = _FreezeDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            worker = ApiWorker(
                self._client.freeze_stock, balance_id,
                dialog.reason_edit.text().strip()
            )
            worker.result.connect(lambda _: (
                self._notif.show_message("Stock frozen.", "info"),
                self._load_stock(),
            ))
            worker.error.connect(self._on_error)
            worker.start()

    def _do_unfreeze(self, balance_id: str) -> None:
        worker = ApiWorker(self._client.unfreeze_stock, balance_id)
        worker.result.connect(lambda _: (
            self._notif.show_message("Stock unfrozen.", "success"),
            self._load_stock(),
        ))
        worker.error.connect(self._on_error)
        worker.start()

    def _do_relocate(self, record: dict) -> None:
        from PyQt6.QtWidgets import QInputDialog
        to_loc, ok = QInputDialog.getText(
            self, "Relocate Stock", "Destination Location ID:"
        )
        if not ok or not to_loc.strip():
            return
        qty_str, ok2 = QInputDialog.getText(
            self, "Relocate Stock", "Quantity to move:"
        )
        if not ok2 or not qty_str.strip().isdigit():
            return
        worker = ApiWorker(
            self._client.create_relocation,
            record.get("item_id", ""),
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

    def _do_adjustment(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        item_id, ok = QInputDialog.getText(self, "Adjustment", "Item ID:")
        if not ok or not item_id.strip():
            return
        loc_id, ok2 = QInputDialog.getText(self, "Adjustment", "Location ID:")
        if not ok2 or not loc_id.strip():
            return
        qty_str, ok3 = QInputDialog.getText(
            self, "Adjustment", "Quantity delta (positive or negative):"
        )
        if not ok3:
            return
        try:
            qty = int(qty_str.strip())
        except ValueError:
            self._notif.show_message("Quantity must be an integer.", "warning")
            return
        reason, ok4 = QInputDialog.getText(self, "Adjustment", "Reason code:")
        if not ok4 or not reason.strip():
            return
        worker = ApiWorker(
            self._client.add_adjustment,
            item_id.strip(), loc_id.strip(), qty, reason.strip().upper()
        )
        worker.result.connect(lambda _: (
            self._notif.show_message("Adjustment recorded.", "success"),
            self.load_data(),
        ))
        worker.error.connect(self._on_error)
        worker.start()
