"""Reusable desktop-wide feedback and utility widgets."""
from district_console.ui.widgets.empty_state import EmptyStateWidget
from district_console.ui.widgets.loading_overlay import LoadingOverlay
from district_console.ui.widgets.lock_conflict_dialog import LockConflictDialog
from district_console.ui.widgets.notification_bar import NotificationBar
from district_console.ui.widgets.recovery_dialog import RecoveryDialog

__all__ = [
    "EmptyStateWidget",
    "LoadingOverlay",
    "LockConflictDialog",
    "NotificationBar",
    "RecoveryDialog",
]
