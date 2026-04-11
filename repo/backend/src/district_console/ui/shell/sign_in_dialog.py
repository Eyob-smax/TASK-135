"""
Sign-in dialog — the application entry point after launch.

Shows a username/password form. On success it emits ``login_success`` and
populates AppState. On failure it shows an inline error message without
closing the dialog. Lockout errors show the remaining wait time.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from district_console.ui.client import ApiClient, ApiError
from district_console.ui.state import AppState
from district_console.ui.utils.async_worker import ApiWorker


class SignInDialog(QDialog):
    """
    Modal sign-in dialog.

    Signals
    -------
    login_success : pyqtSignal()
        Emitted after AppState is populated with a valid session.
    """

    login_success = pyqtSignal()

    def __init__(self, client: ApiClient, state: AppState,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._worker: Optional[ApiWorker] = None

        self.setWindowTitle("District Console — Sign In")
        self.setFixedSize(420, 300)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.MSWindowsFixedSizeDialogHint
        )
        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI construction                                                     #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(12)

        title = QLabel("District Console", self)
        title.setProperty("heading", True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Resource & Inventory Operations", self)
        subtitle.setProperty("subheading", True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        self._username_edit = QLineEdit(self)
        self._username_edit.setPlaceholderText("Username")
        self._username_edit.returnPressed.connect(self._do_login)
        layout.addWidget(self._username_edit)

        self._password_edit = QLineEdit(self)
        self._password_edit.setPlaceholderText("Password")
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_edit.returnPressed.connect(self._do_login)
        layout.addWidget(self._password_edit)

        self._error_label = QLabel("", self)
        self._error_label.setProperty("error", True)
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        layout.addWidget(self._error_label)

        self._sign_in_btn = QPushButton("Sign In", self)
        self._sign_in_btn.setDefault(True)
        self._sign_in_btn.clicked.connect(self._do_login)
        layout.addWidget(self._sign_in_btn)

        layout.addStretch()

    # ------------------------------------------------------------------ #
    # Actions                                                             #
    # ------------------------------------------------------------------ #

    def _do_login(self) -> None:
        username = self._username_edit.text().strip()
        password = self._password_edit.text()

        if not username:
            self._show_error("Username is required.")
            self._username_edit.setFocus()
            return
        if not password:
            self._show_error("Password is required.")
            self._password_edit.setFocus()
            return

        self._clear_error()
        self._sign_in_btn.setEnabled(False)
        self._sign_in_btn.setText("Signing in…")

        self._worker = ApiWorker(self._client.login, username, password)
        self._worker.result.connect(self._on_login_success)
        self._worker.error.connect(self._on_login_error)
        self._worker.finished_clean.connect(self._on_worker_done)
        self._worker.start()

    def _on_login_success(self, data: dict) -> None:
        self._client.set_token(data["token"])
        self._state.set_session(
            token=data["token"],
            user_id=data["user_id"],
            username=data["username"],
            roles=data["roles"],
            expires_at=data["expires_at"],
        )
        self.login_success.emit()

    def _on_login_error(self, exc: Exception) -> None:
        if isinstance(exc, ApiError):
            if exc.status_code == 423:
                self._show_error(
                    "Account is temporarily locked due to too many failed attempts."
                )
            elif exc.status_code == 401:
                self._show_error("Invalid username or password.")
            else:
                self._show_error(f"Sign-in failed: {exc.message}")
        else:
            self._show_error(
                "Could not connect to the local service. "
                "Please restart the application."
            )
        self._password_edit.clear()
        self._password_edit.setFocus()

    def _on_worker_done(self) -> None:
        self._sign_in_btn.setEnabled(True)
        self._sign_in_btn.setText("Sign In")

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.show()

    def _clear_error(self) -> None:
        self._error_label.hide()
        self._error_label.setText("")
