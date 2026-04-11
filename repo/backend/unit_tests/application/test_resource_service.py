"""
Unit tests for ResourceService — import, revision, and review/publish workflows.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.auth_service import AuthService
from district_console.application.resource_service import ResourceService, _compute_dedup_key, _compute_fingerprint
from district_console.domain.entities.role import Permission, Role
from district_console.domain.enums import CheckpointStatus, ResourceStatus, ResourceType
from district_console.domain.enums import RoleType
from district_console.domain.exceptions import (
    DuplicateResourceError,
    InvalidStateTransitionError,
    ResourceNotFoundError,
)
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.checkpoint_store import CheckpointStore
from district_console.infrastructure.lock_manager import LockManager
from district_console.infrastructure.orm import ResourceORM, ResourceRevisionORM, UserORM
from district_console.infrastructure.repositories import (
    AuditRepository,
    CheckpointRepository,
    LockRepository,
    ResourceMetadataRepository,
    ResourceRepository,
    ResourceRevisionRepository,
    RoleRepository,
    ReviewTaskRepository,
    UserRepository,
)


def _make_service(lock_repo=None, audit_repo=None, checkpoint_repo=None):
    audit_repo = audit_repo or AuditRepository()
    lock_repo = lock_repo or LockRepository()
    checkpoint_repo = checkpoint_repo or CheckpointRepository()
    return ResourceService(
        ResourceRepository(),
        ResourceRevisionRepository(),
        ReviewTaskRepository(),
        ResourceMetadataRepository(),
        AuditWriter(audit_repo),
        LockManager(lock_repo),
        CheckpointStore(checkpoint_repo),
    )


NOW = datetime(2024, 1, 1, 12, 0, 0)
ACTOR = uuid.uuid4()


def _role(role_type: RoleType, permissions: list[str]) -> Role:
    perms = frozenset(
        Permission(
            id=uuid.uuid4(),
            name=name,
            resource_name=name.split(".")[0],
            action=name.split(".")[1],
        )
        for name in permissions
    )
    return Role(
        id=uuid.uuid4(),
        role_type=role_type,
        display_name=role_type.value,
        permissions=perms,
    )


@pytest.fixture(autouse=True)
async def _seed_actor_user(db_session: AsyncSession) -> None:
    """Seed a user matching ACTOR so FK constraints pass for resource tests."""
    auth = AuthService(UserRepository(), RoleRepository())
    now = datetime.utcnow().isoformat()
    db_session.add(
        UserORM(
            id=str(ACTOR),
            username="resource_actor",
            password_hash=auth.hash_password("SecurePassword1!"),
            is_active=True,
            failed_attempts=0,
            locked_until=None,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.flush()


async def test_import_file_creates_resource_and_revision(db_session: AsyncSession):
    svc = _make_service()
    content = b"Hello resource content"
    resource, revision = await svc.import_file(
        db_session, content, ResourceType.BOOK, "Test Book", None, None, ACTOR, NOW
    )
    assert resource.status == ResourceStatus.DRAFT
    assert resource.title == "Test Book"
    assert resource.file_fingerprint == _compute_fingerprint(content)
    assert revision.revision_number == 1
    assert revision.file_size == len(content)
    assert revision.resource_id == resource.id


async def test_import_file_duplicate_dedup_key_raises(db_session: AsyncSession):
    svc = _make_service()
    content = b"duplicate content"
    await svc.import_file(db_session, content, ResourceType.BOOK, "Book One", None, None, ACTOR, NOW)
    with pytest.raises(DuplicateResourceError):
        await svc.import_file(db_session, content, ResourceType.BOOK, "Book One", None, None, ACTOR, NOW)


async def test_import_csv_processes_multiple_rows(db_session: AsyncSession):
    svc = _make_service()
    csv_text = "title,resource_type,isbn\nAlpha Book,BOOK,978-1\nBeta Article,ARTICLE,\n"
    result = await svc.import_csv(db_session, csv_text, ACTOR, str(uuid.uuid4()), NOW)
    assert len(result["created"]) == 2
    assert len(result["duplicates"]) == 0
    assert len(result["errors"]) == 0


async def test_import_csv_skips_duplicate_rows(db_session: AsyncSession):
    svc = _make_service()
    csv_text = "title,resource_type,isbn\nSame Book,BOOK,978-X\nSame Book,BOOK,978-X\n"
    result = await svc.import_csv(db_session, csv_text, ACTOR, str(uuid.uuid4()), NOW)
    assert len(result["created"]) == 1
    assert len(result["duplicates"]) == 1


async def test_resume_import_checkpoint_replays_rows_and_completes_checkpoint(
    db_session: AsyncSession,
):
    svc = _make_service()
    job_id = str(uuid.uuid4())
    csv_text = "title,resource_type,isbn\nAlpha Book,BOOK,978-11\nBeta Book,BOOK,978-22\n"

    await svc._checkpoint_store.save(
        db_session,
        job_type="import",
        job_id=job_id,
        state={
            "job_id": job_id,
            "step": "in_progress",
            "progress": 0,
            "csv_text": csv_text,
            "imported_by": str(ACTOR),
        },
    )

    outcome = await svc.resume_import_checkpoint(
        db_session,
        job_id=job_id,
        state={
            "job_id": job_id,
            "step": "in_progress",
            "progress": 0,
            "csv_text": csv_text,
            "imported_by": str(ACTOR),
        },
        now=NOW,
    )

    assert outcome in {"resumed", "completed"}
    cp = await svc._checkpoint_store.load(db_session, "import", job_id)
    assert cp is not None
    assert cp.status == CheckpointStatus.COMPLETED

    items, total = await svc.list_resources(db_session, {}, offset=0, limit=10)
    assert total == 2
    assert len(items) == 2


async def test_resume_import_checkpoint_without_resume_payload_returns_abandoned(
    db_session: AsyncSession,
):
    svc = _make_service()
    outcome = await svc.resume_import_checkpoint(
        db_session,
        job_id=str(uuid.uuid4()),
        state={"progress": 3},
        now=NOW,
    )
    assert outcome == "abandoned"


async def test_create_revision_increments_number(db_session: AsyncSession, seeded_user_orm):
    svc = _make_service()
    content = b"original"
    resource, rev1 = await svc.import_file(
        db_session, content, ResourceType.BOOK, "Revisable Book", None, None, ACTOR, NOW
    )
    rev2 = await svc.create_revision(db_session, resource.id, b"updated content", ACTOR, NOW)
    assert rev2.revision_number == 2
    assert rev2.resource_id == resource.id


async def test_create_revision_at_limit_prunes_oldest_and_succeeds(db_session: AsyncSession, seeded_user_orm):
    """When at the 10-revision cap, adding a new revision prunes the oldest (rolling window)."""
    from district_console.infrastructure.repositories import ResourceRevisionRepository
    svc = _make_service()
    content = b"initial"
    resource, first_rev = await svc.import_file(
        db_session, content, ResourceType.BOOK, "Limited Book", None, None, ACTOR, NOW
    )
    first_rev_id = first_rev.id
    # Seed revisions 2-10 (import already created rev 1; add 9 more)
    for i in range(9):
        await svc.create_revision(db_session, resource.id, f"content {i}".encode(), ACTOR, NOW)
    # Count is now 10; adding one more should prune oldest and succeed
    new_rev = await svc.create_revision(db_session, resource.id, b"eleventh content", ACTOR, NOW)
    assert new_rev is not None
    assert new_rev.revision_number == 11
    # Total revision count must remain 10
    total = await ResourceRevisionRepository.count_for_resource(db_session, resource.id)
    assert total == 10
    # The original first revision must have been deleted
    from district_console.infrastructure.orm import ResourceRevisionORM
    from sqlalchemy import select
    result = await db_session.execute(
        select(ResourceRevisionORM).where(ResourceRevisionORM.id == str(first_rev_id))
    )
    assert result.scalar_one_or_none() is None, "Oldest revision was not pruned"


async def test_submit_for_review_transitions_draft_to_in_review(db_session: AsyncSession, seeded_roles):
    svc = _make_service()
    content = b"book for review"
    resource, _ = await svc.import_file(
        db_session, content, ResourceType.BOOK, "For Review", None, None, ACTOR, NOW
    )
    reviewer_id = ACTOR
    roles = [_role(RoleType.LIBRARIAN, ["resources.submit_review"])]
    updated = await svc.submit_for_review(db_session, resource.id, reviewer_id, ACTOR, roles, NOW)
    assert updated.status == ResourceStatus.IN_REVIEW


async def test_submit_for_review_non_draft_raises_invalid_transition(db_session: AsyncSession, seeded_roles):
    svc = _make_service()
    content = b"already reviewed"
    resource, _ = await svc.import_file(
        db_session, content, ResourceType.BOOK, "In Review Book", None, None, ACTOR, NOW
    )
    reviewer_id = ACTOR
    roles = [_role(RoleType.LIBRARIAN, ["resources.submit_review"])]
    await svc.submit_for_review(db_session, resource.id, reviewer_id, ACTOR, roles, NOW)
    # Submitting again from IN_REVIEW → IN_REVIEW is invalid
    with pytest.raises(InvalidStateTransitionError):
        await svc.submit_for_review(db_session, resource.id, reviewer_id, ACTOR, roles, NOW)


async def test_publish_requires_non_empty_reviewer_notes(db_session: AsyncSession):
    svc = _make_service()
    content = b"to publish"
    resource, _ = await svc.import_file(
        db_session, content, ResourceType.BOOK, "Publishable", None, None, ACTOR, NOW
    )
    submit_roles = [_role(RoleType.LIBRARIAN, ["resources.submit_review"])]
    pub_roles = [_role(RoleType.REVIEWER, ["resources.publish"])]
    reviewer_id = ACTOR
    await svc.submit_for_review(db_session, resource.id, reviewer_id, ACTOR, submit_roles, NOW)
    from district_console.domain.exceptions import DomainValidationError
    with pytest.raises(DomainValidationError):
        await svc.publish_resource(db_session, resource.id, "  ", ACTOR, pub_roles, NOW)


async def test_publish_transitions_in_review_to_published(db_session: AsyncSession):
    svc = _make_service()
    content = b"to publish now"
    resource, _ = await svc.import_file(
        db_session, content, ResourceType.BOOK, "Will Publish", None, None, ACTOR, NOW
    )
    submit_roles = [_role(RoleType.LIBRARIAN, ["resources.submit_review"])]
    pub_roles = [_role(RoleType.REVIEWER, ["resources.publish"])]
    reviewer_id = ACTOR
    await svc.submit_for_review(db_session, resource.id, reviewer_id, ACTOR, submit_roles, NOW)
    published = await svc.publish_resource(db_session, resource.id, "Looks great!", ACTOR, pub_roles, NOW)
    assert published.status == ResourceStatus.PUBLISHED


async def test_unpublish_transitions_published_to_unpublished(db_session: AsyncSession):
    svc = _make_service()
    content = b"unpublish this"
    resource, _ = await svc.import_file(
        db_session, content, ResourceType.BOOK, "Will Unpublish", None, None, ACTOR, NOW
    )
    submit_roles = [_role(RoleType.LIBRARIAN, ["resources.submit_review"])]
    pub_roles = [_role(RoleType.REVIEWER, ["resources.publish"])]
    reviewer_id = ACTOR
    await svc.submit_for_review(db_session, resource.id, reviewer_id, ACTOR, submit_roles, NOW)
    await svc.publish_resource(db_session, resource.id, "Approved!", ACTOR, pub_roles, NOW)
    unpublished = await svc.unpublish_resource(db_session, resource.id, "Taking down temporarily", ACTOR, pub_roles, NOW)
    assert unpublished.status == ResourceStatus.UNPUBLISHED


async def test_list_resources_returns_paginated_results(db_session: AsyncSession):
    svc = _make_service()
    for i in range(3):
        await svc.import_file(
            db_session, f"content {i}".encode(), ResourceType.ARTICLE,
            f"Article {i}", None, None, ACTOR, NOW
        )
    items, total = await svc.list_resources(db_session, {}, offset=0, limit=2)
    assert total == 3
    assert len(items) == 2
