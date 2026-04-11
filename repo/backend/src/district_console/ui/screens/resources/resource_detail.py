"""
Resource detail / editor panel.

Displays the full resource record with tabs for Details, Revisions, and
Metadata. Draft resources can be edited by users with resources.edit.
Status-transition buttons (Submit Review, Publish, Unpublish) appear based
on current status and role.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
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


class ResourceDetailWidget(QWidget):
    """
    Tabbed detail view for a single resource record.
    """

    def __init__(self, client: ApiClient, state: AppState,
                 resource_id: str,
                 parent_window=None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._resource_id = resource_id
        self._parent_window = parent_window
        self._resource: Optional[dict] = None
        self._worker: Optional[ApiWorker] = None
        self._editing = False

        self._build_ui()
        self.load_data()

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        self._notif = NotificationBar(self)
        root.addWidget(self._notif)

        # Action buttons (status-transition)
        self._action_row = QHBoxLayout()
        self._submit_btn = QPushButton("Submit for Review")
        self._submit_btn.hide()
        self._submit_btn.clicked.connect(self._do_submit)
        self._action_row.addWidget(self._submit_btn)

        self._publish_btn = QPushButton("Publish")
        self._publish_btn.hide()
        self._publish_btn.clicked.connect(self._do_publish)
        self._action_row.addWidget(self._publish_btn)

        self._unpublish_btn = QPushButton("Unpublish")
        self._unpublish_btn.hide()
        self._unpublish_btn.clicked.connect(self._do_unpublish)
        self._action_row.addWidget(self._unpublish_btn)

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.hide()
        self._edit_btn.clicked.connect(self._toggle_edit)
        self._action_row.addWidget(self._edit_btn)

        self._action_row.addStretch()
        root.addLayout(self._action_row)

        # Tabs
        self._tabs = QTabWidget()
        root.addWidget(self._tabs, stretch=1)

        self._details_tab = self._build_details_tab()
        self._tabs.addTab(self._details_tab, "Details")

        self._revisions_tab = self._build_revisions_tab()
        self._tabs.addTab(self._revisions_tab, "Revisions")

        self._overlay = LoadingOverlay(self)

    def _build_details_tab(self) -> QWidget:
        container = QWidget()
        scroll = QScrollArea()
        scroll.setWidget(container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        form = QFormLayout(container)
        form.setContentsMargins(16, 12, 16, 12)
        form.setSpacing(10)

        self._title_edit = QLineEdit()
        self._title_edit.setReadOnly(True)
        form.addRow("Title:", self._title_edit)

        self._type_lbl = QLabel()
        form.addRow("Type:", self._type_lbl)

        self._status_lbl = QLabel()
        form.addRow("Status:", self._status_lbl)

        self._isbn_edit = QLineEdit()
        self._isbn_edit.setReadOnly(True)
        form.addRow("ISBN:", self._isbn_edit)

        self._dedup_lbl = QLabel()
        self._dedup_lbl.setProperty("subheading", True)
        form.addRow("Dedup Key:", self._dedup_lbl)

        self._created_lbl = QLabel()
        form.addRow("Created:", self._created_lbl)

        self._updated_lbl = QLabel()
        form.addRow("Updated:", self._updated_lbl)

        self._save_btn = QPushButton("Save Changes")
        self._save_btn.hide()
        self._save_btn.clicked.connect(self._do_save)
        form.addRow("", self._save_btn)

        return scroll

    def _build_revisions_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        self._revisions_table = QTableWidget(0, 4)
        self._revisions_table.setHorizontalHeaderLabels(
            ["#", "File Hash", "Size (bytes)", "Created At"]
        )
        self._revisions_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._revisions_table)
        return container

    # ------------------------------------------------------------------ #
    # Data                                                                #
    # ------------------------------------------------------------------ #

    def load_data(self) -> None:
        self._overlay.show()
        self._worker = ApiWorker(self._client.get_resource, self._resource_id)
        self._worker.result.connect(self._on_resource_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.finished_clean.connect(self._overlay.hide)
        self._worker.start()

    def _on_resource_loaded(self, data: dict) -> None:
        self._resource = data
        self._populate_details(data)
        self._update_action_buttons(data.get("status", ""))
        self._load_revisions()

    def _populate_details(self, data: dict) -> None:
        self._title_edit.setText(data.get("title", ""))
        self._type_lbl.setText(data.get("resource_type", ""))
        status = data.get("status", "")
        self._status_lbl.setText(status)
        self._isbn_edit.setText(data.get("isbn") or "")
        self._dedup_lbl.setText(data.get("dedup_key", "")[:32] + "…")
        created = data.get("created_at", "")
        self._created_lbl.setText(created[:19] if created else "")
        updated = data.get("updated_at", "")
        self._updated_lbl.setText(updated[:19] if updated else "")

    def _update_action_buttons(self, status: str) -> None:
        self._submit_btn.hide()
        self._publish_btn.hide()
        self._unpublish_btn.hide()
        self._edit_btn.hide()

        if (status == "DRAFT"
                and self._state.has_permission("resources.submit_review")):
            self._submit_btn.show()

        if (status == "DRAFT"
                and self._state.has_permission("resources.edit")):
            self._edit_btn.show()

        if (status == "IN_REVIEW"
                and self._state.has_permission("resources.publish")):
            self._publish_btn.show()

        if (status == "PUBLISHED"
                and self._state.has_permission("resources.publish")):
            self._unpublish_btn.show()

    def _load_revisions(self) -> None:
        worker = ApiWorker(self._client.list_revisions, self._resource_id)
        worker.result.connect(self._on_revisions_loaded)
        worker.start()

    def _on_revisions_loaded(self, data: dict) -> None:
        items = data.get("items", [])
        self._revisions_table.setRowCount(0)
        for rev in items:
            row = self._revisions_table.rowCount()
            self._revisions_table.insertRow(row)
            self._revisions_table.setItem(
                row, 0, QTableWidgetItem(str(rev.get("revision_number", "")))
            )
            fh = rev.get("file_hash", "")
            self._revisions_table.setItem(
                row, 1, QTableWidgetItem(fh[:20] + "…" if len(fh) > 20 else fh)
            )
            self._revisions_table.setItem(
                row, 2, QTableWidgetItem(str(rev.get("file_size", "")))
            )
            created = rev.get("created_at", "")
            self._revisions_table.setItem(
                row, 3, QTableWidgetItem(created[:19] if created else "")
            )

    def _on_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Error loading resource: {msg}", "error")

    # ------------------------------------------------------------------ #
    # Edit mode                                                           #
    # ------------------------------------------------------------------ #

    def _toggle_edit(self) -> None:
        self._editing = not self._editing
        self._title_edit.setReadOnly(not self._editing)
        self._isbn_edit.setReadOnly(not self._editing)
        self._edit_btn.setText("Cancel" if self._editing else "Edit")
        self._save_btn.setVisible(self._editing)

    def _do_save(self) -> None:
        fields: dict = {}
        if self._title_edit.text().strip():
            fields["title"] = self._title_edit.text().strip()
        isbn = self._isbn_edit.text().strip()
        if isbn:
            fields["isbn"] = isbn
        worker = ApiWorker(
            self._client.update_resource, self._resource_id, **fields
        )
        worker.result.connect(lambda d: (
            self._notif.show_message("Resource updated.", "success"),
            self._on_resource_loaded(d),
            self._toggle_edit(),
        ))
        worker.error.connect(self._on_action_error)
        worker.start()
        self._worker = worker

    # ------------------------------------------------------------------ #
    # Status transitions                                                  #
    # ------------------------------------------------------------------ #

    def _do_submit(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        reviewer_id, ok = QInputDialog.getText(
            self, "Submit for Review", "Reviewer User ID:"
        )
        if ok and reviewer_id.strip():
            worker = ApiWorker(
                self._client.submit_for_review,
                self._resource_id, reviewer_id.strip()
            )
            worker.result.connect(lambda d: (
                self._notif.show_message("Submitted for review.", "success"),
                self._on_resource_loaded(d),
            ))
            worker.error.connect(self._on_action_error)
            worker.start()
            self._worker = worker

    def _do_publish(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        notes, ok = QInputDialog.getMultiLineText(
            self, "Publish", "Reviewer Notes (required):"
        )
        if ok and notes.strip():
            worker = ApiWorker(
                self._client.publish_resource,
                self._resource_id, notes.strip()
            )
            worker.result.connect(lambda d: (
                self._notif.show_message("Resource published.", "success"),
                self._on_resource_loaded(d),
            ))
            worker.error.connect(self._on_action_error)
            worker.start()
            self._worker = worker
        elif ok:
            self._notif.show_message(
                "Reviewer notes are required to publish.", "warning"
            )

    def _do_unpublish(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        notes, ok = QInputDialog.getMultiLineText(
            self, "Unpublish", "Reason / Notes (required):"
        )
        if ok and notes.strip():
            worker = ApiWorker(
                self._client.unpublish_resource,
                self._resource_id, notes.strip()
            )
            worker.result.connect(lambda d: (
                self._notif.show_message("Resource unpublished.", "info"),
                self._on_resource_loaded(d),
            ))
            worker.error.connect(self._on_action_error)
            worker.start()
            self._worker = worker
        elif ok:
            self._notif.show_message(
                "Notes are required to unpublish.", "warning"
            )

    def _on_action_error(self, exc: Exception) -> None:
        msg = exc.message if isinstance(exc, ApiError) else str(exc)
        self._notif.show_message(f"Action failed: {msg}", "error")
