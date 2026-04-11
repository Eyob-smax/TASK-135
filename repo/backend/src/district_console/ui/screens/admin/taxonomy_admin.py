"""
Taxonomy administration screen.

Left panel: category tree (QTreeWidget, hierarchical).
Right panel: category editor + validation rules table.
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
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from district_console.ui.client import ApiClient, ApiError
from district_console.ui.state import AppState
from district_console.ui.utils.async_worker import ApiWorker
from district_console.ui.widgets.notification_bar import NotificationBar


class TaxonomyAdminWidget(QWidget):
    """Category tree + validation rules administration."""

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

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: category tree
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Categories"))
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Name", "Slug", "Active"])
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        lv.addWidget(self._tree, stretch=1)

        if self._can_edit:
            cat_btns = QHBoxLayout()
            add_root_btn = QPushButton("Add Root")
            add_root_btn.clicked.connect(self._add_root_category)
            add_child_btn = QPushButton("Add Child")
            add_child_btn.clicked.connect(self._add_child_category)
            deactivate_btn = QPushButton("Deactivate")
            deactivate_btn.clicked.connect(self._deactivate_category)
            cat_btns.addWidget(add_root_btn)
            cat_btns.addWidget(add_child_btn)
            cat_btns.addWidget(deactivate_btn)
            lv.addLayout(cat_btns)

        splitter.addWidget(left)

        # Right: validation rules
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(QLabel("Validation Rules"))
        self._rules_table = QTableWidget(0, 4)
        self._rules_table.setHorizontalHeaderLabels(["Field", "Rule Type", "Value", "Description"])
        self._rules_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._rules_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        rv.addWidget(self._rules_table, stretch=1)

        if self._can_edit:
            rule_btns = QHBoxLayout()
            add_rule_btn = QPushButton("Add Rule")
            add_rule_btn.clicked.connect(self._add_rule)
            del_rule_btn = QPushButton("Delete Rule")
            del_rule_btn.clicked.connect(self._delete_rule)
            rule_btns.addWidget(add_rule_btn)
            rule_btns.addWidget(del_rule_btn)
            rv.addLayout(rule_btns)

        splitter.addWidget(right)
        splitter.setSizes([300, 400])

        root.addWidget(splitter, stretch=1)

    def load_data(self) -> None:
        worker = ApiWorker(self._client.list_categories, flat=True)
        worker.result.connect(self._on_categories_loaded)
        worker.error.connect(self._on_error)
        worker.start()

        worker2 = ApiWorker(self._client.list_taxonomy_rules)
        worker2.result.connect(self._on_rules_loaded)
        worker2.error.connect(self._on_error)
        worker2.start()

    def _on_categories_loaded(self, data: list) -> None:
        self._tree.clear()
        node_map: dict[str, QTreeWidgetItem] = {}
        # Sort by depth so parents are created before children
        for r in sorted(data, key=lambda x: x.get("depth", 0)):
            item = QTreeWidgetItem([
                r.get("name", ""),
                r.get("path_slug", ""),
                "Yes" if r.get("is_active") else "No",
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, r)
            parent_id = r.get("parent_id")
            if parent_id and parent_id in node_map:
                node_map[parent_id].addChild(item)
            else:
                self._tree.addTopLevelItem(item)
            node_map[r["category_id"]] = item
        self._tree.expandAll()

    def _on_rules_loaded(self, data: list) -> None:
        self._rules_table.setRowCount(0)
        for r in data:
            row = self._rules_table.rowCount()
            self._rules_table.insertRow(row)
            self._rules_table.setItem(row, 0, QTableWidgetItem(r.get("field", "")))
            self._rules_table.setItem(row, 1, QTableWidgetItem(r.get("rule_type", "")))
            self._rules_table.setItem(row, 2, QTableWidgetItem(r.get("rule_value", "")))
            self._rules_table.setItem(row, 3, QTableWidgetItem(r.get("description") or ""))
            self._rules_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, r)

    def _get_selected_category_id(self) -> Optional[str]:
        items = self._tree.selectedItems()
        if not items:
            return None
        record = items[0].data(0, Qt.ItemDataRole.UserRole)
        return record.get("category_id") if record else None

    def _add_root_category(self) -> None:
        dlg = _CategoryNameDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name = dlg.get_name()
            worker = ApiWorker(self._client.create_category, name=name)
            worker.result.connect(lambda _: self.load_data())
            worker.error.connect(self._on_error)
            worker.start()

    def _add_child_category(self) -> None:
        parent_id = self._get_selected_category_id()
        dlg = _CategoryNameDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name = dlg.get_name()
            worker = ApiWorker(self._client.create_category, name=name, parent_id=parent_id)
            worker.result.connect(lambda _: self.load_data())
            worker.error.connect(self._on_error)
            worker.start()

    def _deactivate_category(self) -> None:
        cat_id = self._get_selected_category_id()
        if not cat_id:
            return
        worker = ApiWorker(self._client.deactivate_category, cat_id)
        worker.result.connect(lambda _: self.load_data())
        worker.error.connect(self._on_error)
        worker.start()

    def _add_rule(self) -> None:
        dlg = _RuleDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            vals = dlg.get_values()
            worker = ApiWorker(self._client.create_taxonomy_rule, **vals)
            worker.result.connect(lambda _: self.load_data())
            worker.error.connect(self._on_error)
            worker.start()

    def _delete_rule(self) -> None:
        row = self._rules_table.currentRow()
        if row < 0:
            return
        record = self._rules_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        rule_id = record.get("rule_id", "")
        worker = ApiWorker(self._client.delete_taxonomy_rule, rule_id)
        worker.result.connect(lambda _: self.load_data())
        worker.error.connect(self._on_error)
        worker.start()

    def _on_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Error: {msg}", "error")


class _CategoryNameDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Category Name")
        form = QFormLayout(self)
        self._name = QLineEdit()
        form.addRow("Name:", self._name)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def get_name(self) -> str:
        return self._name.text().strip()


class _RuleDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Validation Rule")
        form = QFormLayout(self)
        self._field = QLineEdit()
        self._rule_type = QLineEdit()
        self._rule_value = QLineEdit()
        self._description = QLineEdit()
        form.addRow("Field:", self._field)
        form.addRow("Rule Type:", self._rule_type)
        form.addRow("Rule Value:", self._rule_value)
        form.addRow("Description:", self._description)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def get_values(self) -> dict:
        return {
            "field": self._field.text().strip(),
            "rule_type": self._rule_type.text().strip(),
            "rule_value": self._rule_value.text().strip(),
            "description": self._description.text().strip() or None,
        }
