"""
MDI workspace coordinator.

Manages the QMdiArea and the lifecycle of sub-windows. Ensures that:
- Only one instance of each screen type exists at a time (by screen key).
- Sub-windows are tiled/cascaded on demand.
- The active sub-window is tracked so Ctrl+N / Ctrl+F are context-sensitive.

Sub-window types are registered by string key so the coordinator stays
decoupled from concrete screen classes.
"""
from __future__ import annotations

from typing import Callable, Optional, Type

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMdiArea,
    QMdiSubWindow,
    QWidget,
)


class WorkspaceCoordinator:
    """
    Wraps ``QMdiArea`` with singleton sub-window management.

    Usage::

        coord = WorkspaceCoordinator(mdi_area)
        coord.register("resources", ResourceListWidget)
        coord.open("resources", client, state)   # returns sub-window
    """

    def __init__(self, mdi: QMdiArea) -> None:
        self._mdi = mdi
        self._registry: dict[str, Callable[..., QWidget]] = {}
        # key → active sub-window (weak-ish: cleared on close)
        self._open_windows: dict[str, QMdiSubWindow] = {}

    # ------------------------------------------------------------------ #
    # Registry                                                            #
    # ------------------------------------------------------------------ #

    def register(self, key: str, factory: Callable[..., QWidget]) -> None:
        """
        Register a widget factory under *key*.

        *factory* is called as ``factory(*args, **kwargs)`` by ``open()``.
        """
        self._registry[key] = factory

    # ------------------------------------------------------------------ #
    # Opening / focusing                                                  #
    # ------------------------------------------------------------------ #

    def open(self, key: str, *args, title: str = "",
             size: tuple[int, int] = (900, 600),
             **kwargs) -> Optional[QMdiSubWindow]:
        """
        Open (or focus) the sub-window for *key*.

        If a sub-window for *key* is already open and visible, it is
        brought to the foreground rather than creating a duplicate.
        """
        # Bring existing window to front
        if key in self._open_windows:
            existing = self._open_windows[key]
            if not existing.isHidden():
                self._mdi.setActiveSubWindow(existing)
                existing.raise_()
                return existing
            # Was closed by user: remove stale reference
            del self._open_windows[key]

        factory = self._registry.get(key)
        if factory is None:
            return None

        widget = factory(*args, **kwargs)
        sub = self._mdi.addSubWindow(widget)
        sub.setWindowTitle(title or key.replace("_", " ").title())
        sub.resize(*size)
        sub.show()

        # Clean up reference when the sub-window is closed
        sub.destroyed.connect(lambda: self._on_closed(key))

        self._open_windows[key] = sub
        return sub

    def close(self, key: str) -> None:
        """Close and destroy the sub-window for *key* (if open)."""
        if key in self._open_windows:
            self._open_windows[key].close()

    def close_all(self) -> None:
        """Close every managed sub-window (used on logout)."""
        for sub in list(self._open_windows.values()):
            sub.close()
        self._open_windows.clear()

    # ------------------------------------------------------------------ #
    # Layout helpers                                                      #
    # ------------------------------------------------------------------ #

    def tile(self) -> None:
        self._mdi.tileSubWindows()

    def cascade(self) -> None:
        self._mdi.cascadeSubWindows()

    # ------------------------------------------------------------------ #
    # Introspection                                                       #
    # ------------------------------------------------------------------ #

    def active_key(self) -> Optional[str]:
        """Return the registry key of the currently active sub-window."""
        active = self._mdi.activeSubWindow()
        for key, sub in self._open_windows.items():
            if sub is active:
                return key
        return None

    def active_widget(self) -> Optional[QWidget]:
        sub = self._mdi.activeSubWindow()
        if sub:
            return sub.widget()
        return None

    def is_open(self, key: str) -> bool:
        return key in self._open_windows and not self._open_windows[key].isHidden()

    # ------------------------------------------------------------------ #
    # Internal                                                            #
    # ------------------------------------------------------------------ #

    def _on_closed(self, key: str) -> None:
        self._open_windows.pop(key, None)
