"""
Resource library list / search screen.

Features
────────
- Searchable, filterable table of all resources visible to the current user.
- Ctrl+F focuses the search bar.
- Ctrl+N opens the new-resource dialog.
- Double-click row opens ResourceDetailWidget in the workspace.
- Right-click context menu: Submit Review / Publish / Unpublish / View Revisions.
  Actions are gated on AppState.has_permission() and the resource's current status.
- Pagination via Load More button (50 rows per page).
- Empty-state shown when no results.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from district_console.ui.client import ApiClient, ApiError
from district_console.ui.state import AppState
from district_console.ui.utils.async_worker import ApiWorker
from district_console.ui.widgets.empty_state import EmptyStateWidget
from district_console.ui.widgets.loading_overlay import LoadingOverlay
from district_console.ui.widgets.notification_bar import NotificationBar

_COLUMNS = ["Title", "Type", "Status", "Created By", "Updated At"]
_STATUS_OPTS = ["All", "DRAFT", "IN_REVIEW", "PUBLISHED", "UNPUBLISHED"]
_TYPE_OPTS = ["All", "BOOK", "PICTURE_BOOK", "ARTICLE", "AUDIO"]


class _NewResourceDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Resource")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Title *"))
        self.title_edit = QLineEdit()
        layout.addWidget(self.title_edit)

        layout.addWidget(QLabel("Resource Type *"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["BOOK", "PICTURE_BOOK", "ARTICLE", "AUDIO"])
        layout.addWidget(self.type_combo)

        layout.addWidget(QLabel("ISBN (optional)"))
        self.isbn_edit = QLineEdit()
        layout.addWidget(self.isbn_edit)

        self._error = QLabel("")
        self._error.setProperty("error", True)
        self._error.hide()
        layout.addWidget(self._error)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_accept(self) -> None:
        if not self.title_edit.text().strip():
            self._error.setText("Title is required.")
            self._error.show()
            return
        self.accept()

    def values(self) -> dict:
        return {
            "title": self.title_edit.text().strip(),
            "resource_type": self.type_combo.currentText(),
            "isbn": self.isbn_edit.text().strip() or None,
        }


class ResourceListWidget(QWidget):
    """
    Main resource library view with search, filter, table, and context menu.
    """

    # Emitted when user wants to open a resource detail panel
    open_detail = pyqtSignal(str, str)  # resource_id, title

    def __init__(self, client: ApiClient, state: AppState,
                 parent_window=None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._parent_window = parent_window
        self._offset = 0
        self._limit = 50
        self._total = 0
        self._rows: list[dict] = []
        self._worker: Optional[ApiWorker] = None

        self._build_ui()
        self.load_data()

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        # Notification bar (inline, not shell-level)
        self._notif = NotificationBar(self)
        root.addWidget(self._notif)

        # Toolbar row
        toolbar = QHBoxLayout()

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search resources… (Ctrl+F)")
        self._search_edit.returnPressed.connect(self._on_search_changed)
        toolbar.addWidget(self._search_edit, stretch=2)

        self._status_filter = QComboBox()
        self._status_filter.addItems(_STATUS_OPTS)
        self._status_filter.currentIndexChanged.connect(
            lambda _: self._reset_and_load()
        )
        toolbar.addWidget(QLabel("Status:"))
        toolbar.addWidget(self._status_filter)

        self._type_filter = QComboBox()
        self._type_filter.addItems(_TYPE_OPTS)
        self._type_filter.currentIndexChanged.connect(
            lambda _: self._reset_and_load()
        )
        toolbar.addWidget(QLabel("Type:"))
        toolbar.addWidget(self._type_filter)

        self._refresh_btn = QPushButton("↻ Refresh")
        self._refresh_btn.clicked.connect(lambda: self._reset_and_load())
        toolbar.addWidget(self._refresh_btn)

        if self._state.has_permission("resources.create"):
            self._new_btn = QPushButton("＋ New Resource")
            self._new_btn.clicked.connect(self.create_new)
            toolbar.addWidget(self._new_btn)

        root.addLayout(toolbar)

        # Stacked: table vs empty state
        self._stack = QStackedWidget()

        # Table
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._stack.addWidget(self._table)

        self._empty = EmptyStateWidget(
            icon="📚",
            heading="No resources found",
            subtext="Try adjusting the filters or import a new resource.",
            action_label="＋ New Resource" if self._state.has_permission(
                "resources.create") else None,
            action_callback=self.create_new if self._state.has_permission(
                "resources.create") else None,
        )
        self._stack.addWidget(self._empty)
        root.addWidget(self._stack, stretch=1)

        # Load more
        self._load_more_btn = QPushButton("Load More…")
        self._load_more_btn.hide()
        self._load_more_btn.clicked.connect(self._load_more)
        root.addWidget(self._load_more_btn)

        self._status_label = QLabel("")
        self._status_label.setProperty("subheading", True)
        root.addWidget(self._status_label)

        self._overlay = LoadingOverlay(self)

    # ------------------------------------------------------------------ #
    # Data loading                                                        #
    # ------------------------------------------------------------------ #

    def load_data(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._overlay.show()
        status = self._status_filter.currentText()
        rtype = self._type_filter.currentText()
        keyword = self._search_edit.text().strip()

        self._worker = ApiWorker(
            self._client.list_resources,
            offset=self._offset,
            limit=self._limit,
            status=None if status == "All" else status,
            resource_type=None if rtype == "All" else rtype,
            keyword=keyword or None,
        )
        self._worker.result.connect(self._on_data_loaded)
        self._worker.error.connect(self._on_load_error)
        self._worker.finished_clean.connect(self._overlay.hide)
        self._worker.start()

    def _on_data_loaded(self, data: dict) -> None:
        items = data.get("items", [])
        self._total = data.get("total", len(items))

        if self._offset == 0:
            self._rows = items
            self._table.setRowCount(0)
        else:
            self._rows.extend(items)

        for row_data in items:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(row_data.get("title", "")))
            self._table.setItem(row, 1, QTableWidgetItem(row_data.get("resource_type", "")))
            self._table.setItem(row, 2, QTableWidgetItem(row_data.get("status", "")))
            self._table.setItem(row, 3, QTableWidgetItem(row_data.get("created_by", "")))
            updated = row_data.get("updated_at", "")
            self._table.setItem(row, 4, QTableWidgetItem(updated[:19] if updated else ""))
            # Store resource_id in the first cell
            self._table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole, row_data.get("resource_id", "")
            )

        if self._rows:
            self._stack.setCurrentWidget(self._table)
        else:
            self._stack.setCurrentWidget(self._empty)

        showing = min(len(self._rows), self._total)
        self._status_label.setText(f"Showing {showing} of {self._total}")
        has_more = len(self._rows) < self._total
        self._load_more_btn.setVisible(has_more)

    def _on_load_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Failed to load resources: {msg}", "error")

    def _reset_and_load(self) -> None:
        self._offset = 0
        self._rows = []
        self.load_data()

    def _load_more(self) -> None:
        self._offset += self._limit
        self.load_data()

    def _on_search_changed(self) -> None:
        self._reset_and_load()

    # ------------------------------------------------------------------ #
    # Context menu                                                        #
    # ------------------------------------------------------------------ #

    def _show_context_menu(self, pos) -> None:
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        resource_id = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        status = self._table.item(row, 2).text()
        title = self._table.item(row, 0).text()

        menu = QMenu(self)

        view_act = menu.addAction("View Detail")
        view_act.triggered.connect(
            lambda: self._open_detail(resource_id, title)
        )
        menu.addSeparator()

        if (self._state.has_permission("resources.submit_review")
                and status == "DRAFT"):
            sub_act = menu.addAction("Submit for Review…")
            sub_act.triggered.connect(
                lambda: self._do_submit_review(resource_id)
            )

        if self._state.has_permission("resources.publish"):
            if status == "IN_REVIEW":
                pub_act = menu.addAction("Publish…")
                pub_act.triggered.connect(
                    lambda: self._do_publish(resource_id)
                )
            if status == "PUBLISHED":
                unpub_act = menu.addAction("Unpublish…")
                unpub_act.triggered.connect(
                    lambda: self._do_unpublish(resource_id)
                )

        menu.addSeparator()
        revisions_act = menu.addAction("View Revisions")
        revisions_act.triggered.connect(
            lambda: self._open_revisions(resource_id, title)
        )

        menu.exec(self._table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ #
    # Actions                                                             #
    # ------------------------------------------------------------------ #

    def create_new(self) -> None:
        dialog = _NewResourceDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            vals = dialog.values()
            self._worker = ApiWorker(
                self._client.create_resource,
                vals["title"], vals["resource_type"], vals.get("isbn")
            )
            self._worker.result.connect(lambda _: self._reset_and_load())
            self._worker.error.connect(self._on_action_error)
            self._worker.start()

    def focus_search(self) -> None:
        self._search_edit.setFocus()
        self._search_edit.selectAll()

    def _open_detail(self, resource_id: str, title: str) -> None:
        if self._parent_window and hasattr(self._parent_window, "workspace"):
            from district_console.ui.screens.resources.resource_detail import ResourceDetailWidget
            self._parent_window.workspace.register(
                f"resource_{resource_id}",
                lambda: ResourceDetailWidget(
                    self._client, self._state, resource_id, self._parent_window
                ),
            )
            self._parent_window.workspace.open(
                f"resource_{resource_id}", title=f"Resource: {title}", size=(800, 600)
            )

    def _open_revisions(self, resource_id: str, title: str) -> None:
        self._open_detail(resource_id, title)

    def _do_submit_review(self, resource_id: str) -> None:
        from PyQt6.QtWidgets import QInputDialog
        reviewer_id, ok = QInputDialog.getText(
            self, "Submit for Review", "Reviewer User ID:"
        )
        if ok and reviewer_id.strip():
            worker = ApiWorker(
                self._client.submit_for_review, resource_id, reviewer_id.strip()
            )
            worker.result.connect(lambda _: (
                self._notif.show_message("Submitted for review.", "success"),
                self._reset_and_load(),
            ))
            worker.error.connect(self._on_action_error)
            worker.start()
            self._worker = worker

    def _do_publish(self, resource_id: str) -> None:
        from PyQt6.QtWidgets import QInputDialog
        notes, ok = QInputDialog.getMultiLineText(
            self, "Publish Resource", "Reviewer Notes (required):"
        )
        if ok and notes.strip():
            worker = ApiWorker(
                self._client.publish_resource, resource_id, notes.strip()
            )
            worker.result.connect(lambda _: (
                self._notif.show_message("Resource published.", "success"),
                self._reset_and_load(),
            ))
            worker.error.connect(self._on_action_error)
            worker.start()
            self._worker = worker

    def _do_unpublish(self, resource_id: str) -> None:
        from PyQt6.QtWidgets import QInputDialog
        notes, ok = QInputDialog.getMultiLineText(
            self, "Unpublish Resource", "Reason / Notes (required):"
        )
        if ok and notes.strip():
            worker = ApiWorker(
                self._client.unpublish_resource, resource_id, notes.strip()
            )
            worker.result.connect(lambda _: (
                self._notif.show_message("Resource unpublished.", "info"),
                self._reset_and_load(),
            ))
            worker.error.connect(self._on_action_error)
            worker.start()
            self._worker = worker

    def _on_action_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Action failed: {msg}", "error")

    def _on_row_double_clicked(self, index) -> None:
        row = index.row()
        resource_id = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        title = self._table.item(row, 0).text()
        self._open_detail(resource_id, title)
