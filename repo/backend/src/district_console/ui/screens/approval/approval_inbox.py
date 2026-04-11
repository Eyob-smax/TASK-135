"""
Approval task inbox.

Shows:
  - IN_REVIEW resources (for Reviewer/Admin to publish or send back)
  - CLOSED count sessions awaiting approval (for Admin)

Each section uses a separate table with role-gated action buttons.
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
    QTabWidget,
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


class ApprovalInboxWidget(QWidget):
    """
    Multi-tab approval inbox for Reviewer and Administrator roles.
    """

    def __init__(self, client: ApiClient, state: AppState,
                 parent_window=None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._parent_window = parent_window
        self._worker: Optional[ApiWorker] = None
        self._count_worker: Optional[ApiWorker] = None
        self._count_table: Optional[QTableWidget] = None

        self._build_ui()
        self.load_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        self._notif = NotificationBar(self)
        root.addWidget(self._notif)

        header = QHBoxLayout()
        heading = QLabel("Approval Inbox")
        heading.setProperty("heading", True)
        header.addWidget(heading)
        header.addStretch()
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.clicked.connect(self.load_data)
        header.addWidget(refresh_btn)
        root.addLayout(header)

        self._tabs = QTabWidget()

        # Resource review tab
        if self._state.has_permission("resources.publish"):
            self._review_tab = self._build_review_tab()
            self._tabs.addTab(self._review_tab, "Resource Reviews")

        # Count approvals tab
        if self._state.has_permission("inventory.approve_count"):
            self._count_approval_tab = self._build_count_approvals_tab()
            self._tabs.addTab(self._count_approval_tab, "Count Approvals")

        root.addWidget(self._tabs, stretch=1)
        self._overlay = LoadingOverlay(self)

    def _build_review_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)

        sub = QLabel("Resources submitted for your review. Right-click to act.")
        sub.setProperty("subheading", True)
        layout.addWidget(sub)

        self._review_table = QTableWidget(0, 5)
        self._review_table.setHorizontalHeaderLabels(
            ["Title", "Type", "ISBN", "Created By", "Updated At"]
        )
        self._review_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._review_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._review_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._review_table.customContextMenuRequested.connect(
            self._show_review_menu
        )
        layout.addWidget(self._review_table)

        self._review_count_lbl = QLabel("")
        self._review_count_lbl.setProperty("subheading", True)
        layout.addWidget(self._review_count_lbl)
        return tab

    def _build_count_approvals_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        sub = QLabel("Count sessions awaiting approval. Right-click to approve.")
        sub.setProperty("subheading", True)
        layout.addWidget(sub)
        self._count_table = QTableWidget(0, 4)
        self._count_table.setHorizontalHeaderLabels(
            ["Session ID", "Mode", "Created By", "Closed At"]
        )
        self._count_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._count_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._count_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._count_table.customContextMenuRequested.connect(self._show_count_menu)
        layout.addWidget(self._count_table)
        return tab

    # ------------------------------------------------------------------ #
    # Data                                                                #
    # ------------------------------------------------------------------ #

    def load_data(self) -> None:
        if self._state.has_permission("resources.publish"):
            self._load_reviews()
        if self._state.has_permission("inventory.approve_count"):
            self._load_count_approvals()

    def _load_count_approvals(self) -> None:
        self._overlay.show()
        self._count_worker = ApiWorker(
            self._client.list_count_sessions, status="CLOSED"
        )
        self._count_worker.result.connect(self._on_count_approvals_loaded)
        self._count_worker.error.connect(self._on_error)
        self._count_worker.finished_clean.connect(self._overlay.hide)
        self._count_worker.start()

    def _on_count_approvals_loaded(self, data: dict) -> None:
        if self._count_table is None:
            return
        items = data.get("items", [])
        self._count_table.setRowCount(len(items))
        for row, s in enumerate(items):
            self._count_table.setItem(row, 0, QTableWidgetItem(s.get("session_id", "")[:8] + "…"))
            self._count_table.setItem(row, 1, QTableWidgetItem(s.get("mode", "")))
            self._count_table.setItem(row, 2, QTableWidgetItem(s.get("created_by", "")[:8]))
            closed_at = s.get("closed_at", "") or ""
            self._count_table.setItem(row, 3, QTableWidgetItem(closed_at[:19]))
            for col in range(4):
                cell = self._count_table.item(row, col)
                if cell:
                    cell.setData(Qt.ItemDataRole.UserRole, s.get("session_id", ""))

    def _load_reviews(self) -> None:
        self._overlay.show()
        self._worker = ApiWorker(
            self._client.list_resources,
            offset=0, limit=100, status="IN_REVIEW"
        )
        self._worker.result.connect(self._on_reviews_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.finished_clean.connect(self._overlay.hide)
        self._worker.start()

    def _on_reviews_loaded(self, data: dict) -> None:
        items = data.get("items", [])
        self._review_table.setRowCount(0)
        for r in items:
            row = self._review_table.rowCount()
            self._review_table.insertRow(row)
            self._review_table.setItem(row, 0, QTableWidgetItem(r.get("title", "")))
            self._review_table.setItem(row, 1, QTableWidgetItem(r.get("resource_type", "")))
            self._review_table.setItem(row, 2, QTableWidgetItem(r.get("isbn") or ""))
            self._review_table.setItem(row, 3, QTableWidgetItem(r.get("created_by", "")))
            upd = r.get("updated_at", "")
            self._review_table.setItem(row, 4, QTableWidgetItem(upd[:19] if upd else ""))
            self._review_table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole, r.get("resource_id", "")
            )
        count = len(items)
        self._review_count_lbl.setText(
            f"{count} resource(s) awaiting review"
            + (" — action required" if count > 0 else "")
        )
        if count > 0:
            self._review_count_lbl.setStyleSheet("color: #9d5d00; font-weight: 600;")
        else:
            self._review_count_lbl.setStyleSheet("")

    # ------------------------------------------------------------------ #
    # Context menus                                                       #
    # ------------------------------------------------------------------ #

    def _show_review_menu(self, pos) -> None:
        row = self._review_table.rowAt(pos.y())
        if row < 0:
            return
        resource_id = self._review_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        title = self._review_table.item(row, 0).text()

        menu = QMenu(self)
        pub = menu.addAction("✓ Publish…")
        pub.triggered.connect(lambda: self._do_publish(resource_id, title))
        reject = menu.addAction("✕ Send Back (Unpublish)…")
        reject.triggered.connect(lambda: self._do_reject(resource_id, title))
        menu.exec(self._review_table.viewport().mapToGlobal(pos))

    def _do_publish(self, resource_id: str, title: str) -> None:
        notes, ok = QInputDialog.getMultiLineText(
            self, f"Publish '{title}'",
            "Reviewer Notes (required — will be recorded in audit log):"
        )
        if ok and notes.strip():
            worker = ApiWorker(
                self._client.publish_resource, resource_id, notes.strip()
            )
            worker.result.connect(lambda _: (
                self._notif.show_message(f"'{title}' published.", "success"),
                self._load_reviews(),
            ))
            worker.error.connect(self._on_action_error)
            worker.start()
            self._worker = worker
        elif ok:
            self._notif.show_message(
                "Reviewer notes are required to publish.", "warning"
            )

    def _do_reject(self, resource_id: str, title: str) -> None:
        notes, ok = QInputDialog.getMultiLineText(
            self, f"Send Back '{title}'",
            "Reason for sending back (required):"
        )
        if ok and notes.strip():
            worker = ApiWorker(
                self._client.unpublish_resource, resource_id, notes.strip()
            )
            worker.result.connect(lambda _: (
                self._notif.show_message(f"'{title}' sent back.", "info"),
                self._load_reviews(),
            ))
            worker.error.connect(self._on_action_error)
            worker.start()
            self._worker = worker
        elif ok:
            self._notif.show_message("Notes are required.", "warning")

    def _show_count_menu(self, pos) -> None:
        if self._count_table is None:
            return
        row = self._count_table.rowAt(pos.y())
        if row < 0:
            return
        item = self._count_table.item(row, 0)
        if item is None:
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        approve_act = menu.addAction("✓ Approve Count Session…")
        approve_act.triggered.connect(lambda: self._approve_count(session_id))
        menu.exec(self._count_table.viewport().mapToGlobal(pos))

    def _approve_count(self, session_id: str) -> None:
        notes, ok = QInputDialog.getText(self, "Approve Count Session", "Approval notes:")
        if not ok:
            return
        worker = ApiWorker(self._client.approve_count_session, session_id, notes)
        worker.result.connect(lambda _: (
            self._notif.show_message("Count session approved.", "success"),
            self._load_count_approvals(),
        ))
        worker.error.connect(self._on_action_error)
        worker.start()
        self._count_worker = worker

    def _on_action_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Action failed: {msg}", "error")

    def _on_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Load error: {msg}", "error")
