"""
Unit tests for CheckpointStore: save, load, mark_completed, mark_failed, get_active.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from district_console.domain.enums import CheckpointStatus
from district_console.domain.exceptions import DomainValidationError
from district_console.infrastructure.checkpoint_store import CheckpointStore
from district_console.infrastructure.repositories import CheckpointRepository


class TestCheckpointStore:
    async def test_save_creates_active_checkpoint(self, db_session) -> None:
        store = CheckpointStore(CheckpointRepository())
        cp = await store.save(
            db_session,
            job_type="import",
            job_id="batch-001",
            state={"processed": 0, "total": 100},
        )
        assert cp.job_type == "import"
        assert cp.job_id == "batch-001"
        assert cp.status == CheckpointStatus.ACTIVE

    async def test_load_returns_saved_state(self, db_session) -> None:
        store = CheckpointStore(CheckpointRepository())
        await store.save(
            db_session,
            job_type="count",
            job_id="session-abc",
            state={"lines_processed": 42},
        )
        loaded = await store.load(db_session, "count", "session-abc")
        assert loaded is not None
        assert loaded.job_type == "count"
        assert loaded.job_id == "session-abc"
        # state_json should contain our data
        import json
        state = json.loads(loaded.state_json)
        assert state["lines_processed"] == 42

    async def test_load_nonexistent_returns_none(self, db_session) -> None:
        store = CheckpointStore(CheckpointRepository())
        result = await store.load(db_session, "import", "nonexistent-id")
        assert result is None

    async def test_mark_completed_updates_status(self, db_session) -> None:
        store = CheckpointStore(CheckpointRepository())
        cp = await store.save(
            db_session,
            job_type="scheduled",
            job_id="job-001",
            state={"step": 1},
        )
        await store.mark_completed(db_session, cp.id)

        loaded = await store.load(db_session, "scheduled", "job-001")
        assert loaded is not None
        assert loaded.status == CheckpointStatus.COMPLETED

    async def test_mark_failed_stores_reason_in_state_json(
        self, db_session
    ) -> None:
        store = CheckpointStore(CheckpointRepository())
        cp = await store.save(
            db_session,
            job_type="approval",
            job_id="review-001",
            state={"current_step": 3},
        )
        await store.mark_failed(db_session, cp.id, reason="Connection timeout")

        loaded = await store.load(db_session, "approval", "review-001")
        assert loaded is not None
        assert loaded.status == CheckpointStatus.FAILED
        import json
        state = json.loads(loaded.state_json)
        assert state["failure_reason"] == "Connection timeout"

    async def test_get_active_excludes_non_active_records(
        self, db_session
    ) -> None:
        store = CheckpointStore(CheckpointRepository())

        # Create one ACTIVE and one COMPLETED
        active_cp = await store.save(
            db_session, "import", "active-job", {"step": 1}
        )
        done_cp = await store.save(
            db_session, "count", "done-job", {"step": 99}
        )
        await store.mark_completed(db_session, done_cp.id)

        active_list = await store.get_active(db_session)
        active_ids = [str(cp.id) for cp in active_list]
        assert str(active_cp.id) in active_ids
        assert str(done_cp.id) not in active_ids

    async def test_save_invalid_job_type_raises(self, db_session) -> None:
        store = CheckpointStore(CheckpointRepository())
        with pytest.raises(DomainValidationError) as exc_info:
            await store.save(
                db_session,
                job_type="invalid_type",
                job_id="x",
                state={},
            )
        assert exc_info.value.field == "job_type"

    async def test_save_upserts_existing_checkpoint(self, db_session) -> None:
        """Re-saving with same job_type/job_id should update state, not insert a duplicate."""
        store = CheckpointStore(CheckpointRepository())
        cp1 = await store.save(
            db_session, "import", "batch-999", {"step": 1}
        )
        cp2 = await store.save(
            db_session, "import", "batch-999", {"step": 5}
        )
        # Same ID (upsert)
        assert cp1.id == cp2.id
        import json
        loaded = await store.load(db_session, "import", "batch-999")
        assert loaded is not None
        assert json.loads(loaded.state_json)["step"] == 5
