"""
Tests for SignInDialog — login flow, error states, and shell transitions.

Uses pytest-qt's qtbot for widget lifecycle management and a mock ApiClient.
All tests are synchronous (Qt widget tests do not require asyncio_mode).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import Qt

from district_console.ui.client import ApiError
from district_console.ui.shell.sign_in_dialog import SignInDialog
from district_console.ui.state import AppState


@pytest.fixture
def state():
    return AppState()


@pytest.fixture
def mock_client():
    client = MagicMock()
    return client


@pytest.fixture
def sign_in_dialog(qtbot, mock_client, state):
    dialog = SignInDialog(mock_client, state)
    qtbot.addWidget(dialog)
    return dialog


class TestSignInDialogInit:
    def test_dialog_has_username_and_password_fields(self, sign_in_dialog):
        assert sign_in_dialog._username_edit is not None
        assert sign_in_dialog._password_edit is not None

    def test_password_field_uses_echo_mode_password(self, sign_in_dialog):
        from PyQt6.QtWidgets import QLineEdit
        assert (sign_in_dialog._password_edit.echoMode()
                == QLineEdit.EchoMode.Password)

    def test_error_label_hidden_initially(self, sign_in_dialog):
        assert not sign_in_dialog._error_label.isVisible()

    def test_sign_in_button_enabled_initially(self, sign_in_dialog):
        assert sign_in_dialog._sign_in_btn.isEnabled()

    def test_window_title_contains_sign_in(self, sign_in_dialog):
        assert "Sign In" in sign_in_dialog.windowTitle()


class TestSignInDialogValidation:
    def test_empty_username_shows_error(self, qtbot, sign_in_dialog):
        sign_in_dialog._username_edit.clear()
        sign_in_dialog._password_edit.setText("somepassword")
        qtbot.mouseClick(sign_in_dialog._sign_in_btn, Qt.MouseButton.LeftButton)
        assert sign_in_dialog._error_label.isVisible()
        assert "Username" in sign_in_dialog._error_label.text()

    def test_empty_password_shows_error(self, qtbot, sign_in_dialog):
        sign_in_dialog._username_edit.setText("alice")
        sign_in_dialog._password_edit.clear()
        qtbot.mouseClick(sign_in_dialog._sign_in_btn, Qt.MouseButton.LeftButton)
        assert sign_in_dialog._error_label.isVisible()
        assert "Password" in sign_in_dialog._error_label.text()


class TestSignInDialogLoginSuccess:
    def test_login_success_populates_state_and_emits_signal(
        self, qtbot, mock_client, state
    ):
        mock_client.login.return_value = {
            "token": "tok123",
            "user_id": "uid-abc",
            "username": "alice",
            "roles": ["LIBRARIAN"],
            "expires_at": "2026-04-10T18:00:00",
        }
        dialog = SignInDialog(mock_client, state)
        qtbot.addWidget(dialog)

        login_fired = []
        dialog.login_success.connect(lambda: login_fired.append(True))

        dialog._username_edit.setText("alice")
        dialog._password_edit.setText("SecurePassword1!")

        # Simulate the worker completing synchronously by calling the slot
        dialog._on_login_success(mock_client.login.return_value)

        assert state.is_authenticated()
        assert state.username == "alice"
        assert state.has_role("LIBRARIAN")
        assert login_fired

    def test_login_populates_token_in_state(self, mock_client, state):
        data = {
            "token": "tok-xyz",
            "user_id": "uid-1",
            "username": "bob",
            "roles": ["ADMINISTRATOR"],
            "expires_at": "2026-04-10T20:00:00",
        }
        dialog = SignInDialog(mock_client, state)
        dialog._on_login_success(data)
        assert state.token == "tok-xyz"


class TestSignInDialogLoginError:
    def test_invalid_credentials_shows_error_message(
        self, qtbot, mock_client, state
    ):
        dialog = SignInDialog(mock_client, state)
        qtbot.addWidget(dialog)
        exc = ApiError(401, "INVALID_CREDENTIALS", "Invalid credentials")
        dialog._on_login_error(exc)
        assert dialog._error_label.isVisible()
        assert "Invalid" in dialog._error_label.text()

    def test_lockout_error_shows_lockout_message(
        self, qtbot, mock_client, state
    ):
        dialog = SignInDialog(mock_client, state)
        qtbot.addWidget(dialog)
        exc = ApiError(423, "ACCOUNT_LOCKED", "Account locked")
        dialog._on_login_error(exc)
        assert "locked" in dialog._error_label.text().lower()

    def test_sign_in_button_re_enabled_after_error(
        self, qtbot, mock_client, state
    ):
        dialog = SignInDialog(mock_client, state)
        qtbot.addWidget(dialog)
        dialog._on_worker_done()
        assert dialog._sign_in_btn.isEnabled()
        assert dialog._sign_in_btn.text() == "Sign In"
