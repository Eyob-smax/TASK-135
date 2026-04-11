"""
PyQt6 application bootstrap and entry point.

Lifecycle
─────────
1. High-DPI policy configured before QApplication creation.
2. QApplication created; theme applied.
3. bootstrap() (async) called in a temporary event loop to get AppContainer.
4. FastAPI / uvicorn started in a background QThread.
5. SignInDialog shown; on success MainWindow is created and shown.
6. Qt event loop runs until quit.
7. On quit: API server thread is stopped cleanly.

The module exposes ``run_application()`` which is called from
``district_console.bootstrap.__main__``.
"""
from __future__ import annotations

import asyncio
import sys
import time
from typing import Optional

from PyQt6.QtWidgets import QApplication, QMessageBox

from district_console.ui.theme import apply_theme, configure_highdpi
from district_console.ui.state import AppState
from district_console.ui.client import ApiClient
from district_console.ui.tray import SystemTray
from district_console.ui.shell.sign_in_dialog import SignInDialog
from district_console.ui.shell.main_window import MainWindow


# ──────────────────────────────────────────────────────────────────────────────
# Background API server thread
# ──────────────────────────────────────────────────────────────────────────────

class _ApiServerThread:
    """
    Runs the uvicorn ASGI server in a Python daemon thread (not QThread).

    A daemon thread automatically dies when the main thread exits, providing
    a clean shutdown without explicit coordination.
    """

    def __init__(self, api_app, host: str = "127.0.0.1", port: int = 8765) -> None:
        self._api_app = api_app
        self._host = host
        self._port = port
        self._thread: Optional[object] = None

    def start(self) -> None:
        import threading
        import uvicorn

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            config = uvicorn.Config(
                self._api_app,
                host=self._host,
                port=self._port,
                loop="none",
                log_level="error",
                access_log=False,
            )
            server = uvicorn.Server(config)
            loop.run_until_complete(server.serve())

        t = threading.Thread(target=_run, daemon=True, name="dc-api-server")
        t.start()
        self._thread = t

        # Brief wait for the TCP socket to bind before the UI tries to connect
        time.sleep(0.4)


# ──────────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────────


def _load_pending_checkpoints_from_container(state: AppState, container: object) -> None:
    """Copy recovered checkpoints from bootstrap container into UI state."""
    checkpoints = getattr(container, "_active_checkpoints", [])
    if not isinstance(checkpoints, list):
        return

    normalized: list[dict] = []
    for cp in checkpoints:
        if not isinstance(cp, dict):
            continue
        job_id = cp.get("job_id")
        if not job_id:
            continue
        normalized.append(
            {
                "job_type": cp.get("job_type", "unknown"),
                "job_id": str(job_id),
                "state_json": cp.get("state_json", {}),
            }
        )
    state.pending_checkpoints = normalized

def run_application() -> int:
    """
    Bootstrap and run the District Console desktop application.

    Returns the Qt exit code (0 = clean exit).
    """
    # 1. High-DPI must be configured before QApplication
    configure_highdpi()

    app = QApplication(sys.argv)
    app.setApplicationName("District Console")
    app.setApplicationDisplayName("District Resource & Inventory Console")
    app.setOrganizationName("District")
    app.setQuitOnLastWindowClosed(False)  # Keep alive in tray
    apply_theme(app)

    # 2. Bootstrap: run async startup in a temporary event loop
    try:
        from district_console.bootstrap import bootstrap
        loop = asyncio.new_event_loop()
        container = loop.run_until_complete(bootstrap())
        loop.close()
    except Exception as exc:
        QMessageBox.critical(
            None,
            "Startup Error",
            f"Failed to initialise the application:\n\n{exc}\n\n"
            "Please check the database file and restart.",
        )
        return 1

    # 3. Start embedded API server
    api_server = _ApiServerThread(
        container.api_app,
        host=container.config.api_host,
        port=container.config.api_port,
    )
    api_server.start()

    # 4. Shared state and REST client
    state = AppState()
    _load_pending_checkpoints_from_container(state, container)
    client = ApiClient(base_url=container.config.api_url())

    # 5. System tray (visible after login)
    tray = SystemTray(app, state)

    # 6. Sign-in → main window flow
    main_window: Optional[MainWindow] = None
    sign_in: Optional[SignInDialog] = None

    def _show_sign_in() -> None:
        nonlocal sign_in
        sign_in = SignInDialog(client, state)
        sign_in.login_success.connect(_on_login)
        sign_in.show()

    def _on_login() -> None:
        nonlocal main_window, sign_in
        main_window = MainWindow(client, state, tray)
        main_window.logout_requested.connect(_on_logout)
        tray.set_main_window(main_window)
        tray.show()
        main_window.show()
        main_window.show_recovery_prompt()
        if sign_in:
            sign_in.close()

    def _on_logout() -> None:
        nonlocal main_window
        tray.hide()
        if main_window:
            main_window.close()
            main_window.deleteLater()
            main_window = None
        _show_sign_in()

    _show_sign_in()

    exit_code = app.exec()
    client.close()
    return exit_code
