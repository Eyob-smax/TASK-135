"""
Review queue — lists IN_REVIEW resources for Reviewer / Administrator roles.

Reviewers can publish or reject directly from the queue.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QInputDialog,
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


class ReviewQueueWidget(QWidget):
    """List of IN_REVIEW resources with publish/reject actions."""

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

        toolbar = QHBoxLayout()
        heading = QLabel("Resources Awaiting Review")
        heading.setProperty("heading", True)
        toolbar.addWidget(heading)
        toolbar.addStretch()
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.clicked.connect(self.load_data)
        toolbar.addWidget(refresh_btn)
        root.addLayout(toolbar)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Title", "Type", "ISBN", "Submitted By", "Updated At"]
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

        self._count_lbl = QLabel("")
        self._count_lbl.setProperty("subheading", True)
        root.addWidget(self._count_lbl)

        self._overlay = LoadingOverlay(self)

    def load_data(self) -> None:
        self._overlay.show()
        self._worker = ApiWorker(
            self._client.list_resources,
            offset=0, limit=100, status="IN_REVIEW"
        )
        self._worker.result.connect(self._on_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.finished_clean.connect(self._overlay.hide)
        self._worker.start()

    def _on_loaded(self, data: dict) -> None:
        items = data.get("items", [])
        self._table.setRowCount(0)
        for r in items:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(r.get("title", "")))
            self._table.setItem(row, 1, QTableWidgetItem(r.get("resource_type", "")))
            self._table.setItem(row, 2, QTableWidgetItem(r.get("isbn") or ""))
            self._table.setItem(row, 3, QTableWidgetItem(r.get("created_by", "")))
            upd = r.get("updated_at", "")
            self._table.setItem(row, 4, QTableWidgetItem(upd[:19] if upd else ""))
            self._table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole, r.get("resource_id", "")
            )
        self._count_lbl.setText(f"{len(items)} resource(s) awaiting review")

    def _on_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Load error: {msg}", "error")

    def _show_context_menu(self, pos) -> None:
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        resource_id = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        if self._state.has_permission("resources.publish"):
            pub = menu.addAction("Publish…")
            pub.triggered.connect(lambda: self._do_publish(resource_id))
            unpub = menu.addAction("Send Back (Unpublish)…")
            unpub.triggered.connect(lambda: self._do_reject(resource_id))
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _do_publish(self, resource_id: str) -> None:
        notes, ok = QInputDialog.getMultiLineText(
            self, "Publish", "Reviewer Notes (required):"
        )
        if ok and notes.strip():
            worker = ApiWorker(
                self._client.publish_resource, resource_id, notes.strip()
            )
            worker.result.connect(lambda _: (
                self._notif.show_message("Published.", "success"),
                self.load_data(),
            ))
            worker.error.connect(
                lambda e: self._notif.show_message(
                    f"Publish failed: {e.message if isinstance(e, ApiError) else e}",
                    "error"
                )
            )
            worker.start()
            self._worker = worker

    def _do_reject(self, resource_id: str) -> None:
        notes, ok = QInputDialog.getMultiLineText(
            self, "Unpublish / Reject", "Notes (required):"
        )
        if ok and notes.strip():
            worker = ApiWorker(
                self._client.unpublish_resource, resource_id, notes.strip()
            )
            worker.result.connect(lambda _: (
                self._notif.show_message("Sent back.", "info"),
                self.load_data(),
            ))
            worker.error.connect(
                lambda e: self._notif.show_message(str(e), "error")
            )
            worker.start()
            self._worker = worker
