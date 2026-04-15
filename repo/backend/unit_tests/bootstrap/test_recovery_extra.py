"""
Additional bootstrap recovery tests covering uncovered branches of
_recover_checkpoints and _resume_recovered_checkpoints.

These exercise:
  * _recover_checkpoints with string / dict / invalid-JSON state_json
  * _resume_recovered_checkpoints with a bad UUID checkpoint_id
  * _resume_recovered_checkpoints when a service raises → mark_failed path
  * _resume_recovered_checkpoints with non-dict state gets normalised to {}
  * _start_scheduler's inner async jobs execute their session bodies
"""
from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import district_console.bootstrap as bootstrap_mod


class _Store:
    def __init__(self):
        self.marks = {"completed": [], "failed": []}
        self._active = []

    def seed(self, cps):
        self._active = list(cps)

    async def get_active(self, session):
        return list(self._active)

    async def mark_completed(self, session, checkpoint_id):
        self.marks["completed"].append(str(checkpoint_id))

    async def mark_failed(self, session, checkpoint_id, reason):
        self.marks["failed"].append((str(checkpoint_id), reason))


class _Instr:
    def __init__(self):
        self.events = []

    def record_recovery_event(self, job_type, job_id, outcome):
        self.events.append((job_type, job_id, outcome))


@asynccontextmanager
async def _begin_noop():
    yield


class _Session:
    def begin(self):
        return _begin_noop()


@asynccontextmanager
async def _factory():
    yield _Session()


def _container_with(store, instr, resource_svc=None, count_svc=None):
    return SimpleNamespace(
        session_factory=_factory,
        checkpoint_store=store,
        resource_service=resource_svc or SimpleNamespace(),
        count_session_service=count_svc or SimpleNamespace(),
        instrumentation=instr,
    )


# ---------------------------------------------------------------------------
# _recover_checkpoints
# ---------------------------------------------------------------------------

async def test_recover_checkpoints_parses_state_dict_and_string_variants():
    store = _Store()
    cp_id_1 = uuid.uuid4()
    cp_id_2 = uuid.uuid4()
    cp_id_3 = uuid.uuid4()
    store.seed([
        SimpleNamespace(
            id=cp_id_1, job_type="import", job_id="j1",
            state_json={"a": 1},  # dict passes through
        ),
        SimpleNamespace(
            id=cp_id_2, job_type="count", job_id="j2",
            state_json=json.dumps({"b": 2}),  # str is parsed
        ),
        SimpleNamespace(
            id=cp_id_3, job_type="approval", job_id="j3",
            state_json="not-valid-json{",  # invalid JSON → {}
        ),
    ])
    container = _container_with(store, _Instr())
    results = await bootstrap_mod._recover_checkpoints(container)

    assert len(results) == 3
    assert results[0]["state_json"] == {"a": 1}
    assert results[1]["state_json"] == {"b": 2}
    assert results[2]["state_json"] == {}


# ---------------------------------------------------------------------------
# _resume_recovered_checkpoints
# ---------------------------------------------------------------------------

async def test_resume_recovered_bad_checkpoint_id_still_runs_handler():
    """A malformed checkpoint_id must not crash; handler runs but no mark is attempted."""
    store = _Store()
    instr = _Instr()
    resource_svc = SimpleNamespace()

    async def _resume_import(session, job_id, state, now):
        return "completed"

    resource_svc.resume_import_checkpoint = _resume_import
    container = _container_with(store, instr, resource_svc=resource_svc)

    checkpoints = [
        {
            "checkpoint_id": "not-a-uuid",
            "job_type": "import",
            "job_id": "import-bad-id",
            "state_json": {},
        }
    ]
    await bootstrap_mod._resume_recovered_checkpoints(container, checkpoints)

    # Handler ran → instrumentation recorded the event
    assert instr.events == [("import", "import-bad-id", "completed")]
    # No UUID → no mark_completed call
    assert store.marks["completed"] == []
    assert store.marks["failed"] == []


async def test_resume_recovered_handler_exception_marks_failed():
    store = _Store()
    instr = _Instr()
    cp_id = uuid.uuid4()

    async def _raise(*args, **kwargs):
        raise RuntimeError("oops")

    resource_svc = SimpleNamespace(resume_import_checkpoint=_raise)
    container = _container_with(store, instr, resource_svc=resource_svc)

    await bootstrap_mod._resume_recovered_checkpoints(container, [
        {
            "checkpoint_id": str(cp_id),
            "job_type": "import",
            "job_id": "broken",
            "state_json": {},
        }
    ])

    assert instr.events == [("import", "broken", "failed")]
    assert len(store.marks["failed"]) == 1
    assert store.marks["failed"][0][0] == str(cp_id)


async def test_resume_recovered_non_dict_state_normalised_to_empty():
    store = _Store()
    instr = _Instr()
    cp_id = uuid.uuid4()

    seen: list = []

    async def _resume(session, job_id, state, now):
        seen.append(state)
        return "completed"

    resource_svc = SimpleNamespace(resume_import_checkpoint=_resume)
    container = _container_with(store, instr, resource_svc=resource_svc)

    await bootstrap_mod._resume_recovered_checkpoints(container, [
        {
            "checkpoint_id": str(cp_id),
            "job_type": "import",
            "job_id": "j-nonedict",
            "state_json": "not-a-dict",  # not a dict → normalized to {}
        }
    ])
    assert seen == [{}]


async def test_resume_recovered_unknown_job_type_skipped():
    """Unknown job types fall through to 'skipped' and do not fail."""
    store = _Store()
    instr = _Instr()
    cp_id = uuid.uuid4()
    container = _container_with(store, instr)
    await bootstrap_mod._resume_recovered_checkpoints(container, [
        {
            "checkpoint_id": str(cp_id),
            "job_type": "unknown_type",
            "job_id": "j",
            "state_json": {},
        }
    ])
    assert instr.events == [("unknown_type", "j", "skipped")]


# ---------------------------------------------------------------------------
# _start_scheduler job bodies
# ---------------------------------------------------------------------------

def test_start_scheduler_invokes_registered_jobs(monkeypatch):
    """Verify each registered job's body actually runs inside a fresh event loop."""
    scheduled = {}

    class _FakeScheduler:
        def add_job(self, fn, trigger, id, replace_existing):
            scheduled[id] = fn

        def start(self):
            return None

    import apscheduler.schedulers.background as bg
    import apscheduler.triggers.interval as interval

    monkeypatch.setattr(bg, "BackgroundScheduler", _FakeScheduler)
    # Replace IntervalTrigger with a light stub so construction doesn't rely on apscheduler internals
    monkeypatch.setattr(interval, "IntervalTrigger", lambda **kwargs: kwargs)

    # Build a minimal container with async services whose bodies accept (session, now)
    call_log: list[str] = []

    @asynccontextmanager
    async def _begin():
        yield

    class _FactorySession:
        def begin(self):
            return _begin()

        async def execute(self, stmt):
            class _Result:
                def scalars(self):
                    class _S:
                        def all(self):
                            return []

                    return _S()

            return _Result()

    @asynccontextmanager
    async def _factory2():
        yield _FactorySession()

    class _CountSvc:
        async def check_and_expire(self, session, sid, now):
            call_log.append(("expire", str(sid)))

    class _IntegrationSvc:
        async def retry_pending_events(self, session, now):
            call_log.append(("retry", now.year))

        async def enforce_key_lifecycle(self, session, now):
            call_log.append(("lifecycle", now.year))

    container = SimpleNamespace(
        session_factory=_factory2,
        count_session_service=_CountSvc(),
        integration_service=_IntegrationSvc(),
    )

    bootstrap_mod._start_scheduler(container)
    assert set(scheduled.keys()) == {
        "expire_count_sessions",
        "retry_pending_events",
        "enforce_hmac_key_lifecycle",
    }

    # Invoke each scheduled callable — they spin up their own event loops
    scheduled["retry_pending_events"]()
    scheduled["enforce_hmac_key_lifecycle"]()
    scheduled["expire_count_sessions"]()

    event_names = [e[0] for e in call_log]
    assert "retry" in event_names
    assert "lifecycle" in event_names
    # expire job iterates an empty scalars().all(), so no call to check_and_expire — that's OK.
