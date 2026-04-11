"""
Configuration center admin screen.

Four tabs: Dictionary | Workflow Nodes | Templates | Descriptors.
All mutating actions require admin.manage_config permission.
System entries are displayed with a lock indicator and Delete is disabled.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from district_console.ui.client import ApiClient, ApiError
from district_console.ui.state import AppState
from district_console.ui.utils.async_worker import ApiWorker
from district_console.ui.widgets.loading_overlay import LoadingOverlay
from district_console.ui.widgets.notification_bar import NotificationBar


class ConfigCenterWidget(QWidget):
    """Configuration center — tabs for all four config entity types."""

    def __init__(self, client: ApiClient, state: AppState,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._build_ui()
        self._dict_tab.load_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        self._notif = NotificationBar(self)
        root.addWidget(self._notif)

        tabs = QTabWidget()
        self._dict_tab = _DictionaryTab(self._client, self._state)
        self._nodes_tab = _WorkflowNodesTab(self._client, self._state)
        self._templates_tab = _TemplatesTab(self._client, self._state)
        self._descriptors_tab = _DescriptorsTab(self._client, self._state)

        tabs.addTab(self._dict_tab, "Dictionary")
        tabs.addTab(self._nodes_tab, "Workflow Nodes")
        tabs.addTab(self._templates_tab, "Templates")
        tabs.addTab(self._descriptors_tab, "Descriptors")
        tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(tabs, stretch=1)

        self._overlay = LoadingOverlay(self)

    def _on_tab_changed(self, idx: int) -> None:
        tab = self.findChild(QTabWidget).widget(idx)
        if hasattr(tab, "load_data"):
            tab.load_data()


class _DictionaryTab(QWidget):
    """Config dictionary CRUD — category/key/value/description table."""

    def __init__(self, client: ApiClient, state: AppState,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._can_edit = state.has_permission("admin.manage_config")
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Filter row
        filter_row = QHBoxLayout()
        self._category_filter = QLineEdit()
        self._category_filter.setPlaceholderText("Filter by category…")
        self._category_filter.textChanged.connect(lambda _: self.load_data())
        filter_row.addWidget(QLabel("Category:"))
        filter_row.addWidget(self._category_filter)
        filter_row.addStretch()
        if self._can_edit:
            add_btn = QPushButton("Add Entry")
            add_btn.clicked.connect(self._add_entry)
            filter_row.addWidget(add_btn)
        root.addLayout(filter_row)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Category", "Key", "Value", "Description", "System"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        root.addWidget(self._table, stretch=1)

        if self._can_edit:
            btn_row = QHBoxLayout()
            self._edit_btn = QPushButton("Edit")
            self._edit_btn.clicked.connect(self._edit_entry)
            self._delete_btn = QPushButton("Delete")
            self._delete_btn.clicked.connect(self._delete_entry)
            btn_row.addWidget(self._edit_btn)
            btn_row.addWidget(self._delete_btn)
            btn_row.addStretch()
            root.addLayout(btn_row)

    def load_data(self) -> None:
        cat = self._category_filter.text().strip()
        params = {"offset": 0, "limit": 100}
        if cat:
            params["category"] = cat
        worker = ApiWorker(self._client.list_config, **params)
        worker.result.connect(self._on_loaded)
        worker.error.connect(self._on_error)
        worker.start()

    def _on_loaded(self, data: dict) -> None:
        rows = data.get("items", [])
        self._table.setRowCount(0)
        for r in rows:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(r.get("category", "")))
            self._table.setItem(row, 1, QTableWidgetItem(r.get("key", "")))
            self._table.setItem(row, 2, QTableWidgetItem(r.get("value", "")))
            self._table.setItem(row, 3, QTableWidgetItem(r.get("description", "")))
            sys_item = QTableWidgetItem("🔒" if r.get("is_system") else "")
            self._table.setItem(row, 4, sys_item)
            self._table.item(row, 0).setData(Qt.ItemDataRole.UserRole, r)

    def _add_entry(self) -> None:
        dlg = _ConfigEntryDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            category, key, value, desc = dlg.get_values()
            worker = ApiWorker(self._client.upsert_config, category, key, value, desc)
            worker.result.connect(lambda _: self.load_data())
            worker.error.connect(self._on_error)
            worker.start()

    def _edit_entry(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        record = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        dlg = _ConfigEntryDialog(self, record)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            category, key, value, desc = dlg.get_values()
            worker = ApiWorker(self._client.upsert_config, category, key, value, desc)
            worker.result.connect(lambda _: self.load_data())
            worker.error.connect(self._on_error)
            worker.start()

    def _delete_entry(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        record = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if record.get("is_system"):
            return  # silently ignore — button should be visually disabled
        entry_id = record.get("entry_id", "")
        worker = ApiWorker(self._client.delete_config, entry_id)
        worker.result.connect(lambda _: self.load_data())
        worker.error.connect(self._on_error)
        worker.start()

    def _on_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        # Bubble up to parent notif bar
        parent = self.parent()
        while parent and not hasattr(parent, "_notif"):
            parent = parent.parent()
        if parent:
            parent._notif.show_message(f"Error: {msg}", "error")


class _ConfigEntryDialog(QDialog):
    def __init__(self, parent=None, record: dict = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Config Entry")
        form = QFormLayout(self)
        self._cat = QLineEdit(record.get("category", "") if record else "")
        self._key = QLineEdit(record.get("key", "") if record else "")
        self._val = QLineEdit(record.get("value", "") if record else "")
        self._desc = QLineEdit(record.get("description", "") if record else "")
        form.addRow("Category:", self._cat)
        form.addRow("Key:", self._key)
        form.addRow("Value:", self._val)
        form.addRow("Description:", self._desc)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def get_values(self):
        return (
            self._cat.text().strip(),
            self._key.text().strip(),
            self._val.text().strip(),
            self._desc.text().strip(),
        )


class _WorkflowNodesTab(QWidget):
    """Workflow transition node viewer/editor."""

    def __init__(self, client: ApiClient, state: AppState,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._can_edit = state.has_permission("admin.manage_config")
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Workflow", "From", "To", "Required Role", "Condition"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        root.addWidget(self._table, stretch=1)

        if self._can_edit:
            btn_row = QHBoxLayout()
            add_btn = QPushButton("Add Node")
            add_btn.clicked.connect(self._add_node)
            del_btn = QPushButton("Delete")
            del_btn.clicked.connect(self._delete_node)
            btn_row.addWidget(add_btn)
            btn_row.addWidget(del_btn)
            btn_row.addStretch()
            root.addLayout(btn_row)

    def load_data(self) -> None:
        worker = ApiWorker(self._client.list_workflow_nodes)
        worker.result.connect(self._on_loaded)
        worker.error.connect(lambda _: None)
        worker.start()

    def _on_loaded(self, data: list) -> None:
        self._table.setRowCount(0)
        for r in data:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(r.get("workflow_name", "")))
            self._table.setItem(row, 1, QTableWidgetItem(r.get("from_state", "")))
            self._table.setItem(row, 2, QTableWidgetItem(r.get("to_state", "")))
            self._table.setItem(row, 3, QTableWidgetItem(r.get("required_role", "")))
            self._table.setItem(row, 4, QTableWidgetItem(r.get("condition_json") or ""))
            self._table.item(row, 0).setData(Qt.ItemDataRole.UserRole, r)

    def _add_node(self) -> None:
        from PyQt6.QtWidgets import QInputDialog, QComboBox
        wf, ok = QInputDialog.getText(self, "Workflow Node", "Workflow name:")
        if not ok or not wf.strip():
            return
        frm, ok = QInputDialog.getText(self, "Workflow Node", "From state:")
        if not ok:
            return
        to, ok = QInputDialog.getText(self, "Workflow Node", "To state:")
        if not ok:
            return
        role, ok = QInputDialog.getItem(
            self, "Workflow Node", "Required role:",
            ["ADMINISTRATOR", "LIBRARIAN", "TEACHER", "COUNSELOR", "REVIEWER"], 0, False
        )
        if not ok:
            return
        worker = ApiWorker(
            self._client.create_workflow_node, wf.strip(), frm.strip(), to.strip(), role, None
        )
        worker.result.connect(lambda _: self.load_data())
        worker.error.connect(lambda _: None)
        worker.start()

    def _delete_node(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        record = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        node_id = record.get("node_id", "")
        worker = ApiWorker(self._client.delete_workflow_node, node_id)
        worker.result.connect(lambda _: self.load_data())
        worker.error.connect(lambda _: None)
        worker.start()


class _TemplatesTab(QWidget):
    """Notification template viewer/editor."""

    def __init__(self, client: ApiClient, state: AppState,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._can_edit = state.has_permission("admin.manage_config")
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Name", "Event Type", "Subject", "Active"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        root.addWidget(self._table, stretch=1)

        if self._can_edit:
            btn_row = QHBoxLayout()
            edit_btn = QPushButton("Edit Template")
            edit_btn.clicked.connect(self._edit_template)
            btn_row.addWidget(edit_btn)
            btn_row.addStretch()
            root.addLayout(btn_row)

    def load_data(self) -> None:
        worker = ApiWorker(self._client.list_notification_templates)
        worker.result.connect(self._on_loaded)
        worker.error.connect(lambda _: None)
        worker.start()

    def _on_loaded(self, data: list) -> None:
        self._table.setRowCount(0)
        for r in data:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(r.get("name", "")))
            self._table.setItem(row, 1, QTableWidgetItem(r.get("event_type", "")))
            self._table.setItem(row, 2, QTableWidgetItem(r.get("subject_template", "")))
            self._table.setItem(row, 3, QTableWidgetItem("Yes" if r.get("is_active") else "No"))
            self._table.item(row, 0).setData(Qt.ItemDataRole.UserRole, r)

    def _edit_template(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        record = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        dlg = _TemplateEditDialog(self, record)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            vals = dlg.get_values()
            worker = ApiWorker(self._client.upsert_notification_template, **vals)
            worker.result.connect(lambda _: self.load_data())
            worker.error.connect(lambda _: None)
            worker.start()


class _TemplateEditDialog(QDialog):
    def __init__(self, parent=None, record: dict = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Template")
        self.resize(500, 300)
        form = QFormLayout(self)
        self._name = QLineEdit(record.get("name", "") if record else "")
        self._event_type = QLineEdit(record.get("event_type", "") if record else "")
        self._subject = QLineEdit(record.get("subject_template", "") if record else "")
        self._body = QTextEdit()
        self._body.setPlainText(record.get("body_template", "") if record else "")
        form.addRow("Name:", self._name)
        form.addRow("Event Type:", self._event_type)
        form.addRow("Subject:", self._subject)
        form.addRow("Body:", self._body)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def get_values(self) -> dict:
        return {
            "name": self._name.text().strip(),
            "event_type": self._event_type.text().strip(),
            "subject_template": self._subject.text().strip(),
            "body_template": self._body.toPlainText(),
            "is_active": True,
        }


class _DescriptorsTab(QWidget):
    """District descriptor viewer/editor."""

    def __init__(self, client: ApiClient, state: AppState,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._can_edit = state.has_permission("admin.manage_config")
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Key", "Value", "Description", "Region"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        root.addWidget(self._table, stretch=1)

        if self._can_edit:
            btn_row = QHBoxLayout()
            add_btn = QPushButton("Add / Edit Descriptor")
            add_btn.clicked.connect(self._upsert_descriptor)
            btn_row.addWidget(add_btn)
            btn_row.addStretch()
            root.addLayout(btn_row)

    def load_data(self) -> None:
        worker = ApiWorker(self._client.list_district_descriptors)
        worker.result.connect(self._on_loaded)
        worker.error.connect(lambda _: None)
        worker.start()

    def _on_loaded(self, data: list) -> None:
        self._table.setRowCount(0)
        for r in data:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(r.get("key", "")))
            self._table.setItem(row, 1, QTableWidgetItem(r.get("value", "")))
            self._table.setItem(row, 2, QTableWidgetItem(r.get("description", "")))
            self._table.setItem(row, 3, QTableWidgetItem(r.get("region") or ""))
            self._table.item(row, 0).setData(Qt.ItemDataRole.UserRole, r)

    def _upsert_descriptor(self) -> None:
        row = self._table.currentRow()
        record = (
            self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if row >= 0 else None
        )
        from PyQt6.QtWidgets import QInputDialog
        key = record.get("key", "") if record else ""
        if not key:
            key, ok = QInputDialog.getText(self, "Descriptor", "Key:")
            if not ok or not key.strip():
                return
        value, ok = QInputDialog.getText(
            self, "Descriptor", "Value:", text=record.get("value", "") if record else ""
        )
        if not ok:
            return
        worker = ApiWorker(
            self._client.upsert_district_descriptor,
            key.strip(), value.strip(), "", None
        )
        worker.result.connect(lambda _: self.load_data())
        worker.error.connect(lambda _: None)
        worker.start()
