"""
PyQt6 desktop UI layer for the District Resource & Inventory Operations Console.

Module map
──────────
ui/app.py           Application bootstrap, QApplication creation, run_application()
ui/state.py         AppState — shared session and permission state
ui/client.py        ApiClient — synchronous httpx wrapper for local REST calls
ui/theme.py         Windows 11 Fluent palette, high-DPI configuration
ui/shortcuts.py     ShortcutManager — global keyboard shortcut registration
ui/tray.py          SystemTray — minimize-to-tray, notifications, safe quit
ui/shell/           MainWindow, SignInDialog, WorkspaceCoordinator
ui/widgets/         Reusable feedback widgets (loading, notification, empty state, dialogs)
ui/screens/         Business screens: dashboard, resources, inventory, count sessions,
                    approvals, classification, allocations
ui/utils/           Async worker QThread pattern

Architectural contract
──────────────────────
- No business logic or persistence in the UI layer.
- All data access is via ApiClient → local FastAPI REST service.
- All I/O is performed in ApiWorker (QThread) to keep the Qt main thread responsive.
- Role-based visibility uses AppState.has_permission() which mirrors the
  server-side RbacService permission model.
"""
