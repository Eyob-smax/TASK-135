"""
Resource library service — import, revision management, and review/publish workflow.
"""
from __future__ import annotations

import csv
import hashlib
import io
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from district_console.domain.entities.resource import Resource, ResourceRevision, ReviewTask
from district_console.domain.enums import ResourceStatus, ResourceType, ReviewDecision, validate_resource_transition
from district_console.domain.exceptions import (
    DomainValidationError,
    DuplicateResourceError,
    ResourceNotFoundError,
)
from district_console.domain.policies import MAX_RESOURCE_REVISIONS, revisions_over_limit
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.checkpoint_store import CheckpointStore
from district_console.infrastructure.lock_manager import LockManager
from district_console.infrastructure.repositories import (
    ResourceMetadataRepository,
    ResourceRepository,
    ResourceRevisionRepository,
    ReviewTaskRepository,
)


def _compute_fingerprint(content: bytes) -> str:
    """SHA-256 hex digest of binary content."""
    return hashlib.sha256(content).hexdigest()


def _compute_dedup_key(fingerprint: str, isbn: Optional[str],
                        title: str = "", resource_type: str = "") -> str:
    """
    Combine fingerprint + discriminator into a dedup key.

    Discriminator strategy:
    - ISBN present: use ISBN (globally unique catalogue identifier)
    - ISBN absent: use title + resource_type compound (broader metadata hash),
      preventing same-title resources of different types from colliding.
    """
    if isbn:
        discriminator = isbn
    else:
        # Null-byte separator prevents "Math" + "BOOK" colliding with "MathBOOK" (no type)
        discriminator = f"{title}\x00{resource_type}"
    return hashlib.sha256(f"{fingerprint}{discriminator}".encode()).hexdigest()


class ResourceService:
    def __init__(
        self,
        resource_repo: ResourceRepository,
        revision_repo: ResourceRevisionRepository,
        review_task_repo: ReviewTaskRepository,
        metadata_repo: ResourceMetadataRepository,
        audit_writer: AuditWriter,
        lock_manager: LockManager,
        checkpoint_store: CheckpointStore,
    ) -> None:
        self._resource_repo = resource_repo
        self._revision_repo = revision_repo
        self._review_task_repo = review_task_repo
        self._metadata_repo = metadata_repo
        self._audit_writer = audit_writer
        self._lock_manager = lock_manager
        self._checkpoint_store = checkpoint_store

    async def import_file(
        self,
        session: AsyncSession,
        content: bytes,
        resource_type: ResourceType,
        title: str,
        isbn: Optional[str],
        metadata_dict: Optional[dict],
        imported_by: uuid.UUID,
        now: datetime,
    ) -> tuple[Resource, ResourceRevision]:
        """
        Import a new resource file.  Raises DuplicateResourceError if a
        resource with the same dedup_key already exists.
        """
        fingerprint = _compute_fingerprint(content)
        dedup_key = _compute_dedup_key(fingerprint, isbn, title, resource_type.value)

        existing = await self._resource_repo.get_by_dedup_key(session, dedup_key)
        if existing is not None:
            raise DuplicateResourceError(
                existing_id=str(existing.id), dedup_key=dedup_key
            )

        resource = Resource(
            id=uuid.uuid4(),
            title=title,
            resource_type=resource_type,
            status=ResourceStatus.DRAFT,
            file_fingerprint=fingerprint,
            isbn=isbn,
            dedup_key=dedup_key,
            created_by=imported_by,
            created_at=now,
            updated_at=now,
        )
        await self._resource_repo.save(session, resource)

        revision = ResourceRevision(
            id=uuid.uuid4(),
            resource_id=resource.id,
            revision_number=1,
            file_path="",
            file_hash=fingerprint,
            file_size=len(content),
            imported_by=imported_by,
            created_at=now,
        )
        await self._revision_repo.save(session, revision)

        if metadata_dict:
            from district_console.domain.entities.resource_metadata import ResourceMetadata
            meta = ResourceMetadata(resource_id=resource.id, **metadata_dict)
            await self._metadata_repo.save_metadata(session, resource.id, meta)

        await self._audit_writer.write(
            session,
            entity_type="Resource",
            entity_id=resource.id,
            action="IMPORTED",
            actor_id=imported_by,
            metadata={"title": title, "resource_type": resource_type.value},
        )
        cp = await self._checkpoint_store.save(
            session,
            job_type="import",
            job_id=str(resource.id),
            state={"resource_id": str(resource.id), "step": "completed"},
        )
        await self._checkpoint_store.mark_completed(session, cp.id)

        return resource, revision

    async def import_csv(
        self,
        session: AsyncSession,
        csv_text: str,
        imported_by: uuid.UUID,
        job_id: str,
        now: datetime,
    ) -> dict:
        """
        Bulk-import resources from CSV text.

        Expected columns: title, resource_type, isbn (optional).
        Returns counts of created/duplicates/errors and checkpoint_id.
        """
        cp = await self._checkpoint_store.save(
            session,
            job_type="import",
            job_id=job_id,
            state={
                "job_id": job_id,
                "step": "started",
                "progress": 0,
                "csv_text": csv_text,
                "imported_by": str(imported_by),
            },
        )

        created: list[str] = []
        duplicates: list[str] = []
        errors: list[str] = []

        rows = list(csv.DictReader(io.StringIO(csv_text)))
        for i, row in enumerate(rows):
            try:
                title = row.get("title", "").strip()
                isbn = row.get("isbn", "").strip() or None
                resource_type_str = row.get("resource_type", "BOOK").strip().upper()
                resource_type = ResourceType(resource_type_str)
                # Canonical content for CSV rows: isbn (unique across types) when
                # present; otherwise title + resource_type compound to match the
                # broader metadata-hash strategy used by _compute_dedup_key.
                content = (isbn if isbn else f"{title}\x00{resource_type_str}").encode()
                resource, _ = await self.import_file(
                    session, content, resource_type, title, isbn, None, imported_by, now
                )
                created.append(str(resource.id))
            except DuplicateResourceError as exc:
                duplicates.append(exc.existing_id)
            except Exception as exc:
                errors.append(str(exc))

            if (i + 1) % 10 == 0:
                await self._checkpoint_store.save(
                    session,
                    job_type="import",
                    job_id=job_id,
                    state={
                        "job_id": job_id,
                        "step": "in_progress",
                        "progress": i + 1,
                        "csv_text": csv_text,
                        "imported_by": str(imported_by),
                    },
                )

        await self._checkpoint_store.save(
            session,
            job_type="import",
            job_id=job_id,
            state={
                "job_id": job_id,
                "step": "completed",
                "progress": len(rows),
                "csv_text": csv_text,
                "imported_by": str(imported_by),
            },
        )

        await self._checkpoint_store.mark_completed(session, cp.id)

        return {
            "created": created,
            "duplicates": duplicates,
            "errors": errors,
            "checkpoint_id": str(cp.id),
        }

    async def resume_import_checkpoint(
        self,
        session: AsyncSession,
        job_id: str,
        state: dict,
        now: datetime,
    ) -> str:
        """
        Resume an interrupted CSV import from saved checkpoint state.

        Returns one of: "resumed", "completed", "abandoned".
        """
        csv_text = state.get("csv_text")
        imported_by_raw = state.get("imported_by")
        if not isinstance(csv_text, str) or not csv_text.strip() or imported_by_raw is None:
            return "abandoned"

        try:
            imported_by = uuid.UUID(str(imported_by_raw))
        except (TypeError, ValueError):
            return "abandoned"

        try:
            progress = int(state.get("progress", 0))
        except (TypeError, ValueError):
            progress = 0
        progress = max(progress, 0)

        rows = list(csv.DictReader(io.StringIO(csv_text)))
        if progress >= len(rows):
            cp = await self._checkpoint_store.load(session, "import", job_id)
            if cp is not None:
                await self._checkpoint_store.mark_completed(session, cp.id)
            return "completed"

        for i, row in enumerate(rows[progress:], start=progress):
            try:
                title = row.get("title", "").strip()
                isbn = row.get("isbn", "").strip() or None
                resource_type_str = row.get("resource_type", "BOOK").strip().upper()
                resource_type = ResourceType(resource_type_str)
                content = (isbn if isbn else f"{title}\x00{resource_type_str}").encode()
                await self.import_file(
                    session,
                    content,
                    resource_type,
                    title,
                    isbn,
                    None,
                    imported_by,
                    now,
                )
            except DuplicateResourceError:
                # Duplicate rows are intentionally skipped to keep resume idempotent.
                pass
            except Exception:
                # Individual row errors are ignored to allow batch completion.
                pass

            if (i + 1) % 10 == 0:
                await self._checkpoint_store.save(
                    session,
                    job_type="import",
                    job_id=job_id,
                    state={
                        "job_id": job_id,
                        "step": "in_progress",
                        "progress": i + 1,
                        "csv_text": csv_text,
                        "imported_by": str(imported_by),
                    },
                )

        cp = await self._checkpoint_store.load(session, "import", job_id)
        if cp is not None:
            await self._checkpoint_store.save(
                session,
                job_type="import",
                job_id=job_id,
                state={
                    "job_id": job_id,
                    "step": "completed",
                    "progress": len(rows),
                    "csv_text": csv_text,
                    "imported_by": str(imported_by),
                },
            )
            await self._checkpoint_store.mark_completed(session, cp.id)
        return "resumed"

    async def create_revision(
        self,
        session: AsyncSession,
        resource_id: uuid.UUID,
        content: bytes,
        imported_by: uuid.UUID,
        now: datetime,
    ) -> ResourceRevision:
        """Add a new revision to an existing resource (max 10)."""
        resource = await self._resource_repo.get_by_id(session, resource_id)
        if resource is None:
            raise ResourceNotFoundError(str(resource_id))

        count = await self._revision_repo.count_for_resource(session, resource_id)
        if revisions_over_limit(count):
            await self._revision_repo.delete_oldest_for_resource(session, resource_id)

        fingerprint = _compute_fingerprint(content)
        revision = ResourceRevision(
            id=uuid.uuid4(),
            resource_id=resource_id,
            revision_number=count + 1,
            file_path="",
            file_hash=fingerprint,
            file_size=len(content),
            imported_by=imported_by,
            created_at=now,
        )
        await self._revision_repo.save(session, revision)

        resource.updated_at = now
        await self._resource_repo.save(session, resource)

        await self._audit_writer.write(
            session,
            entity_type="Resource",
            entity_id=resource_id,
            action="REVISION_CREATED",
            actor_id=imported_by,
            metadata={"revision_number": count + 1},
        )
        return revision

    async def submit_for_review(
        self,
        session: AsyncSession,
        resource_id: uuid.UUID,
        reviewer_id: uuid.UUID,
        actor_id: uuid.UUID,
        roles: list,
        now: datetime,
    ) -> Resource:
        """Transition a DRAFT resource to IN_REVIEW."""
        from district_console.application.rbac_service import RbacService
        RbacService().check_permission(roles, "resources.submit_review")

        resource = await self._resource_repo.get_by_id(session, resource_id)
        if resource is None:
            raise ResourceNotFoundError(str(resource_id))

        validate_resource_transition(resource.status, ResourceStatus.IN_REVIEW)

        await self._lock_manager.acquire(session, "resource", resource_id, actor_id)
        try:
            resource.status = ResourceStatus.IN_REVIEW
            resource.updated_at = now
            await self._resource_repo.save(session, resource)

            task = ReviewTask(
                id=uuid.uuid4(),
                resource_id=resource_id,
                assigned_to=reviewer_id,
                decision=None,
                notes="",
                created_at=now,
                completed_at=None,
            )
            await self._review_task_repo.save(session, task)

            await self._audit_writer.write(
                session,
                entity_type="Resource",
                entity_id=resource_id,
                action="SUBMITTED_FOR_REVIEW",
                actor_id=actor_id,
                metadata={"reviewer_id": str(reviewer_id)},
            )
        finally:
            await self._lock_manager.release(session, "resource", resource_id, actor_id)

        return resource

    async def publish_resource(
        self,
        session: AsyncSession,
        resource_id: uuid.UUID,
        reviewer_notes: str,
        actor_id: uuid.UUID,
        roles: list,
        now: datetime,
    ) -> Resource:
        """Transition an IN_REVIEW resource to PUBLISHED."""
        from district_console.application.rbac_service import RbacService
        RbacService().check_permission(roles, "resources.publish")

        resource = await self._resource_repo.get_by_id(session, resource_id)
        if resource is None:
            raise ResourceNotFoundError(str(resource_id))

        validate_resource_transition(resource.status, ResourceStatus.PUBLISHED)

        if not reviewer_notes or not reviewer_notes.strip():
            raise DomainValidationError(
                field="reviewer_notes",
                value=reviewer_notes,
                constraint="Reviewer notes are required when publishing a resource.",
            )

        await self._lock_manager.acquire(session, "resource", resource_id, actor_id)
        try:
            task = await self._review_task_repo.get_open_for_resource(session, resource_id)
            if task is not None:
                task.complete(ReviewDecision.APPROVED, reviewer_notes, now, actor_id)
                await self._review_task_repo.save(session, task)

            resource.status = ResourceStatus.PUBLISHED
            resource.updated_at = now
            await self._resource_repo.save(session, resource)

            await self._audit_writer.write(
                session,
                entity_type="Resource",
                entity_id=resource_id,
                action="PUBLISHED",
                actor_id=actor_id,
                metadata={"notes_length": len(reviewer_notes)},
            )
        finally:
            await self._lock_manager.release(session, "resource", resource_id, actor_id)

        return resource

    async def unpublish_resource(
        self,
        session: AsyncSession,
        resource_id: uuid.UUID,
        reviewer_notes: str,
        actor_id: uuid.UUID,
        roles: list,
        now: datetime,
    ) -> Resource:
        """Transition a PUBLISHED resource to UNPUBLISHED."""
        from district_console.application.rbac_service import RbacService
        RbacService().check_permission(roles, "resources.publish")

        resource = await self._resource_repo.get_by_id(session, resource_id)
        if resource is None:
            raise ResourceNotFoundError(str(resource_id))

        validate_resource_transition(resource.status, ResourceStatus.UNPUBLISHED)

        if not reviewer_notes or not reviewer_notes.strip():
            raise DomainValidationError(
                field="reviewer_notes",
                value=reviewer_notes,
                constraint="Reviewer notes are required when unpublishing a resource.",
            )

        await self._lock_manager.acquire(session, "resource", resource_id, actor_id)
        try:
            resource.status = ResourceStatus.UNPUBLISHED
            resource.updated_at = now
            await self._resource_repo.save(session, resource)

            await self._audit_writer.write(
                session,
                entity_type="Resource",
                entity_id=resource_id,
                action="UNPUBLISHED",
                actor_id=actor_id,
                metadata={"notes_length": len(reviewer_notes)},
            )
        finally:
            await self._lock_manager.release(session, "resource", resource_id, actor_id)

        return resource

    async def get_resource(
        self, session: AsyncSession, resource_id: uuid.UUID
    ) -> Resource:
        resource = await self._resource_repo.get_by_id(session, resource_id)
        if resource is None:
            raise ResourceNotFoundError(str(resource_id))
        return resource

    async def list_resources(
        self,
        session: AsyncSession,
        filters: dict,
        offset: int,
        limit: int,
    ) -> tuple[list[Resource], int]:
        return await self._resource_repo.list(session, filters, offset, limit)

    async def get_resource_metadata(self, session: AsyncSession, resource_id: uuid.UUID):
        """Return ResourceMetadata for the given resource, or None if not classified yet."""
        return await self._metadata_repo.get_by_resource_id(session, resource_id)

    async def list_revisions(
        self, session: AsyncSession, resource_id: uuid.UUID
    ) -> list[ResourceRevision]:
        resource = await self._resource_repo.get_by_id(session, resource_id)
        if resource is None:
            raise ResourceNotFoundError(str(resource_id))
        return await self._revision_repo.list_for_resource(session, resource_id)

    async def classify_resource(
        self,
        session: AsyncSession,
        resource_id: uuid.UUID,
        min_age: int,
        max_age: int,
        timeliness_type: str,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> None:
        """Persist classification metadata for a published resource."""
        from district_console.domain.entities.resource_metadata import ResourceMetadata
        from district_console.domain.enums import TimelinesType
        resource = await self._resource_repo.get_by_id(session, resource_id)
        if resource is None:
            raise ResourceNotFoundError(str(resource_id))
        meta = ResourceMetadata(
            resource_id=resource_id,
            age_range_min=min_age,
            age_range_max=max_age,
            timeliness=TimelinesType(timeliness_type),
        )
        meta.validate()
        await self._metadata_repo.save_metadata(session, resource_id, meta)
        await self._audit_writer.write(
            session,
            entity_type="Resource",
            entity_id=resource_id,
            action="RESOURCE_CLASSIFIED",
            actor_id=actor_id,
            metadata={"min_age": min_age, "max_age": max_age, "timeliness": timeliness_type},
        )

    async def request_allocation(
        self,
        session: AsyncSession,
        resource_id: uuid.UUID,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> None:
        """Record a teacher's allocation request via audit trail."""
        resource = await self._resource_repo.get_by_id(session, resource_id)
        if resource is None:
            raise ResourceNotFoundError(str(resource_id))
        await self._audit_writer.write(
            session,
            entity_type="Resource",
            entity_id=resource_id,
            action="ALLOCATION_REQUESTED",
            actor_id=actor_id,
            metadata={"resource_id": str(resource_id)},
        )
