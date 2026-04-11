"""
System tray integration for the District Console.

Provides minimize-to-tray behaviour, a context menu with restore/quit actions,
and balloon notifications. Background tasks (APScheduler, open count sessions)
continue running while the main window is hidden in the tray.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from district_console.ui.state import AppState

if TYPE_CHECKING:
    from district_console.ui.shell.main_window import MainWindow


def _make_tray_icon() -> QIcon:
    """Return a fallback icon (application-level icon or built-in Qt fallback)."""
    app = QApplication.instance()
    if app and not app.windowIcon().isNull():
        return app.windowIcon()
    return QIcon.fromTheme("computer", QIcon())


class SystemTray(QSystemTrayIcon):
    """
    Manages the system tray icon, context menu, and notification bubbles.

    Created before the main window; ``set_main_window()`` is called once
    the main window exists after a successful login.
    """

    def __init__(self, app: QApplication, state: AppState) -> None:
        super().__init__(_make_tray_icon(), app)
        self._state = state
        self._main_window: Optional[MainWindow] = None
        self._setup_menu()
        self.activated.connect(self._on_activated)

    # ------------------------------------------------------------------ #
    # Setup                                                               #
    # ------------------------------------------------------------------ #

    def _setup_menu(self) -> None:
        menu = QMenu()

        self._restore_action = menu.addAction("Open Console")
        self._restore_action.triggered.connect(self._restore_window)

        menu.addSeparator()

        self._user_label = menu.addAction("Not signed in")
        self._user_label.setEnabled(False)

        menu.addSeparator()

        self._quit_action = menu.addAction("Quit District Console")
        self._quit_action.triggered.connect(self._safe_quit)

        self.setContextMenu(menu)
        self.setToolTip("District Console")

    def set_main_window(self, window: "MainWindow") -> None:
        self._main_window = window

    def update_user_label(self, username: str, roles: list[str]) -> None:
        role_str = ", ".join(roles)
        self._user_label.setText(f"{username}  [{role_str}]")

    # ------------------------------------------------------------------ #
    # Slot handlers                                                       #
    # ------------------------------------------------------------------ #

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._restore_window()

    def _restore_window(self) -> None:
        if self._main_window:
            self._main_window.showNormal()
            self._main_window.raise_()
            self._main_window.activateWindow()

    def _safe_quit(self) -> None:
        if self._state.has_resumable_work():
            answer = QMessageBox.question(
                None,
                "Confirm Quit",
                "Background tasks are in progress.\n\n"
                "Quitting now may lose unsaved work. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        QApplication.quit()

    # ------------------------------------------------------------------ #
    # Notifications                                                        #
    # ------------------------------------------------------------------ #

    def notify(self, title: str, message: str,
               icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
               duration_ms: int = 3000) -> None:
        """Show a balloon notification (Windows toast-style)."""
        if self.isSystemTrayAvailable() and self.isVisible():
            self.showMessage(title, message, icon, duration_ms)
