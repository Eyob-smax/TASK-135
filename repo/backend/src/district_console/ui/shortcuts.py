"""
Global keyboard shortcut manager for the District Console desktop shell.

Shortcuts are registered once on the MainWindow and dispatched via Qt's
standard QAction shortcut mechanism (ApplicationShortcut context), so they
fire regardless of which sub-window has focus inside the MDI workspace.

Short-cut map
─────────────
Ctrl+F          Global search (focus search bar / open search dialog)
Ctrl+N          New record (context-sensitive to active MDI sub-window)
Ctrl+Shift+L    Open inventory ledger window
Ctrl+Shift+O    Logout (sign out and return to sign-in screen)
Ctrl+W          Close active MDI sub-window
Ctrl+S          Save / commit current form
Ctrl+R          Refresh active sub-window data
Ctrl+1 … Ctrl+5 Jump to navigation section (Dashboard, Resources,
                Inventory, Count Sessions, Approvals)
F5              Hard refresh
Escape          Dismiss top notification
"""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QMainWindow


# Symbolic names → key sequence strings
SHORTCUT_MAP: dict[str, str] = {
    "global_search":        "Ctrl+F",
    "new_record":           "Ctrl+N",
    "open_inventory_ledger": "Ctrl+Shift+L",
    "logout":               "Ctrl+Shift+O",
    "close_window":         "Ctrl+W",
    "save":            "Ctrl+S",
    "refresh":         "Ctrl+R",
    "nav_dashboard":   "Ctrl+1",
    "nav_resources":   "Ctrl+2",
    "nav_inventory":   "Ctrl+3",
    "nav_count":       "Ctrl+4",
    "nav_approvals":   "Ctrl+5",
    "hard_refresh":    "F5",
    "dismiss_notify":  "Escape",
}


class ShortcutManager:
    """
    Owns all global QAction shortcuts attached to the main window.

    Usage::

        mgr = ShortcutManager(main_window)
        mgr.connect("global_search", self._on_search)
        mgr.connect("logout", self._on_logout)

    ``connect`` can be called multiple times on the same name to add
    multiple slots (additive, not replacing).
    """

    def __init__(self, window: QMainWindow) -> None:
        self._window = window
        self._actions: dict[str, QAction] = {}
        self._setup()

    def _setup(self) -> None:
        for name, seq in SHORTCUT_MAP.items():
            action = QAction(self._window)
            action.setShortcut(QKeySequence(seq))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            self._window.addAction(action)
            self._actions[name] = action

    def connect(self, name: str, slot: Callable[[], None]) -> None:
        """Attach *slot* to the shortcut identified by *name*."""
        if name in self._actions:
            self._actions[name].triggered.connect(slot)

    def disconnect_all(self, name: str) -> None:
        """Remove all connected slots from a named shortcut."""
        if name in self._actions:
            try:
                self._actions[name].triggered.disconnect()
            except RuntimeError:
                pass  # No connections — safe to ignore

    def trigger(self, name: str) -> None:
        """Programmatically fire a shortcut (useful in tests)."""
        if name in self._actions:
            self._actions[name].trigger()

    def action(self, name: str) -> Optional[QAction]:
        """Return the underlying QAction for direct manipulation."""
        return self._actions.get(name)

    def set_enabled(self, name: str, enabled: bool) -> None:
        if name in self._actions:
            self._actions[name].setEnabled(enabled)

    @staticmethod
    def shortcut_hint(name: str) -> str:
        """Return a human-readable shortcut hint for UI labels (e.g. 'Ctrl+F')."""
        return SHORTCUT_MAP.get(name, "")
