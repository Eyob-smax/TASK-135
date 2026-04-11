"""
Relocation workflow screen — browse stock relocations.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
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


class RelocationWidget(QWidget):
    """Stock relocation history viewer. Requires inventory.relocate permission."""

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
        heading = QLabel("Stock Relocations")
        heading.setProperty("heading", True)
        header.addWidget(heading)
        header.addStretch()
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.clicked.connect(self.load_data)
        header.addWidget(refresh_btn)
        root.addLayout(header)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Item ID", "From Location", "To Location", "Qty", "Date"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        root.addWidget(self._table, stretch=1)

        self._overlay = LoadingOverlay(self)

    def load_data(self) -> None:
        self._overlay.show()
        self._worker = ApiWorker(self._client.list_relocations)
        self._worker.result.connect(self._on_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.finished_clean.connect(self._overlay.hide)
        self._worker.start()

    def _on_loaded(self, data: dict) -> None:
        items = data.get("items", [])
        self._table.setRowCount(len(items))
        for row, r in enumerate(items):
            self._table.setItem(row, 0, QTableWidgetItem(r.get("item_id", "")[:8]))
            self._table.setItem(row, 1, QTableWidgetItem(r.get("from_location_id", "")[:8]))
            self._table.setItem(row, 2, QTableWidgetItem(r.get("to_location_id", "")[:8]))
            self._table.setItem(row, 3, QTableWidgetItem(str(r.get("quantity", ""))))
            created_at = r.get("created_at", "")
            self._table.setItem(row, 4, QTableWidgetItem(created_at[:19] if created_at else ""))

    def _on_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Load error: {msg}", "error")

    def focus_search(self) -> None:
        pass
