"""
Checkpoint recovery / resume dialog.

Shown on startup when one or more ACTIVE checkpoints are discovered by the
bootstrap layer. Lets the user choose to resume or discard each job.

Each checkpoint entry is displayed with its job_type, job_id, and progress
state so the user has enough context to decide.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class RecoveryDialog(QDialog):
    """
    Lists pending checkpoints and lets the user select which to resume.

    After ``exec()``, call ``selected_checkpoints()`` to retrieve the list
    of job-id strings the user chose to resume.
    """

    def __init__(
        self,
        checkpoints: list[dict],
        parent: Optional[QWidget] = None,
    ) -> None:
        """
        Parameters
        ----------
        checkpoints : list[dict]
            Each dict: ``{job_type, job_id, state_json}``.
        """
        super().__init__(parent)
        self.setWindowTitle("Resume Interrupted Work")
        self.setMinimumWidth(480)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self._checkboxes: list[tuple[str, QCheckBox]] = []
        self._build_ui(checkpoints)

    def _build_ui(self, checkpoints: list[dict]) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        heading = QLabel(
            "The application was closed while background jobs were running.\n"
            "Select the jobs you want to resume:",
            self,
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)

        scroll_container = QWidget(self)
        scroll_layout = QVBoxLayout(scroll_container)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(6)

        for cp in checkpoints:
            job_type = cp.get("job_type", "unknown")
            job_id = cp.get("job_id", "")
            state = cp.get("state_json", {})

            cb = QCheckBox(self)
            cb.setChecked(True)
            label_text = f"<b>{job_type.upper()}</b> — {job_id[:36]}"
            if isinstance(state, dict) and "progress" in state:
                label_text += f"  ({state['progress']})"
            cb.setText(label_text)
            scroll_layout.addWidget(cb)
            self._checkboxes.append((job_id, cb))

        scroll = QScrollArea(self)
        scroll.setWidget(scroll_container)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(220)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        layout.addWidget(scroll)

        note = QLabel(
            "Unchecked jobs will be marked as abandoned and cannot be resumed later.",
            self,
        )
        note.setWordWrap(True)
        note.setProperty("subheading", True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Resume Selected")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Skip All")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_checkpoints(self) -> list[str]:
        """Return job_id strings for checkpoints the user chose to resume."""
        return [jid for jid, cb in self._checkboxes if cb.isChecked()]
