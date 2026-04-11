"""
Repository classes for District Console infrastructure layer.

Each repository wraps database access for a specific set of ORM models and
converts between ORM objects and domain dataclasses. SQLAlchemy is isolated
here — nothing in the domain or application layers imports it.

Append-only invariants:
  - AuditRepository.append() inserts only. No UPDATE or DELETE is ever
    issued against the audit_events table.
  - LedgerRepository.append() inserts only. The sole permitted UPDATE on
    ledger_entries is LedgerRepository.mark_reversed(), which sets
    is_reversed=True only — no other column may be changed.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.domain.entities.checkpoint import CheckpointRecord
from district_console.domain.entities.count import CountApproval, CountLine, CountSession
from district_console.domain.entities.inventory import (
    InventoryItem,
    Location,
    RecordLock,
    StockBalance,
    Warehouse,
)
from district_console.domain.entities.ledger import LedgerEntry
from district_console.domain.entities.relocation import Relocation
from district_console.domain.entities.resource import AuditEvent, Resource, ResourceRevision, ReviewTask
from district_console.domain.entities.resource_metadata import ResourceMetadata
from district_console.domain.entities.role import Permission, Role
from district_console.domain.entities.user import ScopeAssignment, User
from district_console.domain.enums import (
    CheckpointStatus,
    CountMode,
    CountSessionStatus,
    DeviceSource,
    LedgerEntryType,
    ResourceStatus,
    ResourceType,
    ReviewDecision,
    RoleType,
    ScopeType,
    StockStatus,
)
from district_console.infrastructure.orm import (
    AuditEventORM,
    CheckpointRecordORM,
    CountApprovalORM,
    CountLineORM,
    CountSessionORM,
    HmacKeyORM,
    InventoryItemORM,
    LedgerEntryORM,
    LocationORM,
    PermissionORM,
    RateLimitStateORM,
    RecordLockORM,
    RelocationORM,
    ResourceCategoryORM,
    ResourceKeywordORM,
    ResourceMetadataORM,
    ResourceORM,
    ResourceRevisionORM,
    ReviewTaskORM,
    RoleORM,
    RolePermissionORM,
    ScopeAssignmentORM,
    StockBalanceORM,
    UserORM,
    UserRoleORM,
    WarehouseORM,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse ISO-8601 datetime string; return None if value is None."""
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _fmt_dt(value: Optional[datetime]) -> Optional[str]:
    """Serialise datetime to ISO-8601 string; return None if value is None."""
    if value is None:
        return None
    return value.isoformat()


# ---------------------------------------------------------------------------
# UserRepository
# ---------------------------------------------------------------------------

class UserRepository:
    """CRUD operations for user accounts."""

    @staticmethod
    async def get_by_username(
        session: AsyncSession, username: str
    ) -> Optional[User]:
        result = await session.execute(
            select(UserORM).where(UserORM.username == username)
        )
        orm = result.scalar_one_or_none()
        return _user_to_domain(orm) if orm else None

    @staticmethod
    async def get_by_id(
        session: AsyncSession, user_id: uuid.UUID
    ) -> Optional[User]:
        result = await session.execute(
            select(UserORM).where(UserORM.id == str(user_id))
        )
        orm = result.scalar_one_or_none()
        return _user_to_domain(orm) if orm else None

    @staticmethod
    async def save(session: AsyncSession, user: User) -> User:
        """Insert or update a user record."""
        result = await session.execute(
            select(UserORM).where(UserORM.id == str(user.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = UserORM(
                id=str(user.id),
                username=user.username,
                password_hash=user.password_hash,
                is_active=user.is_active,
                failed_attempts=user.failed_attempts,
                locked_until=_fmt_dt(user.locked_until),
                created_at=_fmt_dt(user.created_at) or datetime.utcnow().isoformat(),
                updated_at=_fmt_dt(user.updated_at) or datetime.utcnow().isoformat(),
            )
            session.add(orm)
        else:
            orm.username = user.username
            orm.password_hash = user.password_hash
            orm.is_active = user.is_active
            orm.failed_attempts = user.failed_attempts
            orm.locked_until = _fmt_dt(user.locked_until)
            orm.updated_at = _fmt_dt(user.updated_at) or datetime.utcnow().isoformat()
        await session.flush()
        return user


def _user_to_domain(orm: UserORM) -> User:
    return User(
        id=uuid.UUID(orm.id),
        username=orm.username,
        password_hash=orm.password_hash,
        is_active=orm.is_active,
        failed_attempts=orm.failed_attempts,
        locked_until=_parse_dt(orm.locked_until),
        created_at=datetime.fromisoformat(orm.created_at),
        updated_at=datetime.fromisoformat(orm.updated_at),
    )


# ---------------------------------------------------------------------------
# RoleRepository
# ---------------------------------------------------------------------------

class RoleRepository:
    """Loads roles and their associated permissions for RBAC checks."""

    @staticmethod
    async def get_roles_for_user(
        session: AsyncSession, user_id: uuid.UUID
    ) -> list[Role]:
        """Return all roles assigned to a user, with permissions loaded."""
        ur_result = await session.execute(
            select(UserRoleORM).where(UserRoleORM.user_id == str(user_id))
        )
        user_roles = ur_result.scalars().all()
        if not user_roles:
            return []

        role_ids = [ur.role_id for ur in user_roles]
        roles_result = await session.execute(
            select(RoleORM).where(RoleORM.id.in_(role_ids))
        )
        role_orms = roles_result.scalars().all()

        roles: list[Role] = []
        for role_orm in role_orms:
            permissions = await _load_permissions_for_role(session, role_orm.id)
            roles.append(Role(
                id=uuid.UUID(role_orm.id),
                role_type=RoleType(role_orm.role_type),
                display_name=role_orm.display_name,
                permissions=frozenset(permissions),
            ))
        return roles


async def _load_permissions_for_role(
    session: AsyncSession, role_id: str
) -> list[Permission]:
    """Load all Permission domain objects for a given role_id."""
    rp_result = await session.execute(
        select(RolePermissionORM).where(RolePermissionORM.role_id == role_id)
    )
    rp_rows = rp_result.scalars().all()
    if not rp_rows:
        return []

    perm_ids = [rp.permission_id for rp in rp_rows]
    perm_result = await session.execute(
        select(PermissionORM).where(PermissionORM.id.in_(perm_ids))
    )
    return [
        Permission(
            id=uuid.UUID(p.id),
            name=p.name,
            resource_name=p.resource_name,
            action=p.action,
        )
        for p in perm_result.scalars().all()
    ]


# ---------------------------------------------------------------------------
# ScopeRepository
# ---------------------------------------------------------------------------

class ScopeRepository:
    """Loads scope assignments for a user."""

    @staticmethod
    async def get_user_scopes(
        session: AsyncSession, user_id: uuid.UUID
    ) -> list[ScopeAssignment]:
        result = await session.execute(
            select(ScopeAssignmentORM).where(
                ScopeAssignmentORM.user_id == str(user_id)
            )
        )
        return [
            ScopeAssignment(
                id=uuid.UUID(orm.id),
                user_id=uuid.UUID(orm.user_id),
                scope_type=ScopeType(orm.scope_type),
                scope_ref_id=uuid.UUID(orm.scope_ref_id),
                granted_by=uuid.UUID(orm.granted_by),
                granted_at=datetime.fromisoformat(orm.granted_at),
            )
            for orm in result.scalars().all()
        ]


# ---------------------------------------------------------------------------
# AuditRepository
# ---------------------------------------------------------------------------

class AuditRepository:
    """
    Append-only writer for audit_events.

    APPEND-ONLY: never call session.execute(update(...)) or session.delete()
    on audit_events. This method is the sole write path.
    """

    @staticmethod
    async def append(session: AsyncSession, event: AuditEvent) -> None:
        """Insert a new audit event row. No UPDATE or DELETE permitted."""
        orm = AuditEventORM(
            id=str(event.id),
            entity_type=event.entity_type,
            entity_id=str(event.entity_id),
            action=event.action,
            actor_id=str(event.actor_id),
            timestamp=event.timestamp.isoformat(),
            metadata_json=json.dumps(event.metadata),
        )
        session.add(orm)
        await session.flush()


# ---------------------------------------------------------------------------
# HmacKeyRepository
# ---------------------------------------------------------------------------

class HmacKeyRepository:
    """Loads HMAC keys for integration client signature verification."""

    @staticmethod
    async def get_active_key(
        session: AsyncSession, client_id: str
    ) -> Optional[HmacKeyORM]:
        result = await session.execute(
            select(HmacKeyORM).where(
                HmacKeyORM.client_id == client_id,
                HmacKeyORM.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_next_key(
        session: AsyncSession, client_id: str
    ) -> Optional[HmacKeyORM]:
        """Return the next/rotation key if one exists."""
        result = await session.execute(
            select(HmacKeyORM).where(
                HmacKeyORM.client_id == client_id,
                HmacKeyORM.is_next == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# RateLimitRepository
# ---------------------------------------------------------------------------

class RateLimitRepository:
    """Read/write rate limit state for integration clients."""

    @staticmethod
    async def get_state(
        session: AsyncSession, client_id: str
    ) -> Optional[RateLimitStateORM]:
        result = await session.execute(
            select(RateLimitStateORM).where(
                RateLimitStateORM.client_id == client_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert_state(
        session: AsyncSession,
        client_id: str,
        window_start: datetime,
        request_count: int,
        existing_orm: Optional[RateLimitStateORM] = None,
    ) -> RateLimitStateORM:
        if existing_orm is not None:
            existing_orm.window_start = window_start.isoformat()
            existing_orm.request_count = request_count
            await session.flush()
            return existing_orm

        new_orm = RateLimitStateORM(
            id=str(uuid.uuid4()),
            client_id=client_id,
            window_start=window_start.isoformat(),
            request_count=request_count,
        )
        session.add(new_orm)
        await session.flush()
        return new_orm


# ---------------------------------------------------------------------------
# LockRepository
# ---------------------------------------------------------------------------

class LockRepository:
    """DB-backed record lock storage."""

    @staticmethod
    async def get_active_lock(
        session: AsyncSession, entity_type: str, entity_id: str
    ) -> Optional[RecordLockORM]:
        result = await session.execute(
            select(RecordLockORM).where(
                RecordLockORM.entity_type == entity_type,
                RecordLockORM.entity_id == entity_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def insert(session: AsyncSession, lock_orm: RecordLockORM) -> None:
        session.add(lock_orm)
        await session.flush()

    @staticmethod
    async def delete_by_id(session: AsyncSession, lock_id: str) -> None:
        await session.execute(
            delete(RecordLockORM).where(RecordLockORM.id == lock_id)
        )
        await session.flush()

    @staticmethod
    async def delete_expired(session: AsyncSession, now: datetime) -> int:
        """Delete all expired locks. Returns the number deleted."""
        result = await session.execute(
            select(RecordLockORM).where(RecordLockORM.expires_at < now.isoformat())
        )
        expired = result.scalars().all()
        count = len(expired)
        for lock_orm in expired:
            await session.delete(lock_orm)
        if count:
            await session.flush()
        return count


def _lock_to_domain(orm: RecordLockORM) -> RecordLock:
    return RecordLock(
        id=uuid.UUID(orm.id),
        entity_type=orm.entity_type,
        entity_id=orm.entity_id,
        locked_by=uuid.UUID(orm.locked_by),
        locked_at=datetime.fromisoformat(orm.locked_at),
        expires_at=datetime.fromisoformat(orm.expires_at),
        nonce=orm.nonce,
    )


# ---------------------------------------------------------------------------
# CheckpointRepository
# ---------------------------------------------------------------------------

class CheckpointRepository:
    """Persistent storage for crash-safe job checkpoints."""

    @staticmethod
    async def upsert(
        session: AsyncSession,
        job_type: str,
        job_id: str,
        state_json: str,
        now: datetime,
    ) -> CheckpointRecordORM:
        result = await session.execute(
            select(CheckpointRecordORM).where(
                CheckpointRecordORM.job_type == job_type,
                CheckpointRecordORM.job_id == job_id,
            )
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = CheckpointRecordORM(
                id=str(uuid.uuid4()),
                job_type=job_type,
                job_id=job_id,
                state_json=state_json,
                status="ACTIVE",
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            )
            session.add(orm)
        else:
            orm.state_json = state_json
            orm.status = "ACTIVE"
            orm.updated_at = now.isoformat()
        await session.flush()
        return orm

    @staticmethod
    async def get(
        session: AsyncSession, job_type: str, job_id: str
    ) -> Optional[CheckpointRecordORM]:
        result = await session.execute(
            select(CheckpointRecordORM).where(
                CheckpointRecordORM.job_type == job_type,
                CheckpointRecordORM.job_id == job_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_active(
        session: AsyncSession,
    ) -> list[CheckpointRecordORM]:
        result = await session.execute(
            select(CheckpointRecordORM).where(
                CheckpointRecordORM.status == "ACTIVE"
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def update_status(
        session: AsyncSession,
        id: str,
        status: str,
        now: datetime,
        extra_state_fields: Optional[dict] = None,
    ) -> None:
        result = await session.execute(
            select(CheckpointRecordORM).where(CheckpointRecordORM.id == id)
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            return
        orm.status = status
        orm.updated_at = now.isoformat()
        if extra_state_fields:
            existing = json.loads(orm.state_json)
            existing.update(extra_state_fields)
            orm.state_json = json.dumps(existing)
        await session.flush()


def _checkpoint_to_domain(orm: CheckpointRecordORM) -> CheckpointRecord:
    return CheckpointRecord(
        id=uuid.UUID(orm.id),
        job_type=orm.job_type,
        job_id=orm.job_id,
        state_json=orm.state_json,
        status=CheckpointStatus(orm.status),
        created_at=datetime.fromisoformat(orm.created_at),
        updated_at=datetime.fromisoformat(orm.updated_at),
    )


# ---------------------------------------------------------------------------
# ResourceRepository
# ---------------------------------------------------------------------------

class ResourceRepository:
    """CRUD and dedup operations for resource records."""

    @staticmethod
    async def get_by_id(
        session: AsyncSession, resource_id: uuid.UUID
    ) -> Optional[Resource]:
        result = await session.execute(
            select(ResourceORM).where(ResourceORM.id == str(resource_id))
        )
        orm = result.scalar_one_or_none()
        return _resource_to_domain(orm) if orm else None

    @staticmethod
    async def get_by_dedup_key(
        session: AsyncSession, dedup_key: str
    ) -> Optional[Resource]:
        result = await session.execute(
            select(ResourceORM).where(ResourceORM.dedup_key == dedup_key)
        )
        orm = result.scalar_one_or_none()
        return _resource_to_domain(orm) if orm else None

    @staticmethod
    async def save(session: AsyncSession, resource: Resource) -> Resource:
        result = await session.execute(
            select(ResourceORM).where(ResourceORM.id == str(resource.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = ResourceORM(
                id=str(resource.id),
                title=resource.title,
                resource_type=resource.resource_type.value,
                status=resource.status.value,
                file_fingerprint=resource.file_fingerprint,
                isbn=resource.isbn,
                dedup_key=resource.dedup_key,
                created_by=str(resource.created_by),
                created_at=resource.created_at.isoformat(),
                updated_at=resource.updated_at.isoformat(),
                owner_scope_type=resource.owner_scope_type,
                owner_scope_ref_id=resource.owner_scope_ref_id,
            )
            session.add(orm)
        else:
            orm.title = resource.title
            orm.resource_type = resource.resource_type.value
            orm.status = resource.status.value
            orm.file_fingerprint = resource.file_fingerprint
            orm.isbn = resource.isbn
            orm.dedup_key = resource.dedup_key
            orm.updated_at = resource.updated_at.isoformat()
            orm.owner_scope_type = resource.owner_scope_type
            orm.owner_scope_ref_id = resource.owner_scope_ref_id
        await session.flush()
        return resource

    @staticmethod
    async def list(
        session: AsyncSession,
        filters: dict,
        offset: int,
        limit: int,
    ) -> tuple[list[Resource], int]:
        stmt = select(ResourceORM)
        if filters.get("status"):
            stmt = stmt.where(ResourceORM.status == filters["status"])
        if filters.get("resource_type"):
            stmt = stmt.where(ResourceORM.resource_type == filters["resource_type"])
        if filters.get("created_by"):
            stmt = stmt.where(ResourceORM.created_by == filters["created_by"])
        if filters.get("keyword"):
            kw = filters["keyword"]
            stmt = stmt.where(ResourceORM.title.ilike(f"%{kw}%"))
        if "allowed_scope_pairs" in filters:
            pairs = filters["allowed_scope_pairs"]
            scope_conditions = [
                and_(
                    ResourceORM.owner_scope_type == st,
                    ResourceORM.owner_scope_ref_id == ref_id,
                )
                for st, ref_id in pairs
            ]
            stmt = stmt.where(
                or_(
                    ResourceORM.owner_scope_ref_id.is_(None),
                    *scope_conditions,
                )
            )

        count_result = await session.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total = int(count_result.scalar_one())

        stmt = stmt.offset(offset).limit(limit)
        result = await session.execute(stmt)
        items = [_resource_to_domain(r) for r in result.scalars().all()]
        return items, total


def _resource_to_domain(orm: ResourceORM) -> Resource:
    return Resource(
        id=uuid.UUID(orm.id),
        title=orm.title,
        resource_type=ResourceType(orm.resource_type),
        status=ResourceStatus(orm.status),
        file_fingerprint=orm.file_fingerprint,
        isbn=orm.isbn,
        dedup_key=orm.dedup_key,
        created_by=uuid.UUID(orm.created_by),
        created_at=datetime.fromisoformat(orm.created_at),
        updated_at=datetime.fromisoformat(orm.updated_at),
        owner_scope_type=orm.owner_scope_type,
        owner_scope_ref_id=orm.owner_scope_ref_id,
    )


# ---------------------------------------------------------------------------
# ResourceRevisionRepository
# ---------------------------------------------------------------------------

class ResourceRevisionRepository:
    """Manage append-only revision history for resources."""

    @staticmethod
    async def list_for_resource(
        session: AsyncSession, resource_id: uuid.UUID
    ) -> list[ResourceRevision]:
        result = await session.execute(
            select(ResourceRevisionORM)
            .where(ResourceRevisionORM.resource_id == str(resource_id))
            .order_by(ResourceRevisionORM.revision_number)
        )
        return [_revision_to_domain(r) for r in result.scalars().all()]

    @staticmethod
    async def count_for_resource(
        session: AsyncSession, resource_id: uuid.UUID
    ) -> int:
        result = await session.execute(
            select(ResourceRevisionORM).where(
                ResourceRevisionORM.resource_id == str(resource_id)
            )
        )
        return len(result.scalars().all())

    @staticmethod
    async def save(
        session: AsyncSession, revision: ResourceRevision
    ) -> ResourceRevision:
        orm = ResourceRevisionORM(
            id=str(revision.id),
            resource_id=str(revision.resource_id),
            revision_number=revision.revision_number,
            file_path=revision.file_path,
            file_hash=revision.file_hash,
            file_size=revision.file_size,
            imported_by=str(revision.imported_by),
            created_at=revision.created_at.isoformat(),
        )
        session.add(orm)
        await session.flush()
        return revision

    @staticmethod
    async def delete_oldest_for_resource(
        session: AsyncSession, resource_id: uuid.UUID
    ) -> None:
        """Delete the revision with the lowest revision_number for this resource."""
        result = await session.execute(
            select(ResourceRevisionORM)
            .where(ResourceRevisionORM.resource_id == str(resource_id))
            .order_by(ResourceRevisionORM.revision_number)
            .limit(1)
        )
        oldest = result.scalar_one_or_none()
        if oldest is not None:
            await session.delete(oldest)
            await session.flush()


def _revision_to_domain(orm: ResourceRevisionORM) -> ResourceRevision:
    return ResourceRevision(
        id=uuid.UUID(orm.id),
        resource_id=uuid.UUID(orm.resource_id),
        revision_number=orm.revision_number,
        file_path=orm.file_path,
        file_hash=orm.file_hash,
        file_size=orm.file_size,
        imported_by=uuid.UUID(orm.imported_by),
        created_at=datetime.fromisoformat(orm.created_at),
    )


# ---------------------------------------------------------------------------
# ReviewTaskRepository
# ---------------------------------------------------------------------------

class ReviewTaskRepository:
    """Manage review task assignments for resources in IN_REVIEW state."""

    @staticmethod
    async def get_open_for_resource(
        session: AsyncSession, resource_id: uuid.UUID
    ) -> Optional[ReviewTask]:
        result = await session.execute(
            select(ReviewTaskORM).where(
                ReviewTaskORM.resource_id == str(resource_id),
                ReviewTaskORM.decision == None,  # noqa: E711
            )
        )
        orm = result.scalar_one_or_none()
        return _review_task_to_domain(orm) if orm else None

    @staticmethod
    async def save(
        session: AsyncSession, task: ReviewTask
    ) -> ReviewTask:
        result = await session.execute(
            select(ReviewTaskORM).where(ReviewTaskORM.id == str(task.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = ReviewTaskORM(
                id=str(task.id),
                resource_id=str(task.resource_id),
                assigned_to=str(task.assigned_to),
                decision=task.decision.value if task.decision else None,
                notes=task.notes,
                created_at=task.created_at.isoformat(),
                completed_at=_fmt_dt(task.completed_at),
            )
            session.add(orm)
        else:
            orm.decision = task.decision.value if task.decision else None
            orm.notes = task.notes
            orm.completed_at = _fmt_dt(task.completed_at)
        await session.flush()
        return task


def _review_task_to_domain(orm: ReviewTaskORM) -> ReviewTask:
    return ReviewTask(
        id=uuid.UUID(orm.id),
        resource_id=uuid.UUID(orm.resource_id),
        assigned_to=uuid.UUID(orm.assigned_to),
        decision=ReviewDecision(orm.decision) if orm.decision else None,
        notes=orm.notes,
        created_at=datetime.fromisoformat(orm.created_at),
        completed_at=_parse_dt(orm.completed_at),
    )


# ---------------------------------------------------------------------------
# ResourceMetadataRepository
# ---------------------------------------------------------------------------

class ResourceMetadataRepository:
    """Persist and retrieve resource metadata, categories, and keywords."""

    @staticmethod
    async def get_by_resource_id(
        session: AsyncSession, resource_id: uuid.UUID
    ) -> Optional[ResourceMetadata]:
        result = await session.execute(
            select(ResourceMetadataORM).where(
                ResourceMetadataORM.resource_id == str(resource_id)
            )
        )
        meta_orm = result.scalar_one_or_none()

        cat_result = await session.execute(
            select(ResourceCategoryORM).where(
                ResourceCategoryORM.resource_id == str(resource_id)
            )
        )
        cat_ids = [uuid.UUID(r.category_id) for r in cat_result.scalars().all()]

        kw_result = await session.execute(
            select(ResourceKeywordORM).where(
                ResourceKeywordORM.resource_id == str(resource_id)
            )
        )
        keywords = [r.keyword for r in kw_result.scalars().all()]

        if meta_orm is None and not cat_ids and not keywords:
            return None

        from district_console.domain.enums import TimelinesType
        return ResourceMetadata(
            resource_id=resource_id,
            category_ids=cat_ids,
            keywords=keywords,
            timeliness=TimelinesType(meta_orm.timeliness) if meta_orm and meta_orm.timeliness else None,
            source=meta_orm.source if meta_orm else None,
            copyright=meta_orm.copyright if meta_orm else None,
            theme=meta_orm.theme if meta_orm else None,
            difficulty_level=meta_orm.difficulty_level if meta_orm else None,
            age_range_min=meta_orm.age_range_min if meta_orm else None,
            age_range_max=meta_orm.age_range_max if meta_orm else None,
        )

    @staticmethod
    async def save_metadata(
        session: AsyncSession,
        resource_id: uuid.UUID,
        metadata: ResourceMetadata,
    ) -> None:
        rid = str(resource_id)

        # Upsert metadata row
        meta_result = await session.execute(
            select(ResourceMetadataORM).where(ResourceMetadataORM.resource_id == rid)
        )
        meta_orm = meta_result.scalar_one_or_none()
        timeliness_val = None
        if metadata.timeliness is not None:
            timeliness_val = metadata.timeliness.value if hasattr(metadata.timeliness, "value") else metadata.timeliness
        if meta_orm is None:
            meta_orm = ResourceMetadataORM(
                resource_id=rid,
                timeliness=timeliness_val,
                source=metadata.source,
                copyright=metadata.copyright,
                theme=metadata.theme,
                difficulty_level=metadata.difficulty_level,
                age_range_min=metadata.age_range_min,
                age_range_max=metadata.age_range_max,
            )
            session.add(meta_orm)
        else:
            meta_orm.timeliness = timeliness_val
            meta_orm.source = metadata.source
            meta_orm.copyright = metadata.copyright
            meta_orm.theme = metadata.theme
            meta_orm.difficulty_level = metadata.difficulty_level
            meta_orm.age_range_min = metadata.age_range_min
            meta_orm.age_range_max = metadata.age_range_max

        # Replace category associations
        await session.execute(
            delete(ResourceCategoryORM).where(ResourceCategoryORM.resource_id == rid)
        )
        for cat_id in metadata.category_ids:
            session.add(ResourceCategoryORM(resource_id=rid, category_id=str(cat_id)))

        # Replace keyword associations
        await session.execute(
            delete(ResourceKeywordORM).where(ResourceKeywordORM.resource_id == rid)
        )
        for kw in metadata.keywords:
            session.add(ResourceKeywordORM(resource_id=rid, keyword=kw))

        await session.flush()


# ---------------------------------------------------------------------------
# InventoryRepository
# ---------------------------------------------------------------------------

class InventoryRepository:
    """Warehouse, location, item, and stock balance operations."""

    # -- InventoryItem --

    @staticmethod
    async def get_item_by_id(
        session: AsyncSession, item_id: uuid.UUID
    ) -> Optional[InventoryItem]:
        result = await session.execute(
            select(InventoryItemORM).where(InventoryItemORM.id == str(item_id))
        )
        orm = result.scalar_one_or_none()
        return _item_to_domain(orm) if orm else None

    @staticmethod
    async def get_item_by_sku(
        session: AsyncSession, sku: str
    ) -> Optional[InventoryItem]:
        result = await session.execute(
            select(InventoryItemORM).where(InventoryItemORM.sku == sku)
        )
        orm = result.scalar_one_or_none()
        return _item_to_domain(orm) if orm else None

    @staticmethod
    async def save_item(
        session: AsyncSession, item: InventoryItem
    ) -> InventoryItem:
        result = await session.execute(
            select(InventoryItemORM).where(InventoryItemORM.id == str(item.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = InventoryItemORM(
                id=str(item.id),
                sku=item.sku,
                name=item.name,
                description=item.description,
                unit_cost=str(item.unit_cost),
                created_by=str(item.created_by),
                created_at=item.created_at.isoformat(),
            )
            session.add(orm)
        else:
            orm.sku = item.sku
            orm.name = item.name
            orm.description = item.description
            orm.unit_cost = str(item.unit_cost)
        await session.flush()
        return item

    @staticmethod
    async def list_items(
        session: AsyncSession, offset: int = 0, limit: int = 50
    ) -> tuple[list[InventoryItem], int]:
        count_result = await session.execute(select(InventoryItemORM))
        total = len(count_result.scalars().all())
        result = await session.execute(
            select(InventoryItemORM).offset(offset).limit(limit)
        )
        return [_item_to_domain(r) for r in result.scalars().all()], total

    # -- Warehouse --

    @staticmethod
    async def get_warehouse_by_id(
        session: AsyncSession, warehouse_id: uuid.UUID
    ) -> Optional[Warehouse]:
        result = await session.execute(
            select(WarehouseORM).where(WarehouseORM.id == str(warehouse_id))
        )
        orm = result.scalar_one_or_none()
        return _warehouse_to_domain(orm) if orm else None

    @staticmethod
    async def save_warehouse(
        session: AsyncSession, warehouse: Warehouse
    ) -> Warehouse:
        result = await session.execute(
            select(WarehouseORM).where(WarehouseORM.id == str(warehouse.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = WarehouseORM(
                id=str(warehouse.id),
                name=warehouse.name,
                school_id=str(warehouse.school_id),
                address=warehouse.address,
                is_active=warehouse.is_active,
            )
            session.add(orm)
        else:
            orm.name = warehouse.name
            orm.address = warehouse.address
            orm.is_active = warehouse.is_active
        await session.flush()
        return warehouse

    @staticmethod
    async def list_warehouses(
        session: AsyncSession,
        school_ids: Optional[list[uuid.UUID]] = None,
    ) -> list[Warehouse]:
        stmt = select(WarehouseORM)
        if school_ids is not None:
            stmt = stmt.where(WarehouseORM.school_id.in_([str(sid) for sid in school_ids]))
        result = await session.execute(stmt)
        return [_warehouse_to_domain(r) for r in result.scalars().all()]

    # -- Location --

    @staticmethod
    async def get_location_by_id(
        session: AsyncSession, location_id: uuid.UUID
    ) -> Optional[Location]:
        result = await session.execute(
            select(LocationORM).where(LocationORM.id == str(location_id))
        )
        orm = result.scalar_one_or_none()
        return _location_to_domain(orm) if orm else None

    @staticmethod
    async def save_location(
        session: AsyncSession, location: Location
    ) -> Location:
        result = await session.execute(
            select(LocationORM).where(LocationORM.id == str(location.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = LocationORM(
                id=str(location.id),
                warehouse_id=str(location.warehouse_id),
                zone=location.zone,
                aisle=location.aisle,
                bin_label=location.bin_label,
                is_active=location.is_active,
            )
            session.add(orm)
        else:
            orm.zone = location.zone
            orm.aisle = location.aisle
            orm.bin_label = location.bin_label
            orm.is_active = location.is_active
        await session.flush()
        return location

    @staticmethod
    async def list_locations(
        session: AsyncSession,
        warehouse_id: Optional[uuid.UUID] = None,
        warehouse_ids: Optional[list[uuid.UUID]] = None,
    ) -> list[Location]:
        stmt = select(LocationORM)
        if warehouse_id is not None:
            stmt = stmt.where(LocationORM.warehouse_id == str(warehouse_id))
        elif warehouse_ids is not None:
            stmt = stmt.where(
                LocationORM.warehouse_id.in_([str(wid) for wid in warehouse_ids])
            )
        result = await session.execute(stmt)
        return [_location_to_domain(r) for r in result.scalars().all()]

    # -- StockBalance --

    @staticmethod
    async def get_stock_balance(
        session: AsyncSession,
        item_id: uuid.UUID,
        location_id: uuid.UUID,
        batch_id: Optional[str] = None,
        serial_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Optional[StockBalance]:
        stmt = select(StockBalanceORM).where(
            StockBalanceORM.item_id == str(item_id),
            StockBalanceORM.location_id == str(location_id),
            StockBalanceORM.batch_id.is_(None) if batch_id is None else StockBalanceORM.batch_id == batch_id,
            StockBalanceORM.serial_id.is_(None) if serial_id is None else StockBalanceORM.serial_id == serial_id,
        )
        if status is not None:
            stmt = stmt.where(StockBalanceORM.status == status)

        result = await session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _stock_to_domain(orm) if orm else None

    @staticmethod
    async def get_stock_balance_by_id(
        session: AsyncSession, balance_id: uuid.UUID
    ) -> Optional[StockBalance]:
        result = await session.execute(
            select(StockBalanceORM).where(StockBalanceORM.id == str(balance_id))
        )
        orm = result.scalar_one_or_none()
        return _stock_to_domain(orm) if orm else None

    @staticmethod
    async def save_stock_balance(
        session: AsyncSession, balance: StockBalance
    ) -> StockBalance:
        result = await session.execute(
            select(StockBalanceORM).where(StockBalanceORM.id == str(balance.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = StockBalanceORM(
                id=str(balance.id),
                item_id=str(balance.item_id),
                location_id=str(balance.location_id),
                batch_id=balance.batch_id,
                serial_id=balance.serial_id,
                status=balance.status.value,
                quantity=balance.quantity,
                is_frozen=balance.is_frozen,
                freeze_reason=balance.freeze_reason,
                frozen_by=str(balance.frozen_by) if balance.frozen_by else None,
                frozen_at=_fmt_dt(balance.frozen_at),
            )
            session.add(orm)
        else:
            orm.status = balance.status.value
            orm.quantity = balance.quantity
            orm.is_frozen = balance.is_frozen
            orm.freeze_reason = balance.freeze_reason
            orm.frozen_by = str(balance.frozen_by) if balance.frozen_by else None
            orm.frozen_at = _fmt_dt(balance.frozen_at)
        await session.flush()
        return balance

    @staticmethod
    async def list_stock(
        session: AsyncSession,
        item_id: Optional[uuid.UUID] = None,
        location_id: Optional[uuid.UUID] = None,
        batch_id: Optional[str] = None,
        serial_id: Optional[str] = None,
        status: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
        location_ids: Optional[list[uuid.UUID]] = None,
    ) -> tuple[list[StockBalance], int]:
        stmt = select(StockBalanceORM)
        if item_id is not None:
            stmt = stmt.where(StockBalanceORM.item_id == str(item_id))
        if location_id is not None:
            stmt = stmt.where(StockBalanceORM.location_id == str(location_id))
        elif location_ids is not None:
            # Object-level scope filter: restrict to locations within user's scope
            stmt = stmt.where(
                StockBalanceORM.location_id.in_([str(lid) for lid in location_ids])
            )
        if batch_id is not None:
            stmt = stmt.where(StockBalanceORM.batch_id == batch_id)
        if serial_id is not None:
            stmt = stmt.where(StockBalanceORM.serial_id == serial_id)
        if status is not None:
            stmt = stmt.where(StockBalanceORM.status == status)

        count_result = await session.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total = int(count_result.scalar_one())

        result = await session.execute(stmt.offset(offset).limit(limit))
        return [_stock_to_domain(r) for r in result.scalars().all()], total


def _item_to_domain(orm: InventoryItemORM) -> InventoryItem:
    return InventoryItem(
        id=uuid.UUID(orm.id),
        sku=orm.sku,
        name=orm.name,
        description=orm.description,
        unit_cost=Decimal(orm.unit_cost),
        created_by=uuid.UUID(orm.created_by),
        created_at=datetime.fromisoformat(orm.created_at),
    )


def _warehouse_to_domain(orm: WarehouseORM) -> Warehouse:
    return Warehouse(
        id=uuid.UUID(orm.id),
        name=orm.name,
        school_id=uuid.UUID(orm.school_id),
        address=orm.address,
        is_active=orm.is_active,
    )


def _location_to_domain(orm: LocationORM) -> Location:
    return Location(
        id=uuid.UUID(orm.id),
        warehouse_id=uuid.UUID(orm.warehouse_id),
        zone=orm.zone,
        aisle=orm.aisle,
        bin_label=orm.bin_label,
        is_active=orm.is_active,
    )


def _stock_to_domain(orm: StockBalanceORM) -> StockBalance:
    return StockBalance(
        id=uuid.UUID(orm.id),
        item_id=uuid.UUID(orm.item_id),
        location_id=uuid.UUID(orm.location_id),
        batch_id=orm.batch_id,
        serial_id=orm.serial_id,
        status=StockStatus(orm.status),
        quantity=orm.quantity,
        is_frozen=orm.is_frozen,
        freeze_reason=orm.freeze_reason,
        frozen_by=uuid.UUID(orm.frozen_by) if orm.frozen_by else None,
        frozen_at=_parse_dt(orm.frozen_at),
    )


# ---------------------------------------------------------------------------
# LedgerRepository
# ---------------------------------------------------------------------------

class LedgerRepository:
    """
    Append-only ledger entry storage.

    APPEND-ONLY: append() is the only permitted INSERT path.
    mark_reversed() is the SOLE permitted UPDATE — sets is_reversed=True only.
    No DELETE is ever issued on ledger_entries.
    """

    @staticmethod
    async def append(
        session: AsyncSession, entry: LedgerEntry
    ) -> LedgerEntry:
        # APPEND-ONLY: INSERT only — never UPDATE or DELETE ledger_entries
        orm = LedgerEntryORM(
            id=str(entry.id),
            item_id=str(entry.item_id),
            location_id=str(entry.location_id),
            entry_type=entry.entry_type.value,
            quantity_delta=entry.quantity_delta,
            quantity_after=entry.quantity_after,
            operator_id=str(entry.operator_id),
            reason_code=entry.reason_code,
            created_at=entry.created_at.isoformat(),
            reference_id=entry.reference_id,
            is_reversed=entry.is_reversed,
            reversal_of_id=str(entry.reversal_of_id) if entry.reversal_of_id else None,
        )
        session.add(orm)
        await session.flush()
        return entry

    @staticmethod
    async def get_by_id(
        session: AsyncSession, entry_id: uuid.UUID
    ) -> Optional[LedgerEntry]:
        result = await session.execute(
            select(LedgerEntryORM).where(LedgerEntryORM.id == str(entry_id))
        )
        orm = result.scalar_one_or_none()
        return _ledger_entry_to_domain(orm) if orm else None

    @staticmethod
    async def list(
        session: AsyncSession,
        item_id: Optional[uuid.UUID] = None,
        location_id: Optional[uuid.UUID] = None,
        location_ids: Optional[list[uuid.UUID]] = None,
        entry_type: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[LedgerEntry], int]:
        stmt = select(LedgerEntryORM)
        if item_id is not None:
            stmt = stmt.where(LedgerEntryORM.item_id == str(item_id))
        if location_id is not None:
            stmt = stmt.where(LedgerEntryORM.location_id == str(location_id))
        elif location_ids is not None:
            stmt = stmt.where(
                LedgerEntryORM.location_id.in_([str(lid) for lid in location_ids])
            )
        if entry_type is not None:
            stmt = stmt.where(LedgerEntryORM.entry_type == entry_type)

        count_result = await session.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total = int(count_result.scalar_one())

        result = await session.execute(
            stmt.order_by(LedgerEntryORM.created_at).offset(offset).limit(limit)
        )
        return [_ledger_entry_to_domain(r) for r in result.scalars().all()], total

    @staticmethod
    async def mark_reversed(
        session: AsyncSession, entry_id: uuid.UUID
    ) -> None:
        # PERMITTED EXCEPTION: UPDATE is_reversed=True only; never deletes, never other fields
        result = await session.execute(
            select(LedgerEntryORM).where(LedgerEntryORM.id == str(entry_id))
        )
        orm = result.scalar_one_or_none()
        if orm is not None:
            orm.is_reversed = True
            await session.flush()


def _ledger_entry_to_domain(orm: LedgerEntryORM) -> LedgerEntry:
    return LedgerEntry(
        id=uuid.UUID(orm.id),
        item_id=uuid.UUID(orm.item_id),
        location_id=uuid.UUID(orm.location_id),
        entry_type=LedgerEntryType(orm.entry_type),
        quantity_delta=orm.quantity_delta,
        quantity_after=orm.quantity_after,
        operator_id=uuid.UUID(orm.operator_id),
        reason_code=orm.reason_code,
        created_at=datetime.fromisoformat(orm.created_at),
        reference_id=orm.reference_id,
        is_reversed=orm.is_reversed,
        reversal_of_id=uuid.UUID(orm.reversal_of_id) if orm.reversal_of_id else None,
    )


# ---------------------------------------------------------------------------
# CountSessionRepository
# ---------------------------------------------------------------------------

class CountSessionRepository:
    """Manage count sessions, count lines, and approvals."""

    @staticmethod
    async def get_by_id(
        session: AsyncSession, session_id: uuid.UUID
    ) -> Optional[CountSession]:
        result = await session.execute(
            select(CountSessionORM).where(CountSessionORM.id == str(session_id))
        )
        orm = result.scalar_one_or_none()
        return _count_session_to_domain(orm) if orm else None

    @staticmethod
    async def save_session(
        session: AsyncSession, count_session: CountSession
    ) -> CountSession:
        result = await session.execute(
            select(CountSessionORM).where(CountSessionORM.id == str(count_session.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = CountSessionORM(
                id=str(count_session.id),
                mode=count_session.mode.value,
                status=count_session.status.value,
                warehouse_id=str(count_session.warehouse_id),
                created_by=str(count_session.created_by),
                created_at=count_session.created_at.isoformat(),
                last_activity_at=count_session.last_activity_at.isoformat(),
                closed_at=_fmt_dt(count_session.closed_at),
                approved_by=str(count_session.approved_by) if count_session.approved_by else None,
                approved_at=_fmt_dt(count_session.approved_at),
            )
            session.add(orm)
        else:
            orm.status = count_session.status.value
            orm.last_activity_at = count_session.last_activity_at.isoformat()
            orm.closed_at = _fmt_dt(count_session.closed_at)
            orm.approved_by = str(count_session.approved_by) if count_session.approved_by else None
            orm.approved_at = _fmt_dt(count_session.approved_at)
        await session.flush()
        return count_session

    @staticmethod
    async def list_by_status(
        session: AsyncSession,
        status: Optional[str] = None,
        warehouse_ids: Optional[list[uuid.UUID]] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[CountSession], int]:
        """List count sessions, optionally filtered by status."""
        q = select(CountSessionORM)
        if status:
            q = q.where(CountSessionORM.status == status)
        if warehouse_ids is not None:
            q = q.where(CountSessionORM.warehouse_id.in_([str(wid) for wid in warehouse_ids]))
        count_q = select(func.count()).select_from(q.subquery())
        total = (await session.execute(count_q)).scalar_one()
        result = await session.execute(q.offset(offset).limit(limit))
        return [_count_session_to_domain(r) for r in result.scalars().all()], total

    @staticmethod
    async def get_lines(
        session: AsyncSession, session_id: uuid.UUID
    ) -> list[CountLine]:
        result = await session.execute(
            select(CountLineORM).where(CountLineORM.session_id == str(session_id))
        )
        return [_count_line_to_domain(r) for r in result.scalars().all()]

    @staticmethod
    async def get_line_by_id(
        session: AsyncSession, session_id: uuid.UUID, line_id: uuid.UUID
    ) -> Optional[CountLine]:
        result = await session.execute(
            select(CountLineORM).where(
                CountLineORM.id == str(line_id),
                CountLineORM.session_id == str(session_id),
            )
        )
        orm = result.scalar_one_or_none()
        return _count_line_to_domain(orm) if orm else None

    @staticmethod
    async def save_line(
        session: AsyncSession, line: CountLine
    ) -> CountLine:
        result = await session.execute(
            select(CountLineORM).where(CountLineORM.id == str(line.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = CountLineORM(
                id=str(line.id),
                session_id=str(line.session_id),
                item_id=str(line.item_id),
                location_id=str(line.location_id),
                expected_qty=line.expected_qty,
                counted_qty=line.counted_qty,
                variance_qty=line.variance_qty,
                variance_value=str(line.variance_value),
                requires_approval=line.requires_approval,
                reason_code=line.reason_code,
            )
            session.add(orm)
        else:
            orm.counted_qty = line.counted_qty
            orm.variance_qty = line.variance_qty
            orm.variance_value = str(line.variance_value)
            orm.requires_approval = line.requires_approval
            orm.reason_code = line.reason_code
        await session.flush()
        return line

    @staticmethod
    async def save_approval(
        session: AsyncSession, approval: CountApproval
    ) -> CountApproval:
        orm = CountApprovalORM(
            id=str(approval.id),
            session_id=str(approval.session_id),
            reviewed_by=str(approval.reviewed_by),
            decision=approval.decision.value,
            notes=approval.notes,
            decided_at=approval.decided_at.isoformat(),
        )
        session.add(orm)
        await session.flush()
        return approval


def _count_session_to_domain(orm: CountSessionORM) -> CountSession:
    return CountSession(
        id=uuid.UUID(orm.id),
        mode=CountMode(orm.mode),
        status=CountSessionStatus(orm.status),
        warehouse_id=uuid.UUID(orm.warehouse_id),
        created_by=uuid.UUID(orm.created_by),
        created_at=datetime.fromisoformat(orm.created_at),
        last_activity_at=datetime.fromisoformat(orm.last_activity_at),
        closed_at=_parse_dt(orm.closed_at),
        approved_by=uuid.UUID(orm.approved_by) if orm.approved_by else None,
        approved_at=_parse_dt(orm.approved_at),
    )


def _count_line_to_domain(orm: CountLineORM) -> CountLine:
    return CountLine(
        id=uuid.UUID(orm.id),
        session_id=uuid.UUID(orm.session_id),
        item_id=uuid.UUID(orm.item_id),
        location_id=uuid.UUID(orm.location_id),
        expected_qty=orm.expected_qty,
        counted_qty=orm.counted_qty,
        variance_qty=orm.variance_qty,
        variance_value=Decimal(orm.variance_value),
        requires_approval=orm.requires_approval,
        reason_code=orm.reason_code,
    )


# ---------------------------------------------------------------------------
# RelocationRepository
# ---------------------------------------------------------------------------

class RelocationRepository:
    """Persist and query intra-warehouse relocation records."""

    @staticmethod
    async def save(
        session: AsyncSession, relocation: Relocation
    ) -> Relocation:
        orm = RelocationORM(
            id=str(relocation.id),
            item_id=str(relocation.item_id),
            from_location_id=str(relocation.from_location_id),
            to_location_id=str(relocation.to_location_id),
            quantity=relocation.quantity,
            operator_id=str(relocation.operator_id),
            device_source=relocation.device_source.value,
            created_at=relocation.created_at.isoformat(),
            ledger_debit_entry_id=str(relocation.ledger_debit_entry_id),
            ledger_credit_entry_id=str(relocation.ledger_credit_entry_id),
        )
        session.add(orm)
        await session.flush()
        return relocation

    @staticmethod
    async def list(
        session: AsyncSession,
        item_id: Optional[uuid.UUID] = None,
        operator_id: Optional[uuid.UUID] = None,
        location_ids: Optional[list[uuid.UUID]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Relocation], int]:
        stmt = select(RelocationORM)
        if item_id is not None:
            stmt = stmt.where(RelocationORM.item_id == str(item_id))
        if operator_id is not None:
            stmt = stmt.where(RelocationORM.operator_id == str(operator_id))
        if location_ids is not None:
            location_ids_str = [str(lid) for lid in location_ids]
            stmt = stmt.where(
                RelocationORM.from_location_id.in_(location_ids_str),
                RelocationORM.to_location_id.in_(location_ids_str),
            )
        if date_from is not None:
            stmt = stmt.where(RelocationORM.created_at >= date_from.isoformat())
        if date_to is not None:
            stmt = stmt.where(RelocationORM.created_at <= date_to.isoformat())

        count_result = await session.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total = int(count_result.scalar_one())

        result = await session.execute(
            stmt.order_by(RelocationORM.created_at.desc()).offset(offset).limit(limit)
        )
        return [_relocation_to_domain(r) for r in result.scalars().all()], total


def _relocation_to_domain(orm: RelocationORM) -> Relocation:
    return Relocation(
        id=uuid.UUID(orm.id),
        item_id=uuid.UUID(orm.item_id),
        from_location_id=uuid.UUID(orm.from_location_id),
        to_location_id=uuid.UUID(orm.to_location_id),
        quantity=orm.quantity,
        operator_id=uuid.UUID(orm.operator_id),
        device_source=DeviceSource(orm.device_source),
        created_at=datetime.fromisoformat(orm.created_at),
        ledger_debit_entry_id=uuid.UUID(orm.ledger_debit_entry_id),
        ledger_credit_entry_id=uuid.UUID(orm.ledger_credit_entry_id),
    )


# ---------------------------------------------------------------------------
# ConfigRepository
# ---------------------------------------------------------------------------

class ConfigRepository:
    """CRUD for configuration dictionary entries."""

    @staticmethod
    async def list_all(
        session: AsyncSession,
        category: Optional[str] = None,
        offset: int = 0,
        batch_id: Optional[str] = None,
        serial_id: Optional[str] = None,
        limit: int = 50,
    ) -> tuple[list, int]:
        from district_console.infrastructure.orm import ConfigDictionaryORM
        stmt = select(ConfigDictionaryORM)
        if category:
            stmt = stmt.where(ConfigDictionaryORM.category == category)
        count_result = await session.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total = int(count_result.scalar_one())
        if batch_id is not None:
            stmt = stmt.where(StockBalanceORM.batch_id == batch_id)
        if serial_id is not None:
            stmt = stmt.where(StockBalanceORM.serial_id == serial_id)
        result = await session.execute(
            stmt.order_by(ConfigDictionaryORM.category, ConfigDictionaryORM.key)
            .offset(offset).limit(limit)
        )
        return [_config_to_domain(r) for r in result.scalars().all()], total

    @staticmethod
    async def get(
        session: AsyncSession, category: str, key: str
    ) -> Optional[object]:
        from district_console.infrastructure.orm import ConfigDictionaryORM
        result = await session.execute(
            select(ConfigDictionaryORM).where(
                ConfigDictionaryORM.category == category,
                ConfigDictionaryORM.key == key,
            )
        )
        orm = result.scalar_one_or_none()
        return _config_to_domain(orm) if orm else None

    @staticmethod
    async def get_by_id(
        session: AsyncSession, entry_id: uuid.UUID
    ) -> Optional[object]:
        from district_console.infrastructure.orm import ConfigDictionaryORM
        result = await session.execute(
            select(ConfigDictionaryORM).where(ConfigDictionaryORM.id == str(entry_id))
        )
        orm = result.scalar_one_or_none()
        return _config_to_domain(orm) if orm else None

    @staticmethod
    async def save(session: AsyncSession, entry: object) -> object:
        from district_console.infrastructure.orm import ConfigDictionaryORM
        from district_console.domain.entities.config import ConfigDictionary
        assert isinstance(entry, ConfigDictionary)
        result = await session.execute(
            select(ConfigDictionaryORM).where(ConfigDictionaryORM.id == str(entry.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = ConfigDictionaryORM(
                id=str(entry.id),
                category=entry.category,
                key=entry.key,
                value=entry.value,
                description=entry.description,
                is_system=entry.is_system,
                updated_by=str(entry.updated_by) if entry.updated_by else None,
                updated_at=_fmt_dt(entry.updated_at),
            )
            session.add(orm)
        else:
            orm.value = entry.value
            orm.description = entry.description
            orm.updated_by = str(entry.updated_by) if entry.updated_by else None
            orm.updated_at = _fmt_dt(entry.updated_at)
        await session.flush()
        return entry

    @staticmethod
    async def delete(session: AsyncSession, entry_id: uuid.UUID) -> None:
        from district_console.infrastructure.orm import ConfigDictionaryORM
        result = await session.execute(
            select(ConfigDictionaryORM).where(ConfigDictionaryORM.id == str(entry_id))
        )
        orm = result.scalar_one_or_none()
        if orm is not None:
            await session.delete(orm)
            await session.flush()


def _config_to_domain(orm: object) -> object:
    from district_console.infrastructure.orm import ConfigDictionaryORM
    from district_console.domain.entities.config import ConfigDictionary
    assert isinstance(orm, ConfigDictionaryORM)
    return ConfigDictionary(
        id=uuid.UUID(orm.id),
        category=orm.category,
        key=orm.key,
        value=orm.value,
        description=orm.description,
        is_system=orm.is_system,
        updated_by=uuid.UUID(orm.updated_by) if orm.updated_by else None,
        updated_at=_parse_dt(orm.updated_at),
    )


# ---------------------------------------------------------------------------
# WorkflowNodeRepository
# ---------------------------------------------------------------------------

class WorkflowNodeRepository:
    """CRUD for workflow transition nodes."""

    @staticmethod
    async def list_by_workflow(
        session: AsyncSession, workflow_name: Optional[str] = None
    ) -> list:
        from district_console.infrastructure.orm import WorkflowNodeORM
        stmt = select(WorkflowNodeORM)
        if workflow_name:
            stmt = stmt.where(WorkflowNodeORM.workflow_name == workflow_name)
        result = await session.execute(stmt.order_by(WorkflowNodeORM.workflow_name))
        return [_workflow_node_to_domain(r) for r in result.scalars().all()]

    @staticmethod
    async def get_by_id(session: AsyncSession, node_id: uuid.UUID) -> Optional[object]:
        from district_console.infrastructure.orm import WorkflowNodeORM
        result = await session.execute(
            select(WorkflowNodeORM).where(WorkflowNodeORM.id == str(node_id))
        )
        orm = result.scalar_one_or_none()
        return _workflow_node_to_domain(orm) if orm else None

    @staticmethod
    async def save(session: AsyncSession, node: object) -> object:
        from district_console.infrastructure.orm import WorkflowNodeORM
        from district_console.domain.entities.config import WorkflowNode
        assert isinstance(node, WorkflowNode)
        result = await session.execute(
            select(WorkflowNodeORM).where(WorkflowNodeORM.id == str(node.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = WorkflowNodeORM(
                id=str(node.id),
                workflow_name=node.workflow_name,
                from_state=node.from_state,
                to_state=node.to_state,
                required_role=node.required_role.value,
                condition_json=node.condition_json,
            )
            session.add(orm)
        else:
            orm.workflow_name = node.workflow_name
            orm.from_state = node.from_state
            orm.to_state = node.to_state
            orm.required_role = node.required_role.value
            orm.condition_json = node.condition_json
        await session.flush()
        return node

    @staticmethod
    async def delete(session: AsyncSession, node_id: uuid.UUID) -> None:
        from district_console.infrastructure.orm import WorkflowNodeORM
        result = await session.execute(
            select(WorkflowNodeORM).where(WorkflowNodeORM.id == str(node_id))
        )
        orm = result.scalar_one_or_none()
        if orm is not None:
            await session.delete(orm)
            await session.flush()


def _workflow_node_to_domain(orm: object) -> object:
    from district_console.infrastructure.orm import WorkflowNodeORM
    from district_console.domain.entities.config import WorkflowNode
    assert isinstance(orm, WorkflowNodeORM)
    return WorkflowNode(
        id=uuid.UUID(orm.id),
        workflow_name=orm.workflow_name,
        from_state=orm.from_state,
        to_state=orm.to_state,
        required_role=RoleType(orm.required_role),
        condition_json=orm.condition_json,
    )


# ---------------------------------------------------------------------------
# NotificationTemplateRepository
# ---------------------------------------------------------------------------

class NotificationTemplateRepository:
    """Manage local notification templates."""

    @staticmethod
    async def list_all(session: AsyncSession) -> list:
        from district_console.infrastructure.orm import NotificationTemplateORM
        result = await session.execute(
            select(NotificationTemplateORM).order_by(NotificationTemplateORM.name)
        )
        return [_template_to_domain(r) for r in result.scalars().all()]

    @staticmethod
    async def get_by_event_type(
        session: AsyncSession, event_type: str
    ) -> Optional[object]:
        from district_console.infrastructure.orm import NotificationTemplateORM
        result = await session.execute(
            select(NotificationTemplateORM).where(
                NotificationTemplateORM.event_type == event_type,
                NotificationTemplateORM.is_active == True,  # noqa: E712
            )
        )
        orm = result.scalar_one_or_none()
        return _template_to_domain(orm) if orm else None

    @staticmethod
    async def get_by_id(session: AsyncSession, template_id: uuid.UUID) -> Optional[object]:
        from district_console.infrastructure.orm import NotificationTemplateORM
        result = await session.execute(
            select(NotificationTemplateORM).where(
                NotificationTemplateORM.id == str(template_id)
            )
        )
        orm = result.scalar_one_or_none()
        return _template_to_domain(orm) if orm else None

    @staticmethod
    async def save(session: AsyncSession, template: object) -> object:
        from district_console.infrastructure.orm import NotificationTemplateORM
        from district_console.domain.entities.config import NotificationTemplate
        assert isinstance(template, NotificationTemplate)
        result = await session.execute(
            select(NotificationTemplateORM).where(
                NotificationTemplateORM.id == str(template.id)
            )
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = NotificationTemplateORM(
                id=str(template.id),
                name=template.name,
                event_type=template.event_type,
                subject_template=template.subject_template,
                body_template=template.body_template,
                is_active=template.is_active,
            )
            session.add(orm)
        else:
            orm.name = template.name
            orm.event_type = template.event_type
            orm.subject_template = template.subject_template
            orm.body_template = template.body_template
            orm.is_active = template.is_active
        await session.flush()
        return template


def _template_to_domain(orm: object) -> object:
    from district_console.infrastructure.orm import NotificationTemplateORM
    from district_console.domain.entities.config import NotificationTemplate
    assert isinstance(orm, NotificationTemplateORM)
    return NotificationTemplate(
        id=uuid.UUID(orm.id),
        name=orm.name,
        event_type=orm.event_type,
        subject_template=orm.subject_template,
        body_template=orm.body_template,
        is_active=orm.is_active,
    )


# ---------------------------------------------------------------------------
# DistrictDescriptorRepository
# ---------------------------------------------------------------------------

class DistrictDescriptorRepository:
    """Manage district/regional reporting descriptors."""

    @staticmethod
    async def list_all(session: AsyncSession) -> list:
        from district_console.infrastructure.orm import DistrictDescriptorORM
        result = await session.execute(
            select(DistrictDescriptorORM).order_by(DistrictDescriptorORM.key)
        )
        return [_descriptor_to_domain(r) for r in result.scalars().all()]

    @staticmethod
    async def get_by_key(session: AsyncSession, key: str) -> Optional[object]:
        from district_console.infrastructure.orm import DistrictDescriptorORM
        result = await session.execute(
            select(DistrictDescriptorORM).where(DistrictDescriptorORM.key == key)
        )
        orm = result.scalar_one_or_none()
        return _descriptor_to_domain(orm) if orm else None

    @staticmethod
    async def get_by_id(session: AsyncSession, desc_id: uuid.UUID) -> Optional[object]:
        from district_console.infrastructure.orm import DistrictDescriptorORM
        result = await session.execute(
            select(DistrictDescriptorORM).where(DistrictDescriptorORM.id == str(desc_id))
        )
        orm = result.scalar_one_or_none()
        return _descriptor_to_domain(orm) if orm else None

    @staticmethod
    async def save(session: AsyncSession, desc: object) -> object:
        from district_console.infrastructure.orm import DistrictDescriptorORM
        from district_console.domain.entities.config import DistrictDescriptor
        assert isinstance(desc, DistrictDescriptor)
        result = await session.execute(
            select(DistrictDescriptorORM).where(DistrictDescriptorORM.id == str(desc.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = DistrictDescriptorORM(
                id=str(desc.id),
                key=desc.key,
                value=desc.value,
                description=desc.description,
                region=desc.region,
            )
            session.add(orm)
        else:
            orm.key = desc.key
            orm.value = desc.value
            orm.description = desc.description
            orm.region = desc.region
        await session.flush()
        return desc


def _descriptor_to_domain(orm: object) -> object:
    from district_console.infrastructure.orm import DistrictDescriptorORM
    from district_console.domain.entities.config import DistrictDescriptor
    assert isinstance(orm, DistrictDescriptorORM)
    return DistrictDescriptor(
        id=uuid.UUID(orm.id),
        key=orm.key,
        value=orm.value,
        description=orm.description,
        region=orm.region,
    )


# ---------------------------------------------------------------------------
# TaxonomyRepository
# ---------------------------------------------------------------------------

class TaxonomyRepository:
    """Category hierarchy and taxonomy validation rules."""

    @staticmethod
    async def list_categories(
        session: AsyncSession, parent_id: Optional[uuid.UUID] = None
    ) -> list:
        from district_console.infrastructure.orm import CategoryORM
        from district_console.domain.entities.resource_metadata import Category
        stmt = select(CategoryORM)
        if parent_id is not None:
            stmt = stmt.where(CategoryORM.parent_id == str(parent_id))
        else:
            stmt = stmt.where(CategoryORM.parent_id == None)  # noqa: E711
        result = await session.execute(stmt.order_by(CategoryORM.name))
        return [_category_to_domain(r) for r in result.scalars().all()]

    @staticmethod
    async def list_all_categories(session: AsyncSession) -> list:
        from district_console.infrastructure.orm import CategoryORM
        result = await session.execute(
            select(CategoryORM).order_by(CategoryORM.depth, CategoryORM.name)
        )
        return [_category_to_domain(r) for r in result.scalars().all()]

    @staticmethod
    async def get_category(
        session: AsyncSession, category_id: uuid.UUID
    ) -> Optional[object]:
        from district_console.infrastructure.orm import CategoryORM
        result = await session.execute(
            select(CategoryORM).where(CategoryORM.id == str(category_id))
        )
        orm = result.scalar_one_or_none()
        return _category_to_domain(orm) if orm else None

    @staticmethod
    async def get_category_by_slug(
        session: AsyncSession, path_slug: str
    ) -> Optional[object]:
        from district_console.infrastructure.orm import CategoryORM
        result = await session.execute(
            select(CategoryORM).where(CategoryORM.path_slug == path_slug)
        )
        orm = result.scalar_one_or_none()
        return _category_to_domain(orm) if orm else None

    @staticmethod
    async def save_category(session: AsyncSession, category: object) -> object:
        from district_console.infrastructure.orm import CategoryORM
        from district_console.domain.entities.resource_metadata import Category
        assert isinstance(category, Category)
        result = await session.execute(
            select(CategoryORM).where(CategoryORM.id == str(category.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = CategoryORM(
                id=str(category.id),
                name=category.name,
                depth=category.depth,
                path_slug=category.path_slug,
                parent_id=str(category.parent_id) if category.parent_id else None,
                is_active=category.is_active,
            )
            session.add(orm)
        else:
            orm.name = category.name
            orm.depth = category.depth
            orm.path_slug = category.path_slug
            orm.parent_id = str(category.parent_id) if category.parent_id else None
            orm.is_active = category.is_active
        await session.flush()
        return category

    @staticmethod
    async def list_validation_rules(
        session: AsyncSession, field: Optional[str] = None
    ) -> list:
        from district_console.infrastructure.orm import TaxonomyValidationRuleORM
        stmt = select(TaxonomyValidationRuleORM)
        if field:
            stmt = stmt.where(TaxonomyValidationRuleORM.field == field)
        result = await session.execute(stmt.order_by(TaxonomyValidationRuleORM.field))
        return [_tax_rule_to_domain(r) for r in result.scalars().all()]

    @staticmethod
    async def get_rule_by_id(
        session: AsyncSession, rule_id: uuid.UUID
    ) -> Optional[object]:
        from district_console.infrastructure.orm import TaxonomyValidationRuleORM
        result = await session.execute(
            select(TaxonomyValidationRuleORM).where(
                TaxonomyValidationRuleORM.id == str(rule_id)
            )
        )
        orm = result.scalar_one_or_none()
        return _tax_rule_to_domain(orm) if orm else None

    @staticmethod
    async def save_rule(session: AsyncSession, rule: object) -> object:
        from district_console.infrastructure.orm import TaxonomyValidationRuleORM
        from district_console.domain.entities.resource_metadata import TaxonomyValidationRule
        assert isinstance(rule, TaxonomyValidationRule)
        result = await session.execute(
            select(TaxonomyValidationRuleORM).where(
                TaxonomyValidationRuleORM.id == str(rule.id)
            )
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = TaxonomyValidationRuleORM(
                id=str(rule.id),
                field=rule.field,
                rule_type=rule.rule_type,
                rule_value=rule.rule_value,
                is_active=rule.is_active,
                description=rule.description,
            )
            session.add(orm)
        else:
            orm.field = rule.field
            orm.rule_type = rule.rule_type
            orm.rule_value = rule.rule_value
            orm.is_active = rule.is_active
            orm.description = rule.description
        await session.flush()
        return rule

    @staticmethod
    async def delete_rule(session: AsyncSession, rule_id: uuid.UUID) -> None:
        from district_console.infrastructure.orm import TaxonomyValidationRuleORM
        result = await session.execute(
            select(TaxonomyValidationRuleORM).where(
                TaxonomyValidationRuleORM.id == str(rule_id)
            )
        )
        orm = result.scalar_one_or_none()
        if orm is not None:
            await session.delete(orm)
            await session.flush()


def _category_to_domain(orm: object) -> object:
    from district_console.infrastructure.orm import CategoryORM
    from district_console.domain.entities.resource_metadata import Category
    assert isinstance(orm, CategoryORM)
    return Category(
        id=uuid.UUID(orm.id),
        name=orm.name,
        depth=orm.depth,
        path_slug=orm.path_slug,
        parent_id=uuid.UUID(orm.parent_id) if orm.parent_id else None,
        is_active=orm.is_active,
    )


def _tax_rule_to_domain(orm: object) -> object:
    from district_console.infrastructure.orm import TaxonomyValidationRuleORM
    from district_console.domain.entities.resource_metadata import TaxonomyValidationRule
    assert isinstance(orm, TaxonomyValidationRuleORM)
    return TaxonomyValidationRule(
        id=uuid.UUID(orm.id),
        field=orm.field,
        rule_type=orm.rule_type,
        rule_value=orm.rule_value,
        is_active=orm.is_active,
        description=orm.description,
    )


# ---------------------------------------------------------------------------
# IntegrationRepository
# ---------------------------------------------------------------------------

class IntegrationRepository:
    """Manage integration clients, HMAC keys, and outbound events."""

    # -- IntegrationClient --

    @staticmethod
    async def list_clients(session: AsyncSession) -> list:
        from district_console.infrastructure.orm import IntegrationClientORM
        result = await session.execute(
            select(IntegrationClientORM).order_by(IntegrationClientORM.name)
        )
        return [_integration_client_to_domain(r) for r in result.scalars().all()]

    @staticmethod
    async def get_client(session: AsyncSession, client_id: uuid.UUID) -> Optional[object]:
        from district_console.infrastructure.orm import IntegrationClientORM
        result = await session.execute(
            select(IntegrationClientORM).where(
                IntegrationClientORM.id == str(client_id)
            )
        )
        orm = result.scalar_one_or_none()
        return _integration_client_to_domain(orm) if orm else None

    @staticmethod
    async def save_client(session: AsyncSession, client: object) -> object:
        from district_console.infrastructure.orm import IntegrationClientORM
        from district_console.domain.entities.integration import IntegrationClient
        assert isinstance(client, IntegrationClient)
        result = await session.execute(
            select(IntegrationClientORM).where(
                IntegrationClientORM.id == str(client.id)
            )
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = IntegrationClientORM(
                id=str(client.id),
                name=client.name,
                description=client.description,
                is_active=client.is_active,
                created_at=client.created_at.isoformat(),
            )
            session.add(orm)
        else:
            orm.name = client.name
            orm.description = client.description
            orm.is_active = client.is_active
        await session.flush()
        return client

    # -- HmacKey --

    @staticmethod
    async def list_keys(session: AsyncSession, client_id: uuid.UUID) -> list:
        from district_console.infrastructure.orm import HmacKeyORM
        result = await session.execute(
            select(HmacKeyORM).where(HmacKeyORM.client_id == str(client_id))
            .order_by(HmacKeyORM.created_at)
        )
        return [_hmac_key_to_domain(r) for r in result.scalars().all()]

    @staticmethod
    async def get_active_key_for_client(
        session: AsyncSession, client_id: uuid.UUID
    ) -> Optional[object]:
        from district_console.infrastructure.orm import HmacKeyORM
        result = await session.execute(
            select(HmacKeyORM).where(
                HmacKeyORM.client_id == str(client_id),
                HmacKeyORM.is_active == True,  # noqa: E712
                HmacKeyORM.is_next == False,  # noqa: E712
            )
        )
        orm = result.scalar_one_or_none()
        return _hmac_key_to_domain(orm) if orm else None

    @staticmethod
    async def get_next_key_for_client(
        session: AsyncSession, client_id: uuid.UUID
    ) -> Optional[object]:
        from district_console.infrastructure.orm import HmacKeyORM
        result = await session.execute(
            select(HmacKeyORM).where(
                HmacKeyORM.client_id == str(client_id),
                HmacKeyORM.is_next == True,  # noqa: E712
            )
        )
        orm = result.scalar_one_or_none()
        return _hmac_key_to_domain(orm) if orm else None

    @staticmethod
    async def save_key(session: AsyncSession, key: object) -> object:
        from district_console.infrastructure.orm import HmacKeyORM
        from district_console.domain.entities.integration import HmacKey
        assert isinstance(key, HmacKey)
        result = await session.execute(
            select(HmacKeyORM).where(HmacKeyORM.id == str(key.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = HmacKeyORM(
                id=str(key.id),
                client_id=str(key.client_id),
                key_encrypted=key.key_encrypted,
                created_at=key.created_at.isoformat(),
                expires_at=key.expires_at.isoformat(),
                is_active=key.is_active,
                is_next=key.is_next,
            )
            session.add(orm)
        else:
            orm.is_active = key.is_active
            orm.is_next = key.is_next
            orm.expires_at = key.expires_at.isoformat()
        await session.flush()
        return key

    # -- OutboundEvent --

    @staticmethod
    async def list_events(
        session: AsyncSession,
        client_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list, int]:
        from district_console.infrastructure.orm import OutboundEventORM
        stmt = select(OutboundEventORM)
        if client_id is not None:
            stmt = stmt.where(OutboundEventORM.client_id == str(client_id))
        if status is not None:
            stmt = stmt.where(OutboundEventORM.status == status)
        count_result = await session.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total = int(count_result.scalar_one())
        result = await session.execute(
            stmt.order_by(OutboundEventORM.created_at.desc()).offset(offset).limit(limit)
        )
        return [_outbound_event_to_domain(r) for r in result.scalars().all()], total

    @staticmethod
    async def get_event(session: AsyncSession, event_id: uuid.UUID) -> Optional[object]:
        from district_console.infrastructure.orm import OutboundEventORM
        result = await session.execute(
            select(OutboundEventORM).where(OutboundEventORM.id == str(event_id))
        )
        orm = result.scalar_one_or_none()
        return _outbound_event_to_domain(orm) if orm else None

    @staticmethod
    async def get_pending_events(session: AsyncSession) -> list:
        from district_console.infrastructure.orm import OutboundEventORM
        result = await session.execute(
            select(OutboundEventORM).where(OutboundEventORM.status == "PENDING")
            .order_by(OutboundEventORM.created_at)
        )
        return [_outbound_event_to_domain(r) for r in result.scalars().all()]

    @staticmethod
    async def save_event(session: AsyncSession, event: object) -> object:
        from district_console.infrastructure.orm import OutboundEventORM
        from district_console.domain.entities.integration import OutboundEvent
        assert isinstance(event, OutboundEvent)
        result = await session.execute(
            select(OutboundEventORM).where(OutboundEventORM.id == str(event.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = OutboundEventORM(
                id=str(event.id),
                client_id=str(event.client_id),
                event_type=event.event_type,
                payload_json=event.payload_json,
                status=event.status,
                created_at=event.created_at.isoformat(),
                delivered_at=_fmt_dt(event.delivered_at),
                retry_count=event.retry_count,
                last_error=event.last_error,
            )
            session.add(orm)
        else:
            orm.status = event.status
            orm.delivered_at = _fmt_dt(event.delivered_at)
            orm.retry_count = event.retry_count
            orm.last_error = event.last_error
        await session.flush()
        return event


def _integration_client_to_domain(orm: object) -> object:
    from district_console.infrastructure.orm import IntegrationClientORM
    from district_console.domain.entities.integration import IntegrationClient
    assert isinstance(orm, IntegrationClientORM)
    return IntegrationClient(
        id=uuid.UUID(orm.id),
        name=orm.name,
        description=orm.description,
        is_active=orm.is_active,
        created_at=datetime.fromisoformat(orm.created_at),
    )


def _hmac_key_to_domain(orm: object) -> object:
    from district_console.infrastructure.orm import HmacKeyORM
    from district_console.domain.entities.integration import HmacKey
    assert isinstance(orm, HmacKeyORM)
    return HmacKey(
        id=uuid.UUID(orm.id),
        client_id=uuid.UUID(orm.client_id),
        key_encrypted=orm.key_encrypted,
        created_at=datetime.fromisoformat(orm.created_at),
        expires_at=datetime.fromisoformat(orm.expires_at),
        is_active=orm.is_active,
        is_next=orm.is_next,
    )


def _outbound_event_to_domain(orm: object) -> object:
    from district_console.infrastructure.orm import OutboundEventORM
    from district_console.domain.entities.integration import OutboundEvent
    assert isinstance(orm, OutboundEventORM)
    return OutboundEvent(
        id=uuid.UUID(orm.id),
        client_id=uuid.UUID(orm.client_id),
        event_type=orm.event_type,
        payload_json=orm.payload_json,
        status=orm.status,
        created_at=datetime.fromisoformat(orm.created_at),
        delivered_at=_parse_dt(orm.delivered_at),
        retry_count=orm.retry_count,
        last_error=orm.last_error,
    )


# ---------------------------------------------------------------------------
# UpdatePackageRepository
# ---------------------------------------------------------------------------

class UpdatePackageRepository:
    """Manage offline update package records."""

    @staticmethod
    async def get_by_id(
        session: AsyncSession, package_id: uuid.UUID
    ) -> Optional[object]:
        from district_console.infrastructure.orm import UpdatePackageORM
        result = await session.execute(
            select(UpdatePackageORM).where(UpdatePackageORM.id == str(package_id))
        )
        orm = result.scalar_one_or_none()
        return _update_package_to_domain(orm) if orm else None

    @staticmethod
    async def get_applied(session: AsyncSession) -> Optional[object]:
        from district_console.infrastructure.orm import UpdatePackageORM
        result = await session.execute(
            select(UpdatePackageORM).where(UpdatePackageORM.status == "APPLIED")
        )
        orm = result.scalar_one_or_none()
        return _update_package_to_domain(orm) if orm else None

    @staticmethod
    async def get_by_version(session: AsyncSession, version: str) -> Optional[object]:
        from district_console.infrastructure.orm import UpdatePackageORM
        result = await session.execute(
            select(UpdatePackageORM).where(UpdatePackageORM.version == version)
        )
        orm = result.scalar_one_or_none()
        return _update_package_to_domain(orm) if orm else None

    @staticmethod
    async def save(session: AsyncSession, package: object) -> object:
        from district_console.infrastructure.orm import UpdatePackageORM
        from district_console.domain.entities.update import UpdatePackage
        assert isinstance(package, UpdatePackage)
        result = await session.execute(
            select(UpdatePackageORM).where(UpdatePackageORM.id == str(package.id))
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = UpdatePackageORM(
                id=str(package.id),
                version=package.version,
                manifest_json=package.manifest_json,
                file_path=package.file_path,
                file_hash=package.file_hash,
                imported_at=package.imported_at.isoformat(),
                imported_by=str(package.imported_by),
                status=package.status.value,
                prior_version_ref=str(package.prior_version_ref) if package.prior_version_ref else None,
            )
            session.add(orm)
        else:
            orm.status = package.status.value
        await session.flush()
        return package

    @staticmethod
    async def list(
        session: AsyncSession, offset: int = 0, limit: int = 20
    ) -> tuple[list, int]:
        from district_console.infrastructure.orm import UpdatePackageORM
        count_result = await session.execute(select(UpdatePackageORM.id))
        total = len(count_result.all())
        result = await session.execute(
            select(UpdatePackageORM)
            .order_by(UpdatePackageORM.imported_at.desc())
            .offset(offset).limit(limit)
        )
        return [_update_package_to_domain(r) for r in result.scalars().all()], total


def _update_package_to_domain(orm: object) -> object:
    from district_console.infrastructure.orm import UpdatePackageORM
    from district_console.domain.entities.update import UpdatePackage
    from district_console.domain.enums import UpdateStatus
    assert isinstance(orm, UpdatePackageORM)
    return UpdatePackage(
        id=uuid.UUID(orm.id),
        version=orm.version,
        manifest_json=orm.manifest_json,
        file_path=orm.file_path,
        file_hash=orm.file_hash,
        imported_at=datetime.fromisoformat(orm.imported_at),
        imported_by=uuid.UUID(orm.imported_by),
        status=UpdateStatus(orm.status),
        prior_version_ref=uuid.UUID(orm.prior_version_ref) if orm.prior_version_ref else None,
    )


# ---------------------------------------------------------------------------
# AuditQueryRepository
# ---------------------------------------------------------------------------

class AuditQueryRepository:
    """Read-only query interface for the append-only audit_events table."""

    @staticmethod
    async def list_events(
        session: AsyncSession,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        action: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AuditEvent], int]:
        stmt = select(AuditEventORM)
        if entity_type:
            stmt = stmt.where(AuditEventORM.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(AuditEventORM.entity_id == entity_id)
        if actor_id:
            stmt = stmt.where(AuditEventORM.actor_id == actor_id)
        if action:
            stmt = stmt.where(AuditEventORM.action == action)
        if date_from:
            stmt = stmt.where(AuditEventORM.timestamp >= date_from.isoformat())
        if date_to:
            stmt = stmt.where(AuditEventORM.timestamp <= date_to.isoformat())
        count_result = await session.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total = int(count_result.scalar_one())
        result = await session.execute(
            stmt.order_by(AuditEventORM.timestamp.desc()).offset(offset).limit(limit)
        )
        return [_audit_event_to_domain(r) for r in result.scalars().all()], total

    @staticmethod
    async def list_security_events(
        session: AsyncSession, offset: int = 0, limit: int = 50
    ) -> tuple[list[AuditEvent], int]:
        security_actions = {"LOGIN", "LOGIN_FAILED", "ACCOUNT_LOCKED", "LOGOUT", "KEY_ROTATION"}
        stmt = select(AuditEventORM).where(
            AuditEventORM.action.in_(security_actions)
        )
        count_result = await session.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total = int(count_result.scalar_one())
        result = await session.execute(
            stmt.order_by(AuditEventORM.timestamp.desc()).offset(offset).limit(limit)
        )
        return [_audit_event_to_domain(r) for r in result.scalars().all()], total


def _audit_event_to_domain(orm: AuditEventORM) -> AuditEvent:
    return AuditEvent(
        id=uuid.UUID(orm.id),
        entity_type=orm.entity_type,
        entity_id=uuid.UUID(orm.entity_id) if len(orm.entity_id) == 36 else uuid.UUID(int=0),
        action=orm.action,
        actor_id=uuid.UUID(orm.actor_id),
        timestamp=datetime.fromisoformat(orm.timestamp),
        metadata=json.loads(orm.metadata_json),
    )
