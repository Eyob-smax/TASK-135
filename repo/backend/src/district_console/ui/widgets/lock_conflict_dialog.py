"""
Lock conflict notification dialog.

Shown when a user tries to edit a record that is currently held by another
user's advisory lock. Displays the lock holder's name and expiry time and
offers a Retry option.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class LockConflictDialog(QDialog):
    """
    Modal dialog displayed when a RecordLockedError is encountered.

    After the user clicks Retry, the caller should attempt the locking
    operation again. Cancel aborts the workflow.
    """

    def __init__(
        self,
        entity_label: str,
        holder_name: str,
        expires_at: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Record In Use")
        self.setMinimumWidth(380)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        icon_label = QLabel("🔒", self)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("font-size: 28pt;")
        layout.addWidget(icon_label)

        heading = QLabel(f"<b>{entity_label}</b> is currently locked", self)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setWordWrap(True)
        layout.addWidget(heading)

        info_parts = [f"This record is being edited by <b>{holder_name}</b>."]
        if expires_at:
            info_parts.append(f"The lock expires at {expires_at}.")
        info_parts.append("Please try again in a moment or ask them to close the record.")

        info = QLabel(" ".join(info_parts), self)
        info.setWordWrap(True)
        info.setProperty("subheading", True)
        layout.addWidget(info)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Retry
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
