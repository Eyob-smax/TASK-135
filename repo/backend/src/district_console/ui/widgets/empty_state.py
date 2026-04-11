"""
Empty-state placeholder widget shown when a list or table has no rows.

Displays a centred icon glyph, a short heading, and an optional action button
(e.g. "Create first item").
"""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QLabel,
    QWidget,
)


class EmptyStateWidget(QWidget):
    """
    Centred empty-state panel.

    Parameters
    ----------
    icon : str
        Unicode glyph used as a large icon (e.g. "📦", "📚").
    heading : str
        Short primary message, e.g. "No items found".
    subtext : str, optional
        Secondary helper text.
    action_label : str, optional
        Label for the call-to-action button; if None the button is omitted.
    action_callback : callable, optional
        Slot connected to the action button.
    """

    def __init__(
        self,
        icon: str = "📋",
        heading: str = "Nothing here yet",
        subtext: str = "",
        action_label: Optional[str] = None,
        action_callback: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        icon_label = QLabel(icon, self)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("font-size: 40pt;")
        layout.addWidget(icon_label)

        heading_label = QLabel(heading, self)
        heading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading_label.setProperty("heading", True)
        layout.addWidget(heading_label)

        if subtext:
            sub_label = QLabel(subtext, self)
            sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sub_label.setProperty("subheading", True)
            sub_label.setWordWrap(True)
            layout.addWidget(sub_label)

        if action_label and action_callback:
            btn = QPushButton(action_label, self)
            btn.setFixedWidth(200)
            btn.clicked.connect(action_callback)
            layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)
