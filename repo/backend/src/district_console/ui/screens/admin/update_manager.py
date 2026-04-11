"""
Update package management admin screen.

Package history table: version | status | imported_at | imported_by.
Import button (file dialog → upload ZIP).
Apply / Rollback buttons (context-sensitive on selection).
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
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


class UpdateManagerWidget(QWidget):
    """Admin screen for offline update package import, apply, and rollback."""

    def __init__(self, client: ApiClient, state: AppState,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._can_edit = state.has_permission("admin.manage_config")
        self._build_ui()
        self.load_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        self._notif = NotificationBar(self)
        root.addWidget(self._notif)

        root.addWidget(QLabel("Update Packages"))

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Version", "Status", "Imported At", "File Hash", "Can Rollback"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        root.addWidget(self._table, stretch=1)

        if self._can_edit:
            btn_row = QHBoxLayout()
            import_btn = QPushButton("Import Package…")
            import_btn.clicked.connect(self._import_package)
            self._apply_btn = QPushButton("Apply")
            self._apply_btn.clicked.connect(self._apply_package)
            self._rollback_btn = QPushButton("Rollback")
            self._rollback_btn.clicked.connect(self._rollback_package)
            btn_row.addWidget(import_btn)
            btn_row.addWidget(self._apply_btn)
            btn_row.addWidget(self._rollback_btn)
            btn_row.addStretch()
            root.addLayout(btn_row)

        self._overlay = LoadingOverlay(self)

    def load_data(self) -> None:
        self._overlay.show()
        worker = ApiWorker(self._client.list_update_packages, offset=0, limit=20)
        worker.result.connect(self._on_loaded)
        worker.error.connect(self._on_error)
        worker.finished_clean.connect(self._overlay.hide)
        worker.start()

    def _on_loaded(self, data: dict) -> None:
        rows = data.get("items", [])
        self._table.setRowCount(0)
        for r in rows:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(r.get("version", "")))
            status_val = r.get("status", "")
            status_item = QTableWidgetItem(status_val)
            if status_val == "APPLIED":
                status_item.setForeground(Qt.GlobalColor.darkGreen)
            elif status_val == "ROLLED_BACK":
                status_item.setForeground(Qt.GlobalColor.gray)
            self._table.setItem(row, 1, status_item)
            imported = r.get("imported_at", "")
            self._table.setItem(row, 2, QTableWidgetItem(imported[:19] if imported else ""))
            file_hash = r.get("file_hash", "")
            self._table.setItem(row, 3, QTableWidgetItem(file_hash[:16] + "…" if len(file_hash) > 16 else file_hash))
            self._table.setItem(row, 4, QTableWidgetItem("Yes" if r.get("can_rollback") else "No"))
            self._table.item(row, 0).setData(Qt.ItemDataRole.UserRole, r)

    def _get_selected_package_id(self) -> Optional[str]:
        row = self._table.currentRow()
        if row < 0:
            return None
        record = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        return record.get("package_id") if record else None

    def _import_package(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Update Package", "", "ZIP Archives (*.zip)"
        )
        if not path:
            return
        self._overlay.show()
        try:
            with open(path, "rb") as f:
                content = f.read()
        except OSError as exc:
            self._overlay.hide()
            self._notif.show_message(f"Cannot read file: {exc}", "error")
            return
        import os
        filename = os.path.basename(path)
        worker = ApiWorker(self._client.import_update_package, content, filename)
        worker.result.connect(self._on_imported)
        worker.error.connect(self._on_error)
        worker.finished_clean.connect(self._overlay.hide)
        worker.start()

    def _on_imported(self, data: dict) -> None:
        self._notif.show_message(
            f"Package {data.get('version', '')} imported (PENDING).", "success"
        )
        self.load_data()

    def _apply_package(self) -> None:
        pkg_id = self._get_selected_package_id()
        if not pkg_id:
            return
        worker = ApiWorker(self._client.apply_update_package, pkg_id)
        worker.result.connect(lambda data: (
            self._notif.show_message(f"Package {data.get('version','')} applied.", "success"),
            self.load_data(),
        ))
        worker.error.connect(self._on_error)
        worker.start()

    def _rollback_package(self) -> None:
        pkg_id = self._get_selected_package_id()
        if not pkg_id:
            return
        worker = ApiWorker(self._client.rollback_update_package, pkg_id)
        worker.result.connect(lambda data: (
            self._notif.show_message(
                f"Rolled back to {data.get('version','')}.", "success"
            ),
            self.load_data(),
        ))
        worker.error.connect(self._on_error)
        worker.start()

    def _on_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Error: {msg}", "error")
