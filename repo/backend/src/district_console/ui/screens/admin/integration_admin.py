"""
Integration client administration screen.

Top: client list table (name, status, created_at).
Middle: key rotation panel (Rotate / Commit buttons).
Bottom: outbound event log table (event_type, status, retry_count, last_error).
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from district_console.ui.client import ApiClient, ApiError
from district_console.ui.state import AppState
from district_console.ui.utils.async_worker import ApiWorker
from district_console.ui.widgets.notification_bar import NotificationBar


class IntegrationAdminWidget(QWidget):
    """Admin screen for integration client lifecycle and outbound event log."""

    def __init__(self, client: ApiClient, state: AppState,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._can_edit = state.has_permission("admin.manage_config")
        self._selected_client_id: Optional[str] = None
        self._build_ui()
        self.load_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        self._notif = NotificationBar(self)
        root.addWidget(self._notif)

        # Client list
        client_group = QGroupBox("Integration Clients")
        cv = QVBoxLayout(client_group)
        self._client_table = QTableWidget(0, 4)
        self._client_table.setHorizontalHeaderLabels(["Name", "Description", "Active", "Created"])
        self._client_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._client_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._client_table.selectionModel().selectionChanged.connect(self._on_client_selected)
        cv.addWidget(self._client_table)

        if self._can_edit:
            client_btns = QHBoxLayout()
            add_btn = QPushButton("Register Client")
            add_btn.clicked.connect(self._register_client)
            deact_btn = QPushButton("Deactivate")
            deact_btn.clicked.connect(self._deactivate_client)
            client_btns.addWidget(add_btn)
            client_btns.addWidget(deact_btn)
            client_btns.addStretch()
            cv.addLayout(client_btns)

        root.addWidget(client_group)

        # Key rotation
        if self._can_edit:
            key_group = QGroupBox("HMAC Key Rotation")
            kv = QHBoxLayout(key_group)
            self._rotate_btn = QPushButton("Initiate Rotation")
            self._rotate_btn.clicked.connect(self._rotate_key)
            self._commit_btn = QPushButton("Commit Rotation")
            self._commit_btn.clicked.connect(self._commit_rotation)
            kv.addWidget(self._rotate_btn)
            kv.addWidget(self._commit_btn)
            kv.addStretch()
            root.addWidget(key_group)

        # Outbound event log
        event_group = QGroupBox("Outbound Event Log")
        ev = QVBoxLayout(event_group)
        self._event_table = QTableWidget(0, 5)
        self._event_table.setHorizontalHeaderLabels(
            ["Event Type", "Status", "Retry Count", "Delivered At", "Last Error"]
        )
        self._event_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._event_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        ev.addWidget(self._event_table)

        if self._can_edit:
            retry_btn = QPushButton("Retry Pending")
            retry_btn.clicked.connect(self._retry_events)
            ev.addWidget(retry_btn)

        root.addWidget(event_group, stretch=1)

    def load_data(self) -> None:
        worker = ApiWorker(self._client.list_integration_clients)
        worker.result.connect(self._on_clients_loaded)
        worker.error.connect(self._on_error)
        worker.start()

        worker2 = ApiWorker(self._client.list_outbound_events, offset=0, limit=50)
        worker2.result.connect(self._on_events_loaded)
        worker2.error.connect(self._on_error)
        worker2.start()

    def _on_clients_loaded(self, data: list) -> None:
        self._client_table.setRowCount(0)
        for r in data:
            row = self._client_table.rowCount()
            self._client_table.insertRow(row)
            self._client_table.setItem(row, 0, QTableWidgetItem(r.get("name", "")))
            self._client_table.setItem(row, 1, QTableWidgetItem(r.get("description", "")))
            active_item = QTableWidgetItem("Yes" if r.get("is_active") else "No")
            if not r.get("is_active"):
                active_item.setForeground(Qt.GlobalColor.gray)
            self._client_table.setItem(row, 2, active_item)
            created = r.get("created_at", "")
            self._client_table.setItem(row, 3, QTableWidgetItem(created[:19] if created else ""))
            self._client_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, r)

    def _on_events_loaded(self, data: dict) -> None:
        rows = data.get("items", [])
        self._event_table.setRowCount(0)
        for r in rows:
            row = self._event_table.rowCount()
            self._event_table.insertRow(row)
            self._event_table.setItem(row, 0, QTableWidgetItem(r.get("event_type", "")))
            status_item = QTableWidgetItem(r.get("status", ""))
            if r.get("status") == "FAILED":
                status_item.setForeground(Qt.GlobalColor.red)
            elif r.get("status") == "DELIVERED":
                status_item.setForeground(Qt.GlobalColor.darkGreen)
            self._event_table.setItem(row, 1, status_item)
            self._event_table.setItem(row, 2, QTableWidgetItem(str(r.get("retry_count", 0))))
            delivered = r.get("delivered_at", "") or ""
            self._event_table.setItem(row, 3, QTableWidgetItem(delivered[:19] if delivered else ""))
            self._event_table.setItem(row, 4, QTableWidgetItem(r.get("last_error") or ""))

    def _on_client_selected(self) -> None:
        row = self._client_table.currentRow()
        if row < 0:
            self._selected_client_id = None
            return
        record = self._client_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        self._selected_client_id = record.get("client_id") if record else None

    def _register_client(self) -> None:
        dlg = _RegisterClientDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name, desc = dlg.get_values()
            worker = ApiWorker(self._client.create_integration_client, name, desc)
            worker.result.connect(self._on_client_created)
            worker.error.connect(self._on_error)
            worker.start()

    def _on_client_created(self, data: dict) -> None:
        key_val = data.get("initial_key", {}).get("key_value", "")
        self._notif.show_message(
            f"Client created. Initial key (store securely): {key_val[:12]}…",
            "success",
            timeout_ms=0,
        )
        self.load_data()

    def _deactivate_client(self) -> None:
        if not self._selected_client_id:
            return
        worker = ApiWorker(self._client.deactivate_integration_client, self._selected_client_id)
        worker.result.connect(lambda _: self.load_data())
        worker.error.connect(self._on_error)
        worker.start()

    def _rotate_key(self) -> None:
        if not self._selected_client_id:
            return
        worker = ApiWorker(self._client.rotate_integration_key, self._selected_client_id)
        worker.result.connect(lambda data: self._notif.show_message(
            f"Next key generated. Key: {data.get('key_value','')[:12]}… — update client config, then commit.",
            "info", timeout_ms=0
        ))
        worker.error.connect(self._on_error)
        worker.start()

    def _commit_rotation(self) -> None:
        if not self._selected_client_id:
            return
        worker = ApiWorker(self._client.commit_integration_key_rotation, self._selected_client_id)
        worker.result.connect(lambda _: self._notif.show_message("Key rotation committed.", "success"))
        worker.error.connect(self._on_error)
        worker.start()

    def _retry_events(self) -> None:
        worker = ApiWorker(self._client.retry_outbound_events)
        worker.result.connect(lambda data: self._notif.show_message(
            f"Retry: {data.get('delivered',0)} delivered, {data.get('failed',0)} failed.", "info"
        ))
        worker.error.connect(self._on_error)
        worker.start()

    def _on_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Error: {msg}", "error")


class _RegisterClientDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Register Integration Client")
        form = QFormLayout(self)
        self._name = QLineEdit()
        self._desc = QLineEdit()
        form.addRow("Name:", self._name)
        form.addRow("Description:", self._desc)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def get_values(self) -> tuple[str, str]:
        return self._name.text().strip(), self._desc.text().strip()
