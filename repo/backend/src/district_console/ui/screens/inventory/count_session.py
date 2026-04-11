"""
Count session workspace.

Supports the full count session workflow:
  Open session (choose mode + warehouse) → Add count lines → Close → Approve.

Blind mode: expected_qty column is hidden in the count line table.
Expired session: shows warning and disables all data-entry actions.
Large variance: highlights rows that require supervisor approval.
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
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
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

_SESSION_COLS = ["Mode", "Status", "Warehouse", "Created", "Expires At", "Session ID"]
_LINE_COLS = ["Item ID", "Location ID", "Expected", "Counted", "Δ Variance", "$ Variance", "Needs Approval", "Line ID"]


class _OpenSessionDialog(QDialog):
    def __init__(self, warehouses: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open Count Session")
        layout = QFormLayout(self)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["OPEN", "BLIND", "CYCLE"])
        layout.addRow("Count Mode:", self.mode_combo)
        self.warehouse_combo = QComboBox()
        for w in warehouses:
            self.warehouse_combo.addItem(w.get("name", ""), userData=w.get("warehouse_id", ""))
        layout.addRow("Warehouse:", self.warehouse_combo)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def values(self) -> dict:
        return {
            "mode": self.mode_combo.currentText(),
            "warehouse_id": self.warehouse_combo.currentData(),
        }


class _AddLineDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Count Line")
        layout = QFormLayout(self)
        self.item_edit = QLineEdit()
        self.item_edit.setPlaceholderText("Item UUID")
        layout.addRow("Item ID:", self.item_edit)
        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("Location UUID")
        layout.addRow("Location ID:", self.location_edit)
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(0, 999999)
        layout.addRow("Counted Qty:", self.qty_spin)
        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("Optional reason code")
        layout.addRow("Reason Code:", self.reason_edit)
        self._err = QLabel("")
        self._err.setProperty("error", True)
        self._err.hide()
        layout.addRow(self._err)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def _on_ok(self) -> None:
        if not self.item_edit.text().strip():
            self._err.setText("Item ID is required.")
            self._err.show()
            return
        if not self.location_edit.text().strip():
            self._err.setText("Location ID is required.")
            self._err.show()
            return
        self.accept()

    def values(self) -> dict:
        return {
            "item_id": self.item_edit.text().strip(),
            "location_id": self.location_edit.text().strip(),
            "counted_qty": self.qty_spin.value(),
            "reason_code": self.reason_edit.text().strip() or None,
        }


class CountSessionWidget(QWidget):
    """
    Full count session workspace with session list and line editor.
    """

    def __init__(self, client: ApiClient, state: AppState,
                 parent_window=None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._parent_window = parent_window
        self._active_session_id: Optional[str] = None
        self._active_mode: Optional[str] = None
        self._worker: Optional[ApiWorker] = None
        self._warehouses: list[dict] = []

        self._build_ui()
        self._load_warehouses()

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        self._notif = NotificationBar(self)
        root.addWidget(self._notif)

        # Header actions
        header = QHBoxLayout()
        heading = QLabel("Count Sessions")
        heading.setProperty("heading", True)
        header.addWidget(heading)
        header.addStretch()

        if self._state.has_permission("inventory.count"):
            self._open_btn = QPushButton("▶ Open New Session")
            self._open_btn.clicked.connect(self._do_open_session)
            header.addWidget(self._open_btn)

        root.addLayout(header)

        # Session info
        self._session_info = QGroupBox("Active Session")
        info_layout = QFormLayout(self._session_info)
        self._session_id_lbl = QLabel("None")
        info_layout.addRow("Session ID:", self._session_id_lbl)
        self._session_mode_lbl = QLabel("")
        info_layout.addRow("Mode:", self._session_mode_lbl)
        self._session_status_lbl = QLabel("")
        info_layout.addRow("Status:", self._session_status_lbl)
        self._session_expires_lbl = QLabel("")
        info_layout.addRow("Expires:", self._session_expires_lbl)
        root.addWidget(self._session_info)

        # Lines table
        lines_header = QHBoxLayout()
        lines_header.addWidget(QLabel("Count Lines"))
        lines_header.addStretch()

        if self._state.has_permission("inventory.count"):
            self._add_line_btn = QPushButton("＋ Add Line")
            self._add_line_btn.setEnabled(False)
            self._add_line_btn.clicked.connect(self._do_add_line)
            lines_header.addWidget(self._add_line_btn)

            self._close_btn = QPushButton("■ Close Session")
            self._close_btn.setEnabled(False)
            self._close_btn.clicked.connect(self._do_close_session)
            lines_header.addWidget(self._close_btn)

        if self._state.has_permission("inventory.approve_count"):
            self._approve_btn = QPushButton("✓ Approve")
            self._approve_btn.setEnabled(False)
            self._approve_btn.clicked.connect(self._do_approve)
            lines_header.addWidget(self._approve_btn)

        root.addLayout(lines_header)

        self._lines_table = QTableWidget(0, len(_LINE_COLS))
        self._lines_table.setHorizontalHeaderLabels(_LINE_COLS)
        self._lines_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._lines_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        root.addWidget(self._lines_table, stretch=1)

        self._overlay = LoadingOverlay(self)

    # ------------------------------------------------------------------ #
    # Data                                                                #
    # ------------------------------------------------------------------ #

    def _load_warehouses(self) -> None:
        worker = ApiWorker(self._client.list_warehouses)
        worker.result.connect(self._on_warehouses_loaded)
        worker.start()

    def _on_warehouses_loaded(self, data: dict) -> None:
        self._warehouses = data.get("items", [])

    def _load_session(self, session_id: str) -> None:
        self._overlay.show()
        worker = ApiWorker(self._client.get_count_session, session_id)
        worker.result.connect(self._on_session_loaded)
        worker.error.connect(self._on_error)
        worker.finished_clean.connect(self._overlay.hide)
        worker.start()
        self._worker = worker

    def _on_session_loaded(self, data: dict) -> None:
        self._active_session_id = data.get("session_id", "")
        self._active_mode = data.get("mode", "OPEN")
        status = data.get("status", "")
        is_active = status == "ACTIVE"
        is_closed = status == "CLOSED"

        self._session_id_lbl.setText(self._active_session_id)
        self._session_mode_lbl.setText(self._active_mode)
        self._session_status_lbl.setText(status)
        expires = data.get("expires_at", "")
        self._session_expires_lbl.setText(expires[:19] if expires else "")

        if hasattr(self, "_add_line_btn"):
            self._add_line_btn.setEnabled(is_active)
        if hasattr(self, "_close_btn"):
            self._close_btn.setEnabled(is_active)
        if hasattr(self, "_approve_btn"):
            self._approve_btn.setEnabled(is_closed)

        # Load lines
        self._populate_lines(data.get("lines", []))

        if status == "EXPIRED":
            self._notif.show_message(
                "This count session has expired (8h inactivity).", "warning"
            )

    def _populate_lines(self, lines: list[dict]) -> None:
        self._lines_table.setRowCount(0)
        is_blind = self._active_mode == "BLIND"

        for line in lines:
            row = self._lines_table.rowCount()
            self._lines_table.insertRow(row)
            self._lines_table.setItem(row, 0, QTableWidgetItem(line.get("item_id", "")[:12] + "…"))
            self._lines_table.setItem(row, 1, QTableWidgetItem(line.get("location_id", "")[:12] + "…"))
            expected = "—" if is_blind else str(line.get("expected_qty", "") or "0")
            self._lines_table.setItem(row, 2, QTableWidgetItem(expected))
            self._lines_table.setItem(row, 3, QTableWidgetItem(str(line.get("counted_qty", 0))))
            var_qty = line.get("variance_qty", 0)
            var_cell = QTableWidgetItem(f"{'+' if var_qty >= 0 else ''}{var_qty}")
            if var_qty != 0:
                var_cell.setForeground(
                    Qt.GlobalColor.darkGreen if var_qty > 0 else Qt.GlobalColor.red
                )
            self._lines_table.setItem(row, 4, var_cell)
            var_val = line.get("variance_value", "0")
            self._lines_table.setItem(row, 5, QTableWidgetItem(f"${var_val}"))
            needs_appr = line.get("requires_approval", False)
            appr_cell = QTableWidgetItem("YES" if needs_appr else "no")
            if needs_appr:
                appr_cell.setForeground(Qt.GlobalColor.darkRed)
            self._lines_table.setItem(row, 6, appr_cell)
            self._lines_table.setItem(row, 7, QTableWidgetItem(line.get("line_id", "")))

    # ------------------------------------------------------------------ #
    # Actions                                                             #
    # ------------------------------------------------------------------ #

    def _do_open_session(self) -> None:
        if not self._warehouses:
            self._notif.show_message(
                "No warehouses available. Please create one first.", "warning"
            )
            return
        dialog = _OpenSessionDialog(self._warehouses, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            vals = dialog.values()
            worker = ApiWorker(
                self._client.open_count_session,
                vals["mode"], vals["warehouse_id"]
            )
            worker.result.connect(lambda d: (
                self._notif.show_message("Count session opened.", "success"),
                self._load_session(d.get("session_id", "")),
            ))
            worker.error.connect(self._on_error)
            worker.start()
            self._worker = worker

    def _do_add_line(self) -> None:
        if not self._active_session_id:
            return
        dialog = _AddLineDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            vals = dialog.values()
            worker = ApiWorker(
                self._client.add_count_line,
                self._active_session_id,
                vals["item_id"], vals["location_id"],
                vals["counted_qty"], vals.get("reason_code"),
            )
            worker.result.connect(lambda _: (
                self._notif.show_message("Line added.", "success"),
                self._load_session(self._active_session_id),
            ))
            worker.error.connect(self._on_error)
            worker.start()
            self._worker = worker

    def _do_close_session(self) -> None:
        if not self._active_session_id:
            return
        answer = QMessageBox.question(
            self, "Close Session",
            "Close this count session? All variances will be posted to the ledger.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            worker = ApiWorker(
                self._client.close_count_session, self._active_session_id
            )
            worker.result.connect(lambda _: (
                self._notif.show_message("Session closed.", "info"),
                self._load_session(self._active_session_id),
            ))
            worker.error.connect(self._on_error)
            worker.start()
            self._worker = worker

    def _do_approve(self) -> None:
        if not self._active_session_id:
            return
        notes, ok = QInputDialog.getMultiLineText(
            self, "Approve Session", "Approval Notes:"
        )
        if ok:
            worker = ApiWorker(
                self._client.approve_count_session,
                self._active_session_id, notes or ""
            )
            worker.result.connect(lambda _: (
                self._notif.show_message("Session approved.", "success"),
                self._load_session(self._active_session_id),
            ))
            worker.error.connect(self._on_error)
            worker.start()
            self._worker = worker

    def _on_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Error: {msg}", "error")
