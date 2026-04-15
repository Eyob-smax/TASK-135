"""
Additional ResourceService tests covering uncovered branches:

  * import_file with metadata_dict (ResourceMetadata persistence path)
  * import_csv: normal flow + checkpoint save every 10 rows + errors
  * resume_import_checkpoint: valid state, no state, already-completed, bad UUID, bad progress
  * create_revision: not found + exceeds MAX_RESOURCE_REVISIONS
  * get_resource / list_revisions: not found
  * classify_resource: not found + success
  * request_allocation: not found + success
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.auth_service import AuthService
from district_console.application.resource_service import ResourceService
from district_console.domain.enums import ResourceType, ResourceStatus
from district_console.domain.exceptions import ResourceNotFoundError
from district_console.domain.policies import MAX_RESOURCE_REVISIONS
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.checkpoint_store import CheckpointStore
from district_console.infrastructure.lock_manager import LockManager
from district_console.infrastructure.orm import UserORM
from district_console.infrastructure.repositories import (
    AuditRepository,
    CheckpointRepository,
    LockRepository,
    ResourceMetadataRepository,
    ResourceRepository,
    ResourceRevisionRepository,
    ReviewTaskRepository,
    RoleRepository,
    UserRepository,
)


def _make_service() -> ResourceService:
    return ResourceService(
        ResourceRepository(),
        ResourceRevisionRepository(),
        ReviewTaskRepository(),
        ResourceMetadataRepository(),
        AuditWriter(AuditRepository()),
        LockManager(LockRepository()),
        CheckpointStore(CheckpointRepository()),
    )


NOW = datetime(2024, 6, 1, 10, 0, 0)
ACTOR = uuid.uuid4()


@pytest.fixture(autouse=True)
async def _seed_actor(db_session: AsyncSession) -> None:
    auth = AuthService(UserRepository(), RoleRepository())
    now = datetime.utcnow().isoformat()
    db_session.add(
        UserORM(
            id=str(ACTOR),
            username="resource_extra_actor",
            password_hash=auth.hash_password("SecurePassword1!"),
            is_active=True,
            failed_attempts=0,
            locked_until=None,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.flush()


# ---------------------------------------------------------------------------
# Import with metadata
# ---------------------------------------------------------------------------

async def test_import_file_persists_metadata_when_provided(db_session: AsyncSession):
    svc = _make_service()
    metadata_dict = {
        "age_range_min": 10,
        "age_range_max": 14,
    }
    resource, _ = await svc.import_file(
        db_session,
        content=b"hello world",
        resource_type=ResourceType.BOOK,
        title="Metadata Book",
        isbn=None,
        metadata_dict=metadata_dict,
        imported_by=ACTOR,
        now=NOW,
    )
    stored = await svc.get_resource_metadata(db_session, resource.id)
    assert stored is not None
    assert stored.age_range_min == 10
    assert stored.age_range_max == 14


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

def _csv_with(rows: list[dict]) -> str:
    buf = io.StringIO()
    import csv as _csv

    writer = _csv.DictWriter(buf, fieldnames=["title", "resource_type", "isbn"])
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue()


async def test_import_csv_creates_duplicates_and_errors(db_session: AsyncSession):
    svc = _make_service()
    csv_text = _csv_with(
        [
            {"title": "Alpha", "resource_type": "BOOK", "isbn": "ISBN-1"},
            {"title": "Alpha", "resource_type": "BOOK", "isbn": "ISBN-1"},  # duplicate
            {"title": "Beta", "resource_type": "BAD_TYPE_ENUM", "isbn": ""},  # error
        ]
    )
    result = await svc.import_csv(db_session, csv_text, ACTOR, "job-csv-1", NOW)
    assert len(result["created"]) == 1
    assert len(result["duplicates"]) == 1
    assert len(result["errors"]) == 1
    assert result["checkpoint_id"]


async def test_import_csv_persists_progress_checkpoint_every_ten(db_session: AsyncSession):
    svc = _make_service()
    rows = [
        {"title": f"Title-{i}", "resource_type": "BOOK", "isbn": f"ISBN-{i:04d}"}
        for i in range(12)
    ]
    csv_text = _csv_with(rows)
    result = await svc.import_csv(db_session, csv_text, ACTOR, "job-csv-progress", NOW)
    assert len(result["created"]) == 12

    # Checkpoint for this job should have completed state
    repo = CheckpointRepository()
    cp = await repo.get(db_session, "import", "job-csv-progress")
    assert cp is not None


# ---------------------------------------------------------------------------
# resume_import_checkpoint
# ---------------------------------------------------------------------------

async def test_resume_import_checkpoint_abandoned_for_missing_state(
    db_session: AsyncSession,
):
    svc = _make_service()
    outcome = await svc.resume_import_checkpoint(db_session, "job-A", {}, NOW)
    assert outcome == "abandoned"


async def test_resume_import_checkpoint_abandoned_for_bad_uuid(
    db_session: AsyncSession,
):
    svc = _make_service()
    state = {"csv_text": "title,resource_type,isbn\nA,BOOK,\n", "imported_by": "not-a-uuid"}
    outcome = await svc.resume_import_checkpoint(db_session, "job-B", state, NOW)
    assert outcome == "abandoned"


async def test_resume_import_checkpoint_already_completed_returns_completed(
    db_session: AsyncSession,
):
    """progress >= len(rows) means the job already finished — resume returns 'completed'."""
    svc = _make_service()
    csv_text = "title,resource_type,isbn\nA,BOOK,\nB,BOOK,\n"
    # First run a real import to create a checkpoint record (so load returns it)
    job_id = "job-completed"
    await svc.import_csv(db_session, csv_text, ACTOR, job_id, NOW)
    state = {
        "csv_text": csv_text,
        "imported_by": str(ACTOR),
        "progress": 99,
    }
    outcome = await svc.resume_import_checkpoint(db_session, job_id, state, NOW)
    assert outcome == "completed"


async def test_resume_import_checkpoint_resumes_partial_run(db_session: AsyncSession):
    svc = _make_service()
    rows = [
        {"title": f"R-{i}", "resource_type": "BOOK", "isbn": f"I-{i:03d}"}
        for i in range(15)
    ]
    csv_text = _csv_with(rows)
    job_id = "job-resume"
    # Seed a checkpoint record so `load(...)` returns something for resume to mark completed
    await svc.import_csv(db_session, csv_text, ACTOR, job_id, NOW)

    state = {"csv_text": csv_text, "imported_by": str(ACTOR), "progress": 5}
    outcome = await svc.resume_import_checkpoint(db_session, job_id, state, NOW)
    assert outcome == "resumed"


async def test_resume_import_checkpoint_bad_progress_defaults_to_zero(
    db_session: AsyncSession,
):
    svc = _make_service()
    rows = [{"title": "R1", "resource_type": "BOOK", "isbn": "I1"}]
    csv_text = _csv_with(rows)
    job_id = "job-bad-progress"
    await svc.import_csv(db_session, csv_text, ACTOR, job_id, NOW)
    state = {
        "csv_text": csv_text,
        "imported_by": str(ACTOR),
        "progress": "NaN",
    }
    outcome = await svc.resume_import_checkpoint(db_session, job_id, state, NOW)
    assert outcome in {"resumed", "completed"}


# ---------------------------------------------------------------------------
# Revisions
# ---------------------------------------------------------------------------

async def test_create_revision_resource_not_found(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(ResourceNotFoundError):
        await svc.create_revision(db_session, uuid.uuid4(), b"x", ACTOR, NOW)


async def test_create_revision_over_limit_deletes_oldest(db_session: AsyncSession):
    svc = _make_service()
    resource, first = await svc.import_file(
        db_session,
        content=b"initial content",
        resource_type=ResourceType.BOOK,
        title="Rev Book",
        isbn="REV-1",
        metadata_dict=None,
        imported_by=ACTOR,
        now=NOW,
    )
    # import_file already created revision #1. Adding MAX_RESOURCE_REVISIONS
    # more revisions drives count up to the limit on the final iteration,
    # which triggers the `delete_oldest_for_resource` branch exactly once.
    for i in range(MAX_RESOURCE_REVISIONS):
        await svc.create_revision(
            db_session, resource.id, f"rev {i}".encode(), ACTOR, NOW
        )

    # Oldest revision (#1) should have been purged.
    revisions = await svc.list_revisions(db_session, resource.id)
    revision_numbers = {r.revision_number for r in revisions}
    assert 1 not in revision_numbers  # oldest purged
    assert len(revisions) == MAX_RESOURCE_REVISIONS


async def test_get_resource_not_found(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(ResourceNotFoundError):
        await svc.get_resource(db_session, uuid.uuid4())


async def test_list_revisions_resource_not_found(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(ResourceNotFoundError):
        await svc.list_revisions(db_session, uuid.uuid4())


# ---------------------------------------------------------------------------
# classify_resource
# ---------------------------------------------------------------------------

async def test_classify_resource_not_found(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(ResourceNotFoundError):
        await svc.classify_resource(
            db_session, uuid.uuid4(), 6, 12, "EVERGREEN", ACTOR, NOW
        )


async def test_classify_resource_persists_metadata(db_session: AsyncSession):
    svc = _make_service()
    resource, _ = await svc.import_file(
        db_session,
        content=b"content",
        resource_type=ResourceType.BOOK,
        title="To Classify",
        isbn="CLASS-1",
        metadata_dict=None,
        imported_by=ACTOR,
        now=NOW,
    )
    await svc.classify_resource(
        db_session,
        resource.id,
        min_age=8,
        max_age=10,
        timeliness_type="EVERGREEN",
        actor_id=ACTOR,
        now=NOW,
    )
    meta = await svc.get_resource_metadata(db_session, resource.id)
    assert meta is not None
    assert meta.age_range_min == 8
    assert meta.age_range_max == 10


# ---------------------------------------------------------------------------
# request_allocation
# ---------------------------------------------------------------------------

async def test_request_allocation_not_found(db_session: AsyncSession):
    svc = _make_service()
    with pytest.raises(ResourceNotFoundError):
        await svc.request_allocation(db_session, uuid.uuid4(), ACTOR, NOW)


async def test_request_allocation_success(db_session: AsyncSession):
    svc = _make_service()
    resource, _ = await svc.import_file(
        db_session,
        content=b"x",
        resource_type=ResourceType.BOOK,
        title="Alloc Req",
        isbn="ALLOC-1",
        metadata_dict=None,
        imported_by=ACTOR,
        now=NOW,
    )
    # Should not raise; writes an audit event
    await svc.request_allocation(db_session, resource.id, ACTOR, NOW)
