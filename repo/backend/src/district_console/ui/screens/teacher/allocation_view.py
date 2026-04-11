"""
Teacher classroom allocation / resource request view.

Teachers can browse PUBLISHED resources and see their current availability.
The "Request" button creates a record of intent; fulfilment is handled by
Librarians in the inventory system.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QInputDialog,
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


class AllocationWidget(QWidget):
    """
    Teacher view: browse published resources and submit allocation requests.
    """

    def __init__(self, client: ApiClient, state: AppState,
                 parent_window=None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._parent_window = parent_window
        self._worker: Optional[ApiWorker] = None

        self._build_ui()
        self.load_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        self._notif = NotificationBar(self)
        root.addWidget(self._notif)

        header = QHBoxLayout()
        heading = QLabel("Resource Allocations")
        heading.setProperty("heading", True)
        header.addWidget(heading)
        header.addStretch()
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.clicked.connect(self.load_data)
        header.addWidget(refresh_btn)
        root.addLayout(header)

        sub = QLabel(
            "Browse published resources. Right-click to request allocation."
        )
        sub.setProperty("subheading", True)
        root.addWidget(sub)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["Title", "Type", "ISBN", "Status"]
        )
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        root.addWidget(self._table, stretch=1)

        self._overlay = LoadingOverlay(self)

    def load_data(self) -> None:
        self._overlay.show()
        self._worker = ApiWorker(
            self._client.list_resources, offset=0, limit=100, status="PUBLISHED"
        )
        self._worker.result.connect(self._on_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.finished_clean.connect(self._overlay.hide)
        self._worker.start()

    def _on_loaded(self, data: dict) -> None:
        rows = data.get("items", [])
        self._table.setRowCount(0)
        for r in rows:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(r.get("title", "")))
            self._table.setItem(row, 1, QTableWidgetItem(r.get("resource_type", "")))
            self._table.setItem(row, 2, QTableWidgetItem(r.get("isbn") or ""))
            self._table.setItem(row, 3, QTableWidgetItem(r.get("status", "")))
            self._table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole, r.get("resource_id", "")
            )

    def _show_context_menu(self, pos) -> None:
        from PyQt6.QtWidgets import QMenu
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        title = self._table.item(row, 0).text()
        item = self._table.item(row, 0)
        resource_id = item.data(Qt.ItemDataRole.UserRole) if item else ""
        menu = QMenu(self)
        req = menu.addAction(f"Request Allocation for '{title}'")
        req.triggered.connect(
            lambda: self._submit_allocation_request(resource_id, title)
        )
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _submit_allocation_request(self, resource_id: str, title: str) -> None:
        if not resource_id:
            self._notif.show_message("Cannot determine resource ID.", "error")
            return
        self._worker = ApiWorker(self._client.request_allocation, resource_id)
        self._worker.result.connect(
            lambda _: self._notif.show_message(
                f"Allocation request for '{title}' submitted to librarian.",
                "success",
            )
        )
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def focus_search(self) -> None:
        pass  # No search bar in this view; satisfy shell interface

    def _on_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Load error: {msg}", "error")
