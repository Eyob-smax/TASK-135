"""
Main application shell window.

Hosts the MDI workspace, navigation dock, menu bar, notification bar, and
shortcut infrastructure. One instance exists for the lifetime of an
authenticated session; it is destroyed and re-created on logout/re-login.

Responsibilities
────────────────
- Register all screen factories with WorkspaceCoordinator
- Wire global keyboard shortcuts to workspace actions
- Handle tray minimize / safe shutdown
- Show the RecoveryDialog for pending checkpoints on first show
- Expose a notification API used by all child screens
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDockWidget,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMdiArea,
    QMessageBox,
    QStatusBar,
    QToolBar,
    QWidget,
)

from district_console.ui.client import ApiClient
from district_console.ui.shortcuts import ShortcutManager
from district_console.ui.state import AppState
from district_console.ui.shell.workspace import WorkspaceCoordinator
from district_console.ui.widgets.notification_bar import NotificationBar
from district_console.ui.widgets.recovery_dialog import RecoveryDialog

if TYPE_CHECKING:
    from district_console.ui.tray import SystemTray

# Navigation entries: (display_label, registry_key, required_permission)
_NAV_ENTRIES = [
    ("Dashboard",        "dashboard",        None),
    ("Resources",        "resources",        "resources.view"),
    ("Inventory",        "inventory",        "inventory.view"),
    ("Count Sessions",   "count_sessions",   "inventory.count"),
    ("Relocations",      "relocations",      "inventory.relocate"),
    ("Approvals",        "approvals",        "resources.publish"),
    ("Classification",   "classification",   "resources.classify"),
    ("Allocations",      "allocations",      None),
    # Admin-only entries
    ("── Admin ──",      None,               "admin.manage_config"),
    ("Config Center",    "config_center",    "admin.manage_config"),
    ("Taxonomy Admin",   "taxonomy_admin",   "admin.manage_config"),
    ("Integrations",     "integration_admin","admin.manage_config"),
    ("Update Manager",   "update_manager",   "admin.manage_config"),
    ("Audit Log",        "audit_log",        "admin.manage_config"),
]


class MainWindow(QMainWindow):
    """
    Central shell window for an authenticated session.

    Signals
    -------
    logout_requested : pyqtSignal()
        Emitted when the user logs out (Ctrl+Shift+O or menu action).
    """

    logout_requested = pyqtSignal()

    def __init__(self, client: ApiClient, state: AppState,
                 tray: "SystemTray",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._tray = tray

        self.setWindowTitle("District Resource & Inventory Console")
        self.resize(1600, 960)
        self.setMinimumSize(1024, 600)

        self._build_ui()
        self._register_screens()
        self._build_menus()
        self._build_toolbar()
        self._wire_shortcuts()
        self._apply_role_visibility()

        tray.update_user_label(state.username or "", state.roles)

    # ------------------------------------------------------------------ #
    # UI construction                                                     #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        # Notification bar (inserted above MDI area via central widget layout)
        container = QWidget(self)
        from PyQt6.QtWidgets import QVBoxLayout
        v_layout = QVBoxLayout(container)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(0)

        self._notification_bar = NotificationBar(container)
        v_layout.addWidget(self._notification_bar)

        self._mdi = QMdiArea(container)
        self._mdi.setViewMode(QMdiArea.ViewMode.SubWindowView)
        self._mdi.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._mdi.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        v_layout.addWidget(self._mdi, stretch=1)

        self.setCentralWidget(container)

        # Status bar
        status = QStatusBar(self)
        role_text = ", ".join(self._state.roles) if self._state.roles else "—"
        status.addPermanentWidget(
            QLabel(f"  {self._state.username}  |  {role_text}  ")
        )
        self.setStatusBar(status)

        # Navigation dock
        self._nav_list = QListWidget()
        self._nav_list.itemDoubleClicked.connect(self._on_nav_activated)
        nav_dock = QDockWidget("Navigation", self)
        nav_dock.setWidget(self._nav_list)
        nav_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, nav_dock)
        self._populate_nav()

        self.workspace = WorkspaceCoordinator(self._mdi)

    def _populate_nav(self) -> None:
        self._nav_list.clear()
        for label, key, perm in _NAV_ENTRIES:
            if perm and not self._state.has_permission(perm):
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            if key is None:
                # Section separator — not selectable
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._nav_list.addItem(item)

    def _build_menus(self) -> None:
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")
        logout_action = file_menu.addAction("Sign &Out\tCtrl+Shift+O")
        logout_action.triggered.connect(self._do_logout)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("&Quit")
        quit_action.triggered.connect(self._tray._safe_quit)

        # View menu
        view_menu = menubar.addMenu("&View")
        tile_action = view_menu.addAction("&Tile Windows")
        tile_action.triggered.connect(self.workspace.tile)
        cascade_action = view_menu.addAction("&Cascade Windows")
        cascade_action.triggered.connect(self.workspace.cascade)
        view_menu.addSeparator()
        close_all_action = view_menu.addAction("Close &All Windows")
        close_all_action.triggered.connect(self.workspace.close_all)

        # Role-gated menus
        if self._state.has_permission("inventory.view"):
            inv_menu = menubar.addMenu("&Inventory")
            adj_act = inv_menu.addAction("New &Adjustment")
            adj_act.triggered.connect(
                lambda: self.workspace.open("inventory", self._client,
                                            self._state, title="Inventory")
            )

        if self._state.has_permission("resources.view"):
            res_menu = menubar.addMenu("&Resources")
            new_res_act = res_menu.addAction("&New Resource\tCtrl+N")
            new_res_act.triggered.connect(self._on_new_record)
            res_menu.addSeparator()
            import_act = res_menu.addAction("&Import File…")
            import_act.triggered.connect(
                lambda: self.workspace.open("resources", self._client,
                                            self._state, title="Resources")
            )

        if self._state.has_permission("admin.manage_config"):
            admin_menu = menubar.addMenu("&Administration")
            admin_menu.addAction("&Config Center").triggered.connect(
                lambda: self.workspace.open("config_center", title="Config Center")
            )
            admin_menu.addAction("&Taxonomy Admin").triggered.connect(
                lambda: self.workspace.open("taxonomy_admin", title="Taxonomy Admin")
            )
            admin_menu.addAction("&Integrations").triggered.connect(
                lambda: self.workspace.open("integration_admin", title="Integrations")
            )
            admin_menu.addAction("&Update Manager").triggered.connect(
                lambda: self.workspace.open("update_manager", title="Update Manager")
            )
            admin_menu.addSeparator()
            admin_menu.addAction("&Audit Log").triggered.connect(
                lambda: self.workspace.open("audit_log", title="Audit Log")
            )

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main", self)
        tb.setMovable(False)
        self.addToolBar(tb)

        search_action = tb.addAction("🔍 Search (Ctrl+F)")
        search_action.triggered.connect(self._on_global_search)

        if self._state.has_permission("resources.create"):
            new_action = tb.addAction("＋ New (Ctrl+N)")
            new_action.triggered.connect(self._on_new_record)

    # ------------------------------------------------------------------ #
    # Screen registry                                                     #
    # ------------------------------------------------------------------ #

    def _register_screens(self) -> None:
        from district_console.ui.screens.dashboard import DashboardWidget
        from district_console.ui.screens.resources.resource_list import ResourceListWidget
        from district_console.ui.screens.inventory.ledger_viewer import LedgerViewerWidget
        from district_console.ui.screens.inventory.count_session import CountSessionWidget
        from district_console.ui.screens.inventory.relocation_view import RelocationWidget
        from district_console.ui.screens.approval.approval_inbox import ApprovalInboxWidget
        from district_console.ui.screens.counselor.classification_view import ClassificationWidget
        from district_console.ui.screens.teacher.allocation_view import AllocationWidget

        self.workspace.register(
            "dashboard",
            lambda: DashboardWidget(self._client, self._state, self),
        )
        self.workspace.register(
            "resources",
            lambda: ResourceListWidget(self._client, self._state, self),
        )
        self.workspace.register(
            "inventory",
            lambda: LedgerViewerWidget(self._client, self._state, self),
        )
        self.workspace.register(
            "count_sessions",
            lambda: CountSessionWidget(self._client, self._state, self),
        )
        self.workspace.register(
            "relocations",
            lambda: RelocationWidget(self._client, self._state, self),
        )
        self.workspace.register(
            "approvals",
            lambda: ApprovalInboxWidget(self._client, self._state, self),
        )
        self.workspace.register(
            "classification",
            lambda: ClassificationWidget(self._client, self._state, self),
        )
        self.workspace.register(
            "allocations",
            lambda: AllocationWidget(self._client, self._state, self),
        )

        # Admin-only screens (registered unconditionally; nav visibility is
        # gated by admin.manage_config in _populate_nav)
        if self._state.has_permission("admin.manage_config"):
            from district_console.ui.screens.admin.config_center import ConfigCenterWidget
            from district_console.ui.screens.admin.taxonomy_admin import TaxonomyAdminWidget
            from district_console.ui.screens.admin.integration_admin import IntegrationAdminWidget
            from district_console.ui.screens.admin.update_manager import UpdateManagerWidget
            from district_console.ui.screens.admin.audit_log_viewer import AuditLogViewerWidget

            self.workspace.register(
                "config_center",
                lambda: ConfigCenterWidget(self._client, self._state, self),
            )
            self.workspace.register(
                "taxonomy_admin",
                lambda: TaxonomyAdminWidget(self._client, self._state, self),
            )
            self.workspace.register(
                "integration_admin",
                lambda: IntegrationAdminWidget(self._client, self._state, self),
            )
            self.workspace.register(
                "update_manager",
                lambda: UpdateManagerWidget(self._client, self._state, self),
            )
            self.workspace.register(
                "audit_log",
                lambda: AuditLogViewerWidget(self._client, self._state, self),
            )

    # ------------------------------------------------------------------ #
    # Shortcuts                                                           #
    # ------------------------------------------------------------------ #

    def _wire_shortcuts(self) -> None:
        self._shortcuts = ShortcutManager(self)
        self._shortcuts.connect("global_search", self._on_global_search)
        self._shortcuts.connect("new_record", self._on_new_record)
        self._shortcuts.connect("logout", self._do_logout)
        self._shortcuts.connect("close_window", self._close_active_subwindow)
        self._shortcuts.connect("refresh", self._refresh_active)
        self._shortcuts.connect("hard_refresh", self._refresh_active)
        self._shortcuts.connect("dismiss_notify", self._notification_bar.dismiss)
        self._shortcuts.connect("nav_dashboard", lambda: self._open_nav("dashboard"))
        self._shortcuts.connect("nav_resources", lambda: self._open_nav("resources"))
        self._shortcuts.connect("nav_inventory", lambda: self._open_nav("inventory"))
        self._shortcuts.connect("nav_count", lambda: self._open_nav("count_sessions"))
        self._shortcuts.connect("nav_approvals", lambda: self._open_nav("approvals"))
        self._shortcuts.connect("open_inventory_ledger", lambda: self._open_nav("inventory"))

    # ------------------------------------------------------------------ #
    # Role-based visibility                                               #
    # ------------------------------------------------------------------ #

    def _apply_role_visibility(self) -> None:
        """Show/hide menu and toolbar items based on current roles."""
        # Navigation list already filtered; toolbar actions reflect permissions
        pass  # Additional role gates applied in _build_menus/_build_toolbar above

    # ------------------------------------------------------------------ #
    # Actions                                                             #
    # ------------------------------------------------------------------ #

    def _on_nav_activated(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        label = item.text()
        self._open_nav(key, label)

    def _open_nav(self, key: str, title: str = "") -> None:
        self.workspace.open(key, title=title or key.replace("_", " ").title())

    def _on_global_search(self) -> None:
        """Focus the search widget in the active sub-window, or open Resources."""
        widget = self.workspace.active_widget()
        if widget and hasattr(widget, "focus_search"):
            widget.focus_search()
        else:
            self.workspace.open("resources", title="Resources")

    def _on_new_record(self) -> None:
        """Open a new-record dialog in the context of the active sub-window."""
        widget = self.workspace.active_widget()
        if widget and hasattr(widget, "create_new"):
            widget.create_new()
        elif self._state.has_permission("resources.create"):
            self.workspace.open("resources", title="Resources")

    def _close_active_subwindow(self) -> None:
        sub = self._mdi.activeSubWindow()
        if sub:
            sub.close()

    def _refresh_active(self) -> None:
        widget = self.workspace.active_widget()
        if widget and hasattr(widget, "load_data"):
            widget.load_data()

    def _do_logout(self) -> None:
        from district_console.ui.utils.async_worker import ApiWorker
        self._logout_worker = ApiWorker(self._client.logout)
        self._logout_worker.finished_clean.connect(self._finish_logout)
        self._logout_worker.start()

    def _finish_logout(self) -> None:
        self._state.clear()
        self.workspace.close_all()
        self.logout_requested.emit()
        self.hide()

    # ------------------------------------------------------------------ #
    # Recovery prompt                                                     #
    # ------------------------------------------------------------------ #

    def show_recovery_prompt(self) -> None:
        """Display pending checkpoints dialog on first show (called from app.py)."""
        if not self._state.pending_checkpoints:
            return
        dialog = RecoveryDialog(self._state.pending_checkpoints, self)
        result = dialog.exec()
        selected = dialog.selected_checkpoints() if result else []
        # Keep only selected checkpoints in state for downstream resume handlers.
        self._state.pending_checkpoints = [
            cp for cp in self._state.pending_checkpoints
            if cp.get("job_id") in selected
        ]
        if selected:
            self.notify(
                f"Resuming {len(selected)} interrupted job(s).", "info"
            )

    # ------------------------------------------------------------------ #
    # Notification shortcut                                               #
    # ------------------------------------------------------------------ #

    def notify(self, message: str,
               severity: str = "info", timeout_ms: int = 5000) -> None:
        """Show a notification bar message. Also mirror to tray."""
        self._notification_bar.show_message(message, severity, timeout_ms)  # type: ignore[arg-type]
        if not self.isVisible():
            self._tray.notify("District Console", message)

    # ------------------------------------------------------------------ #
    # Window events                                                       #
    # ------------------------------------------------------------------ #

    def changeEvent(self, event: QEvent) -> None:
        if (event.type() == QEvent.Type.WindowStateChange
                and self.isMinimized()
                and self._state.tray_mode):
            self.hide()
            self._tray.show()
            self._tray.notify("District Console",
                              "Application minimized to tray.")
        super().changeEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._state.has_resumable_work():
            answer = QMessageBox.question(
                self,
                "Confirm Close",
                "Background tasks are still running.\n\n"
                "Closing now may lose in-progress work. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.workspace.close_all()
        self._tray.hide()
        event.accept()
