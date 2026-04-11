"""
Collapsible notification bar displayed at the top of the main window.

Supports four severity levels: info, success, warning, error.
Auto-dismisses after a configurable timeout (0 = no auto-dismiss).
A close button and the Escape key dismiss it manually.
"""
from __future__ import annotations

from typing import Literal

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

Severity = Literal["info", "success", "warning", "error"]

_ICONS: dict[str, str] = {
    "info":    "ℹ",
    "success": "✓",
    "warning": "⚠",
    "error":   "✕",
}


class NotificationBar(QWidget):
    """
    Thin banner shown beneath the menu bar.

    Signals
    -------
    dismissed : pyqtSignal()
        Emitted when the bar is hidden (button click, timer, or Escape).
    """

    dismissed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NotificationBar")
        self.setFixedHeight(36)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 8, 4)
        layout.setSpacing(8)

        self._icon_label = QLabel(self)
        self._icon_label.setFixedWidth(20)
        layout.addWidget(self._icon_label)

        self._message_label = QLabel(self)
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._message_label, stretch=1)

        self._close_btn = QPushButton("✕", self)
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; "
            "color: #666; font-size: 11pt; }"
            "QPushButton:hover { color: #1a1a1a; }"
        )
        self._close_btn.clicked.connect(self.dismiss)
        layout.addWidget(self._close_btn)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

        self.hide()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def show_message(self, message: str, severity: Severity = "info",
                     timeout_ms: int = 5000) -> None:
        """Display *message* with the given severity for *timeout_ms* ms."""
        self._timer.stop()
        self._message_label.setText(message)
        self._icon_label.setText(_ICONS.get(severity, "ℹ"))
        self.setProperty("severity", severity)
        # Force stylesheet re-evaluation after property change
        self.style().unpolish(self)
        self.style().polish(self)
        self.show()
        if timeout_ms > 0:
            self._timer.start(timeout_ms)

    def dismiss(self) -> None:
        self._timer.stop()
        self.hide()
        self.dismissed.emit()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
        super().keyPressEvent(event)
