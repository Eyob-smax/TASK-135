"""
Tests for RecoveryDialog — pending checkpoint display and selection.
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QCheckBox, QDialogButtonBox

from district_console.ui.widgets.recovery_dialog import RecoveryDialog


@pytest.fixture
def checkpoints():
    return [
        {"job_type": "import", "job_id": "cp-001", "state_json": {"progress": "5/10"}},
        {"job_type": "count", "job_id": "cp-002", "state_json": {}},
    ]


@pytest.fixture
def dialog(qtbot, checkpoints):
    d = RecoveryDialog(checkpoints)
    qtbot.addWidget(d)
    return d


class TestRecoveryDialogDisplay:
    def test_dialog_shows_all_checkpoints(self, dialog, checkpoints):
        assert len(dialog._checkboxes) == len(checkpoints)

    def test_checkboxes_checked_by_default(self, dialog):
        for _jid, cb in dialog._checkboxes:
            assert cb.isChecked()

    def test_dialog_title_mentions_resume(self, dialog):
        assert "Resume" in dialog.windowTitle()

    def test_checkpoint_job_ids_shown(self, dialog, checkpoints):
        checkbox_texts = [cb.text() for _jid, cb in dialog._checkboxes]
        for cp in checkpoints:
            assert any(cp["job_id"][:8] in t for t in checkbox_texts)


class TestRecoveryDialogSelection:
    def test_all_selected_when_all_checked(self, dialog, checkpoints):
        # By default all are checked
        selected = dialog.selected_checkpoints()
        assert set(selected) == {"cp-001", "cp-002"}

    def test_deselect_one_removes_from_selected(self, dialog):
        # Uncheck the first checkbox
        _jid, first_cb = dialog._checkboxes[0]
        first_cb.setChecked(False)
        selected = dialog.selected_checkpoints()
        assert "cp-001" not in selected
        assert "cp-002" in selected

    def test_deselect_all_returns_empty(self, dialog):
        for _jid, cb in dialog._checkboxes:
            cb.setChecked(False)
        assert dialog.selected_checkpoints() == []


class TestRecoveryDialogEmptyCheckpoints:
    def test_empty_checkpoints_list_creates_dialog(self, qtbot):
        d = RecoveryDialog([])
        qtbot.addWidget(d)
        assert len(d._checkboxes) == 0
        assert d.selected_checkpoints() == []
