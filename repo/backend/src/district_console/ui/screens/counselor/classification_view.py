"""
Counselor metadata classification and timeliness editing screen.

Counselors browse PUBLISHED resources and can classify them with:
  - Age range (min_age 0–18, max_age 0–18, min <= max)
  - Timeliness type (EVERGREEN / CURRENT / ARCHIVED)
  - Audience notes

Validation is applied client-side before submission, matching domain policies:
  age_range_valid(min_age, max_age) and timeliness_valid(value).
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
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from district_console.ui.widgets.loading_overlay import LoadingOverlay
from district_console.ui.widgets.notification_bar import NotificationBar

_TIMELINESS = ["EVERGREEN", "CURRENT", "ARCHIVED"]


class _ClassifyDialog(QDialog):
    def __init__(self, current: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Classify Resource")
        self.setMinimumWidth(360)
        layout = QFormLayout(self)

        self.min_age = QSpinBox()
        self.min_age.setRange(0, 18)
        self.min_age.setValue((current or {}).get("min_age", 0))
        layout.addRow("Min Age:", self.min_age)

        self.max_age = QSpinBox()
        self.max_age.setRange(0, 18)
        self.max_age.setValue((current or {}).get("max_age", 18))
        layout.addRow("Max Age:", self.max_age)

        self.timeliness = QComboBox()
        self.timeliness.addItems(_TIMELINESS)
        cur_t = (current or {}).get("timeliness_type", "EVERGREEN")
        idx = self.timeliness.findText(cur_t)
        if idx >= 0:
            self.timeliness.setCurrentIndex(idx)
        layout.addRow("Timeliness:", self.timeliness)

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
        min_a = self.min_age.value()
        max_a = self.max_age.value()
        if min_a > max_a:
            self._err.setText("Min age must be ≤ max age.")
            self._err.show()
            return
        self.accept()

    def values(self) -> dict:
        return {
            "min_age": self.min_age.value(),
            "max_age": self.max_age.value(),
            "timeliness_type": self.timeliness.currentText(),
        }


class ClassificationWidget(QWidget):
    """
    Counselor view for classifying published resources.
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
        heading = QLabel("Resource Classification")
        heading.setProperty("heading", True)
        header.addWidget(heading)
        header.addStretch()
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.clicked.connect(self.load_data)
        header.addWidget(refresh_btn)
        root.addLayout(header)

        sub = QLabel(
            "Right-click a resource to classify age range and timeliness."
        )
        sub.setProperty("subheading", True)
        root.addWidget(sub)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Title", "Type", "Min Age", "Max Age", "Timeliness"]
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
            # Metadata may be embedded or empty
            meta = r.get("metadata") or {}
            self._table.setItem(row, 2, QTableWidgetItem(str(meta.get("min_age", "—"))))
            self._table.setItem(row, 3, QTableWidgetItem(str(meta.get("max_age", "—"))))
            self._table.setItem(row, 4, QTableWidgetItem(meta.get("timeliness_type", "—")))
            self._table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole, r
            )

    def _show_context_menu(self, pos) -> None:
        from PyQt6.QtWidgets import QMenu
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        record = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if not isinstance(record, dict):
            return

        menu = QMenu(self)
        if self._state.has_permission("resources.classify"):
            classify_act = menu.addAction("Classify / Edit Metadata…")
            classify_act.triggered.connect(
                lambda: self._do_classify(record)
            )
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _do_classify(self, record: dict) -> None:
        dialog = _ClassifyDialog(record.get("metadata"), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            vals = dialog.values()
            resource_id = record.get("resource_id", "")
            title = record.get("title", "")
            self._worker = ApiWorker(
                self._client.classify_resource,
                resource_id,
                vals["min_age"],
                vals["max_age"],
                vals["timeliness_type"],
            )
            self._worker.result.connect(
                lambda _: self._notif.show_message(
                    f"Classification saved for '{title}'.", "success"
                )
            )
            self._worker.error.connect(self._on_error)
            self._worker.finished_clean.connect(self.load_data)
            self._worker.start()

    def _on_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Load error: {msg}", "error")
