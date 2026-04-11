"""
Session status widget — shows current user, roles, and session expiry.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import QFormLayout, QLabel, QWidget

from district_console.ui.state import AppState


class SessionStatusWidget(QWidget):
    def __init__(self, state: AppState, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = state
        self._build_ui()

    def _build_ui(self) -> None:
        form = QFormLayout(self)
        form.setContentsMargins(20, 16, 20, 16)
        form.setSpacing(10)

        self._user_lbl = QLabel(self._state.username or "—")
        form.addRow("Username:", self._user_lbl)

        roles = ", ".join(self._state.roles) if self._state.roles else "—"
        self._roles_lbl = QLabel(roles)
        form.addRow("Roles:", self._roles_lbl)

        self._expiry_lbl = QLabel(
            (self._state.expires_at or "")[:19] or "—"
        )
        form.addRow("Session Expires:", self._expiry_lbl)
