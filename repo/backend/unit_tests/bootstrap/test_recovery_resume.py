from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import district_console.bootstrap as bootstrap_mod


def _make_container():
    marks = {"completed": [], "failed": []}
    recoveries = []

    class _Store:
        async def mark_completed(self, session, checkpoint_id):
            marks["completed"].append(str(checkpoint_id))

        async def mark_failed(self, session, checkpoint_id, reason):
            marks["failed"].append((str(checkpoint_id), reason))

    class _ResourceSvc:
        async def resume_import_checkpoint(self, session, job_id, state, now):
            if job_id == "import-done":
                return "completed"
            return "abandoned"

    class _CountSvc:
        async def resume_count_checkpoint(self, session, session_id, now):
            return "resumed"

        async def resume_approval_checkpoint(self, session, session_id):
            return "completed"

    class _Instr:
        def record_recovery_event(self, job_type, job_id, outcome):
            recoveries.append((job_type, job_id, outcome))

    @asynccontextmanager
    async def _begin():
        yield

    class _Session:
        def begin(self):
            return _begin()

    @asynccontextmanager
    async def _factory():
        yield _Session()

    container = SimpleNamespace(
        session_factory=_factory,
        checkpoint_store=_Store(),
        resource_service=_ResourceSvc(),
        count_session_service=_CountSvc(),
        instrumentation=_Instr(),
    )
    return container, marks, recoveries


async def test_resume_recovered_checkpoints_marks_status_and_instruments():
    container, marks, recoveries = _make_container()
    checkpoints = [
        {
            "checkpoint_id": str(uuid.uuid4()),
            "job_type": "import",
            "job_id": "import-done",
            "state_json": {},
        },
        {
            "checkpoint_id": str(uuid.uuid4()),
            "job_type": "import",
            "job_id": "import-abandon",
            "state_json": {},
        },
        {
            "checkpoint_id": str(uuid.uuid4()),
            "job_type": "count",
            "job_id": str(uuid.uuid4()),
            "state_json": {},
        },
        {
            "checkpoint_id": str(uuid.uuid4()),
            "job_type": "approval",
            "job_id": str(uuid.uuid4()),
            "state_json": {},
        },
    ]

    await bootstrap_mod._resume_recovered_checkpoints(container, checkpoints)

    assert len(marks["completed"]) == 2
    assert len(marks["failed"]) == 1
    assert len(recoveries) == 4


def test_start_scheduler_registers_key_lifecycle_job(monkeypatch):
    added_jobs = []

    class _FakeScheduler:
        def add_job(self, fn, trigger, id, replace_existing):
            added_jobs.append(id)

        def start(self):
            return None

    class _FakeTrigger:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    import apscheduler.schedulers.background as bg
    import apscheduler.triggers.interval as interval

    monkeypatch.setattr(bg, "BackgroundScheduler", _FakeScheduler)
    monkeypatch.setattr(interval, "IntervalTrigger", _FakeTrigger)

    @asynccontextmanager
    async def _begin():
        yield

    class _Session:
        def begin(self):
            return _begin()

    @asynccontextmanager
    async def _factory():
        yield _Session()

    container = SimpleNamespace(
        session_factory=_factory,
        count_session_service=SimpleNamespace(check_and_expire=lambda *args, **kwargs: None),
        integration_service=SimpleNamespace(
            retry_pending_events=lambda *args, **kwargs: None,
            enforce_key_lifecycle=lambda *args, **kwargs: None,
        ),
    )

    bootstrap_mod._start_scheduler(container)

    assert "expire_count_sessions" in added_jobs
    assert "retry_pending_events" in added_jobs
    assert "enforce_hmac_key_lifecycle" in added_jobs