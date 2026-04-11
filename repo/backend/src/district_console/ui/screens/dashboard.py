"""
Dashboard / home workspace.

Shows role-appropriate summary cards that give a quick operational picture:
  - Pending review tasks (Reviewer / Administrator)
  - Active count sessions (Librarian / Administrator)
  - Pending approvals waiting for sign-off (Administrator)
  - Quick-launch buttons for the most common workflows per role

Data is loaded asynchronously via ApiWorker. Each card has its own worker
so a slow endpoint does not block faster cards.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from district_console.ui.client import ApiClient
from district_console.ui.state import AppState
from district_console.ui.utils.async_worker import ApiWorker
from district_console.ui.widgets.loading_overlay import LoadingOverlay


class _SummaryCard(QFrame):
    """
    A single summary card with a numeric value, label, and optional action.
    """

    def __init__(self, icon: str, label: str,
                 action_label: str = "",
                 action_callback=None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumSize(220, 110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        header = QHBoxLayout()
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size: 20pt;")
        header.addWidget(icon_lbl)
        header.addStretch()
        layout.addLayout(header)

        self._value_label = QLabel("—")
        self._value_label.setStyleSheet(
            "font-size: 26pt; font-weight: 700;"
        )
        layout.addWidget(self._value_label)

        lbl = QLabel(label)
        lbl.setProperty("subheading", True)
        layout.addWidget(lbl)

        if action_label and action_callback:
            btn = QPushButton(action_label)
            btn.setProperty("flat", True)
            btn.setStyleSheet("text-align: left; padding: 0;")
            btn.clicked.connect(action_callback)
            layout.addWidget(btn)

    def set_value(self, value: str) -> None:
        self._value_label.setText(value)

    def set_error(self) -> None:
        self._value_label.setText("!")
        self._value_label.setStyleSheet(
            "font-size: 26pt; font-weight: 700; color: #c42b1c;"
        )


class DashboardWidget(QWidget):
    """
    Home screen showing role-appropriate operational summary.

    Parameters
    ----------
    parent_window : QMainWindow, optional
        Reference to the shell window for cross-screen navigation triggers.
    """

    def __init__(self, client: ApiClient, state: AppState,
                 parent_window=None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._state = state
        self._parent_window = parent_window
        self._workers: list[ApiWorker] = []

        self._build_ui()
        self.load_data()

    # ------------------------------------------------------------------ #
    # UI construction                                                     #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # Heading
        heading = QLabel(
            f"Good day, {self._state.username or 'User'}"
        )
        heading.setProperty("heading", True)
        root.addWidget(heading)

        roles_txt = ", ".join(self._state.roles) if self._state.roles else "—"
        sub = QLabel(f"Signed in as: {roles_txt}")
        sub.setProperty("subheading", True)
        root.addWidget(sub)

        # Cards grid
        self._cards_grid = QGridLayout()
        self._cards_grid.setSpacing(16)
        root.addLayout(self._cards_grid)
        self._build_cards()

        # Quick-launch section
        launch_heading = QLabel("Quick Launch")
        launch_heading.setStyleSheet("font-weight: 600; margin-top: 8px;")
        root.addWidget(launch_heading)

        launch_row = QHBoxLayout()
        self._build_quick_launch(launch_row)
        root.addLayout(launch_row)

        root.addStretch()

        self._overlay = LoadingOverlay(self)

    def _build_cards(self) -> None:
        col = 0
        row = 0

        if self._state.has_permission("resources.view"):
            self._card_resources = _SummaryCard(
                "📚", "Published Resources",
                "View Library →",
                lambda: self._nav("resources"),
            )
            self._cards_grid.addWidget(self._card_resources, row, col)
            col += 1

        if self._state.has_permission("resources.publish"):
            self._card_reviews = _SummaryCard(
                "🔍", "Pending Reviews",
                "Open Review Queue →",
                lambda: self._nav("approvals"),
            )
            self._cards_grid.addWidget(self._card_reviews, row, col)
            col += 1

        if self._state.has_permission("inventory.count"):
            self._card_counts = _SummaryCard(
                "📦", "Active Count Sessions",
                "Open Count Sessions →",
                lambda: self._nav("count_sessions"),
            )
            self._cards_grid.addWidget(self._card_counts, row, col)
            col += 1

        if self._state.has_permission("inventory.view"):
            if col >= 3:
                col = 0
                row += 1
            self._card_stock = _SummaryCard(
                "🏭", "Stock Locations",
                "View Inventory →",
                lambda: self._nav("inventory"),
            )
            self._cards_grid.addWidget(self._card_stock, row, col)

    def _build_quick_launch(self, layout: QHBoxLayout) -> None:
        buttons: list[tuple[str, str, str]] = []

        if self._state.has_permission("resources.create"):
            buttons.append(("＋ New Resource", "resources", "resources.create"))
        if self._state.has_permission("inventory.adjust"):
            buttons.append(("＋ Adjustment", "inventory", "inventory.adjust"))
        if self._state.has_permission("inventory.count"):
            buttons.append(("▶ New Count Session", "count_sessions", "inventory.count"))
        if self._state.has_permission("resources.publish"):
            buttons.append(("✓ Review Queue", "approvals", "resources.publish"))

        for label, key, _ in buttons:
            btn = QPushButton(label)
            btn.setFixedHeight(40)
            btn.clicked.connect(lambda _checked, k=key: self._nav(k))
            layout.addWidget(btn)
        layout.addStretch()

    # ------------------------------------------------------------------ #
    # Data loading                                                        #
    # ------------------------------------------------------------------ #

    def load_data(self) -> None:
        """Refresh all summary cards."""
        if self._state.has_permission("resources.view"):
            self._load_resource_count()

    def _load_resource_count(self) -> None:
        worker = ApiWorker(
            self._client.list_resources, offset=0, limit=1,
            status="PUBLISHED"
        )
        worker.result.connect(self._on_resources_loaded)
        worker.error.connect(lambda _: self._safe_card_error("resources"))
        worker.start()
        self._workers.append(worker)

    def _on_resources_loaded(self, data: dict) -> None:
        total = data.get("total", 0)
        if hasattr(self, "_card_resources"):
            self._card_resources.set_value(str(total))

    def _safe_card_error(self, card_name: str) -> None:
        card = getattr(self, f"_card_{card_name}", None)
        if card:
            card.set_error()

    # ------------------------------------------------------------------ #
    # Navigation helper                                                   #
    # ------------------------------------------------------------------ #

    def _nav(self, key: str) -> None:
        if self._parent_window and hasattr(self._parent_window, "workspace"):
            self._parent_window.workspace.open(
                key, title=key.replace("_", " ").title()
            )
