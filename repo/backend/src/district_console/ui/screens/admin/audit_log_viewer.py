"""
Audit log viewer admin screen.

Three tabs:
  - All Events: filterable by entity_type, action, actor, date range.
  - Security Events: login/lockout/logout/key-rotation events only.
  - Checkpoints: non-completed checkpoint status for recovery visibility.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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


class AuditLogViewerWidget(QWidget):
    """Immutable audit trail browser with security and checkpoint tabs."""

    def __init__(self, client: ApiClient, state: AppState,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._build_ui()
        self._all_tab.load_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        self._notif = NotificationBar(self)
        root.addWidget(self._notif)

        tabs = QTabWidget()
        self._all_tab = _AllEventsTab(self._client, self._state)
        self._security_tab = _SecurityEventsTab(self._client, self._state)
        self._checkpoint_tab = _CheckpointTab(self._client, self._state)

        tabs.addTab(self._all_tab, "All Events")
        tabs.addTab(self._security_tab, "Security")
        tabs.addTab(self._checkpoint_tab, "Checkpoints")
        tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(tabs, stretch=1)

        self._overlay = LoadingOverlay(self)

    def _on_tab_changed(self, idx: int) -> None:
        tab = self.findChild(QTabWidget).widget(idx)
        if hasattr(tab, "load_data"):
            tab.load_data()


class _AllEventsTab(QWidget):
    """Filterable audit event browser."""

    def __init__(self, client: ApiClient, state: AppState,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        filter_group = QGroupBox("Filters")
        fg = QFormLayout(filter_group)
        self._entity_type_edit = QLineEdit()
        self._action_edit = QLineEdit()
        self._actor_edit = QLineEdit()
        fg.addRow("Entity Type:", self._entity_type_edit)
        fg.addRow("Action:", self._action_edit)
        fg.addRow("Actor ID:", self._actor_edit)
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self.load_data)
        fg.addRow(search_btn)
        root.addWidget(filter_group)

        self._table = _AuditTable()
        root.addWidget(self._table, stretch=1)

    def load_data(self) -> None:
        params = {"offset": 0, "limit": 50}
        et = self._entity_type_edit.text().strip()
        act = self._action_edit.text().strip()
        actor = self._actor_edit.text().strip()
        if et:
            params["entity_type"] = et
        if act:
            params["action"] = act
        if actor:
            params["actor_id"] = actor
        worker = ApiWorker(self._client.list_audit_events, **params)
        worker.result.connect(lambda data: self._table.populate(data.get("items", [])))
        worker.error.connect(lambda _: None)
        worker.start()


class _SecurityEventsTab(QWidget):
    """Login, lockout, and key-rotation audit events."""

    def __init__(self, client: ApiClient, state: AppState,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        self._table = _AuditTable()
        root.addWidget(self._table, stretch=1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_data)
        root.addWidget(refresh_btn)

    def load_data(self) -> None:
        worker = ApiWorker(self._client.list_security_audit_events, offset=0, limit=50)
        worker.result.connect(lambda data: self._table.populate(data.get("items", [])))
        worker.error.connect(lambda _: None)
        worker.start()


class _CheckpointTab(QWidget):
    """Non-completed checkpoint status for recovery visibility."""

    def __init__(self, client: ApiClient, state: AppState,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(QLabel("Active, Failed, and Abandoned checkpoints requiring attention:"))

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Job Type", "Job ID", "Status", "Updated At", "State"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        root.addWidget(self._table, stretch=1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_data)
        root.addWidget(refresh_btn)

    def load_data(self) -> None:
        worker = ApiWorker(self._client.list_checkpoint_status)
        worker.result.connect(self._on_loaded)
        worker.error.connect(lambda _: None)
        worker.start()

    def _on_loaded(self, data: list) -> None:
        self._table.setRowCount(0)
        for r in data:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(r.get("job_type", "")))
            self._table.setItem(row, 1, QTableWidgetItem(r.get("job_id", "")))
            status_val = r.get("status", "")
            status_item = QTableWidgetItem(status_val)
            if status_val == "FAILED":
                status_item.setForeground(Qt.GlobalColor.red)
            elif status_val == "ABANDONED":
                status_item.setForeground(Qt.GlobalColor.gray)
            self._table.setItem(row, 2, status_item)
            updated = r.get("updated_at", "")
            self._table.setItem(row, 3, QTableWidgetItem(updated[:19] if updated else ""))
            self._table.setItem(row, 4, QTableWidgetItem(r.get("state_json", "")[:60]))


class _AuditTable(QTableWidget):
    """Reusable audit event table widget."""

    def __init__(self, parent=None) -> None:
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels(
            ["Timestamp", "Entity Type", "Action", "Actor ID", "Entity ID"]
        )
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.horizontalHeader().setStretchLastSection(True)

    def populate(self, rows: list) -> None:
        self.setRowCount(0)
        for r in rows:
            row = self.rowCount()
            self.insertRow(row)
            ts = r.get("timestamp", "")
            self.setItem(row, 0, QTableWidgetItem(ts[:19] if ts else ""))
            self.setItem(row, 1, QTableWidgetItem(r.get("entity_type", "")))
            self.setItem(row, 2, QTableWidgetItem(r.get("action", "")))
            self.setItem(row, 3, QTableWidgetItem(r.get("actor_id", "")[:8] + "…"))
            self.setItem(row, 4, QTableWidgetItem(r.get("entity_id", "")[:8] + "…"))
