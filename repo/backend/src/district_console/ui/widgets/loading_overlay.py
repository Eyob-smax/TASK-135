"""
Semi-transparent loading overlay that covers its parent widget.

Show it when a background API call is in-flight; hide it on completion.
The overlay captures mouse events so the user cannot interact with
the underlying form while a request is pending.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


class LoadingOverlay(QWidget):
    """
    Transparent overlay with a centred spinner label.

    Usage::

        overlay = LoadingOverlay(parent_widget)
        overlay.show()   # before worker.start()
        # ... worker.finished_clean.connect(overlay.hide)
    """

    def __init__(self, parent: QWidget, message: str = "Loading…") -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._label = QLabel(message, self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            "color: #1a1a1a; font-size: 11pt; font-weight: 600;"
            "background: transparent;"
        )
        layout.addWidget(self._label)
        self.hide()

    def set_message(self, message: str) -> None:
        self._label.setText(message)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(243, 243, 243, 200))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        if self.parent():
            self.setGeometry(self.parent().rect())  # type: ignore[union-attr]
        super().resizeEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        if self.parent():
            self.setGeometry(self.parent().rect())  # type: ignore[union-attr]
        self.raise_()
        super().showEvent(event)
