"""
Tests for startup recovery state hydration in ui.app.
"""
from __future__ import annotations

from types import SimpleNamespace

from district_console.ui.app import _load_pending_checkpoints_from_container
from district_console.ui.state import AppState


def test_load_pending_checkpoints_hydrates_state_from_container() -> None:
    state = AppState()
    container = SimpleNamespace(
        _active_checkpoints=[
            {"job_type": "import", "job_id": "job-1", "state_json": {"progress": "10/20"}},
            {"job_type": "count", "job_id": "job-2", "state_json": {"step": "awaiting_approval"}},
        ]
    )

    _load_pending_checkpoints_from_container(state, container)

    assert len(state.pending_checkpoints) == 2
    assert state.pending_checkpoints[0]["job_type"] == "import"
    assert state.pending_checkpoints[0]["job_id"] == "job-1"
    assert state.pending_checkpoints[0]["state_json"]["progress"] == "10/20"


def test_load_pending_checkpoints_ignores_invalid_entries() -> None:
    state = AppState()
    container = SimpleNamespace(
        _active_checkpoints=[
            {"job_type": "import"},  # missing job_id
            "not-a-dict",
            {"job_type": "approval", "job_id": "job-3"},
        ]
    )

    _load_pending_checkpoints_from_container(state, container)

    assert state.pending_checkpoints == [
        {"job_type": "approval", "job_id": "job-3", "state_json": {}}
    ]
