"""
SQLAlchemy ORM mapped classes for all 39 District Console tables.

Column types mirror the Alembic migration (0001_initial_schema.py) exactly:
- UUIDs stored as String (TEXT in SQLite)
- Datetimes stored as String (ISO-8601 TEXT in SQLite)
- Decimal values (unit_cost, variance_value, quantity_after) stored as String

ORM objects are internal to the infrastructure layer. Repositories convert
between ORM objects and domain dataclasses — SQLAlchemy is never imported in
the domain layer.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, mapped_column, MappedColumn


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# ---------------------------------------------------------------------------
# RBAC: users, roles, permissions
# ---------------------------------------------------------------------------

class UserORM(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "failed_attempts >= 0 AND failed_attempts <= 10",
            name="ck_users_failed_attempts",
        ),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    username: MappedColumn[str] = mapped_column(String, nullable=False, unique=True)
    password_hash: MappedColumn[str] = mapped_column(String, nullable=False)
    is_active: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=True)
    failed_attempts: MappedColumn[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: MappedColumn[str | None] = mapped_column(String, nullable=True)
    created_at: MappedColumn[str] = mapped_column(String, nullable=False)
    updated_at: MappedColumn[str] = mapped_column(String, nullable=False)


class RoleORM(Base):
    __tablename__ = "roles"
    __table_args__ = (
        CheckConstraint(
            "role_type IN ('ADMINISTRATOR','LIBRARIAN','TEACHER','COUNSELOR','REVIEWER')",
            name="ck_roles_role_type",
        ),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    role_type: MappedColumn[str] = mapped_column(String, nullable=False, unique=True)
    display_name: MappedColumn[str] = mapped_column(String, nullable=False)


class PermissionORM(Base):
    __tablename__ = "permissions"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    name: MappedColumn[str] = mapped_column(String, nullable=False, unique=True)
    resource_name: MappedColumn[str] = mapped_column(String, nullable=False)
    action: MappedColumn[str] = mapped_column(String, nullable=False)


class RolePermissionORM(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        PrimaryKeyConstraint("role_id", "permission_id"),
    )

    role_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("roles.id"), nullable=False
    )
    permission_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("permissions.id"), nullable=False
    )


class UserRoleORM(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "role_id"),
    )

    user_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    role_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("roles.id"), nullable=False
    )
    assigned_by: MappedColumn[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    assigned_at: MappedColumn[str] = mapped_column(String, nullable=False)


# ---------------------------------------------------------------------------
# Scope hierarchy
# ---------------------------------------------------------------------------

class SchoolORM(Base):
    __tablename__ = "schools"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    name: MappedColumn[str] = mapped_column(String, nullable=False)
    district_code: MappedColumn[str] = mapped_column(String, nullable=False)
    is_active: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=True)


class DepartmentORM(Base):
    __tablename__ = "departments"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    school_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("schools.id"), nullable=False
    )
    name: MappedColumn[str] = mapped_column(String, nullable=False)
    is_active: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=True)


class ClassORM(Base):
    __tablename__ = "classes"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    department_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("departments.id"), nullable=False
    )
    name: MappedColumn[str] = mapped_column(String, nullable=False)
    teacher_id: MappedColumn[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    is_active: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=True)


class IndividualORM(Base):
    __tablename__ = "individuals"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    class_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("classes.id"), nullable=False
    )
    display_name: MappedColumn[str] = mapped_column(String, nullable=False)
    user_id: MappedColumn[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )


class ScopeAssignmentORM(Base):
    __tablename__ = "scope_assignments"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('SCHOOL','DEPARTMENT','CLASS','INDIVIDUAL')",
            name="ck_scope_assignments_scope_type",
        ),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    user_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    scope_type: MappedColumn[str] = mapped_column(String, nullable=False)
    scope_ref_id: MappedColumn[str] = mapped_column(String, nullable=False)
    granted_by: MappedColumn[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    granted_at: MappedColumn[str] = mapped_column(String, nullable=False)


# ---------------------------------------------------------------------------
# Resource library
# ---------------------------------------------------------------------------

class ResourceORM(Base):
    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint(
            "resource_type IN ('BOOK','PICTURE_BOOK','ARTICLE','AUDIO')",
            name="ck_resources_resource_type",
        ),
        CheckConstraint(
            "status IN ('DRAFT','IN_REVIEW','PUBLISHED','UNPUBLISHED')",
            name="ck_resources_status",
        ),
        CheckConstraint(
            "owner_scope_type IS NULL OR owner_scope_type IN ('SCHOOL','DEPARTMENT','CLASS','INDIVIDUAL')",
            name="ck_resources_owner_scope_type",
        ),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    title: MappedColumn[str] = mapped_column(String, nullable=False)
    resource_type: MappedColumn[str] = mapped_column(String, nullable=False, index=True)
    status: MappedColumn[str] = mapped_column(
        String, nullable=False, default="DRAFT", index=True
    )
    file_fingerprint: MappedColumn[str] = mapped_column(String, nullable=False)
    isbn: MappedColumn[str | None] = mapped_column(String, nullable=True)
    dedup_key: MappedColumn[str] = mapped_column(String, nullable=False, unique=True)
    created_by: MappedColumn[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    created_at: MappedColumn[str] = mapped_column(String, nullable=False)
    updated_at: MappedColumn[str] = mapped_column(String, nullable=False)
    owner_scope_type: MappedColumn[str | None] = mapped_column(String, nullable=True)
    owner_scope_ref_id: MappedColumn[str | None] = mapped_column(String, nullable=True)


class ResourceRevisionORM(Base):
    __tablename__ = "resource_revisions"
    __table_args__ = (
        UniqueConstraint(
            "resource_id", "revision_number",
            name="uq_resource_revisions_resource_revision",
        ),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    resource_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("resources.id"), nullable=False, index=True
    )
    revision_number: MappedColumn[int] = mapped_column(Integer, nullable=False)
    file_path: MappedColumn[str] = mapped_column(String, nullable=False)
    file_hash: MappedColumn[str] = mapped_column(String, nullable=False)
    file_size: MappedColumn[int] = mapped_column(Integer, nullable=False)
    imported_by: MappedColumn[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    created_at: MappedColumn[str] = mapped_column(String, nullable=False)


class CategoryORM(Base):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("depth >= 0", name="ck_categories_depth"),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    name: MappedColumn[str] = mapped_column(String, nullable=False)
    depth: MappedColumn[int] = mapped_column(Integer, nullable=False, default=0)
    path_slug: MappedColumn[str] = mapped_column(String, nullable=False, unique=True)
    parent_id: MappedColumn[str | None] = mapped_column(
        String, ForeignKey("categories.id"), nullable=True
    )
    is_active: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=True)


class ResourceMetadataORM(Base):
    __tablename__ = "resource_metadata"
    __table_args__ = (
        CheckConstraint(
            "timeliness IS NULL OR timeliness IN ('EVERGREEN','CURRENT','ARCHIVED')",
            name="ck_resource_metadata_timeliness",
        ),
        CheckConstraint(
            "age_range_min IS NULL OR age_range_min >= 0",
            name="ck_resource_metadata_age_min",
        ),
        CheckConstraint(
            "age_range_max IS NULL OR age_range_max <= 18",
            name="ck_resource_metadata_age_max",
        ),
        CheckConstraint(
            "age_range_min IS NULL OR age_range_max IS NULL OR age_range_min <= age_range_max",
            name="ck_resource_metadata_age_order",
        ),
    )

    resource_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("resources.id"), primary_key=True
    )
    timeliness: MappedColumn[str | None] = mapped_column(String, nullable=True)
    source: MappedColumn[str | None] = mapped_column(String, nullable=True)
    copyright: MappedColumn[str | None] = mapped_column(String, nullable=True)
    theme: MappedColumn[str | None] = mapped_column(String, nullable=True)
    difficulty_level: MappedColumn[str | None] = mapped_column(String, nullable=True)
    age_range_min: MappedColumn[int | None] = mapped_column(Integer, nullable=True)
    age_range_max: MappedColumn[int | None] = mapped_column(Integer, nullable=True)


class ResourceCategoryORM(Base):
    __tablename__ = "resource_categories"
    __table_args__ = (
        PrimaryKeyConstraint("resource_id", "category_id"),
    )

    resource_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("resources.id"), nullable=False
    )
    category_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("categories.id"), nullable=False
    )


class ResourceKeywordORM(Base):
    __tablename__ = "resource_keywords"
    __table_args__ = (
        PrimaryKeyConstraint("resource_id", "keyword"),
    )

    resource_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("resources.id"), nullable=False
    )
    keyword: MappedColumn[str] = mapped_column(String, nullable=False)


class ReviewTaskORM(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        CheckConstraint(
            "decision IS NULL OR decision IN ('APPROVED','REJECTED','NEEDS_REVISION')",
            name="ck_review_tasks_decision",
        ),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    resource_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("resources.id"), nullable=False, index=True
    )
    assigned_to: MappedColumn[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    decision: MappedColumn[str | None] = mapped_column(String, nullable=True)
    notes: MappedColumn[str] = mapped_column(String, nullable=False, default="")
    created_at: MappedColumn[str] = mapped_column(String, nullable=False)
    completed_at: MappedColumn[str | None] = mapped_column(String, nullable=True)


class AuditEventORM(Base):
    # APPEND-ONLY: this table must never receive UPDATE or DELETE statements.
    __tablename__ = "audit_events"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    entity_type: MappedColumn[str] = mapped_column(String, nullable=False, index=True)
    entity_id: MappedColumn[str] = mapped_column(String, nullable=False)
    action: MappedColumn[str] = mapped_column(String, nullable=False)
    actor_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    timestamp: MappedColumn[str] = mapped_column(String, nullable=False, index=True)
    metadata_json: MappedColumn[str] = mapped_column(String, nullable=False, default="{}")


class TaxonomyValidationRuleORM(Base):
    __tablename__ = "taxonomy_validation_rules"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    field: MappedColumn[str] = mapped_column(String, nullable=False)
    rule_type: MappedColumn[str] = mapped_column(String, nullable=False)
    rule_value: MappedColumn[str] = mapped_column(String, nullable=False)
    is_active: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: MappedColumn[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

class InventoryItemORM(Base):
    __tablename__ = "inventory_items"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    sku: MappedColumn[str] = mapped_column(String, nullable=False, unique=True)
    name: MappedColumn[str] = mapped_column(String, nullable=False)
    description: MappedColumn[str] = mapped_column(String, nullable=False, default="")
    unit_cost: MappedColumn[str] = mapped_column(String, nullable=False)  # TEXT for Decimal
    created_by: MappedColumn[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    created_at: MappedColumn[str] = mapped_column(String, nullable=False)


class WarehouseORM(Base):
    __tablename__ = "warehouses"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    name: MappedColumn[str] = mapped_column(String, nullable=False)
    school_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("schools.id"), nullable=False
    )
    address: MappedColumn[str] = mapped_column(String, nullable=False, default="")
    is_active: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=True)


class LocationORM(Base):
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "bin_label", name="uq_locations_warehouse_bin"),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    warehouse_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("warehouses.id"), nullable=False, index=True
    )
    zone: MappedColumn[str] = mapped_column(String, nullable=False)
    aisle: MappedColumn[str] = mapped_column(String, nullable=False)
    bin_label: MappedColumn[str] = mapped_column(String, nullable=False)
    is_active: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=True)


class StockBalanceORM(Base):
    __tablename__ = "stock_balances"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_stock_balances_quantity"),
        CheckConstraint(
            "status IN ('AVAILABLE','RESERVED','QUARANTINE','DISPOSED','FROZEN')",
            name="ck_stock_balances_status",
        ),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    item_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("inventory_items.id"), nullable=False
    )
    location_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("locations.id"), nullable=False
    )
    batch_id: MappedColumn[str | None] = mapped_column(String, nullable=True)
    serial_id: MappedColumn[str | None] = mapped_column(String, nullable=True)
    status: MappedColumn[str] = mapped_column(
        String, nullable=False, default="AVAILABLE"
    )
    quantity: MappedColumn[int] = mapped_column(Integer, nullable=False, default=0)
    is_frozen: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=False)
    freeze_reason: MappedColumn[str | None] = mapped_column(String, nullable=True)
    frozen_by: MappedColumn[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    frozen_at: MappedColumn[str | None] = mapped_column(String, nullable=True)


class RecordLockORM(Base):
    __tablename__ = "record_locks"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", name="uq_record_locks_entity"),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    entity_type: MappedColumn[str] = mapped_column(String, nullable=False)
    entity_id: MappedColumn[str] = mapped_column(String, nullable=False)
    locked_by: MappedColumn[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    locked_at: MappedColumn[str] = mapped_column(String, nullable=False)
    expires_at: MappedColumn[str] = mapped_column(String, nullable=False)
    nonce: MappedColumn[str] = mapped_column(String, nullable=False)


class LedgerEntryORM(Base):
    # APPEND-ONLY: this table must never receive UPDATE or DELETE statements.
    # Corrections are represented as new CORRECTION entries with reversal_of_id set.
    # The is_reversed flag on the original entry may be updated to True ONLY
    # when a CORRECTION entry references it — no other column may be updated.
    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint(
            "quantity_after >= 0", name="ck_ledger_entries_quantity_after"
        ),
        CheckConstraint(
            "entry_type IN ('RECEIPT','ADJUSTMENT','RELOCATION','CORRECTION','COUNT_CLOSE')",
            name="ck_ledger_entries_entry_type",
        ),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    item_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("inventory_items.id"), nullable=False
    )
    location_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("locations.id"), nullable=False
    )
    entry_type: MappedColumn[str] = mapped_column(String, nullable=False)
    quantity_delta: MappedColumn[int] = mapped_column(Integer, nullable=False)
    quantity_after: MappedColumn[int] = mapped_column(Integer, nullable=False)
    operator_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    reason_code: MappedColumn[str] = mapped_column(String, nullable=False)
    created_at: MappedColumn[str] = mapped_column(String, nullable=False, index=True)
    reference_id: MappedColumn[str | None] = mapped_column(String, nullable=True)
    is_reversed: MappedColumn[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    reversal_of_id: MappedColumn[str | None] = mapped_column(
        String, ForeignKey("ledger_entries.id"), nullable=True
    )


# ---------------------------------------------------------------------------
# Count sessions
# ---------------------------------------------------------------------------

class CountSessionORM(Base):
    __tablename__ = "count_sessions"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('OPEN','BLIND','CYCLE')", name="ck_count_sessions_mode"
        ),
        CheckConstraint(
            "status IN ('ACTIVE','CLOSED','EXPIRED','APPROVED')",
            name="ck_count_sessions_status",
        ),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    mode: MappedColumn[str] = mapped_column(String, nullable=False)
    status: MappedColumn[str] = mapped_column(String, nullable=False, default="ACTIVE")
    warehouse_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("warehouses.id"), nullable=False
    )
    created_by: MappedColumn[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    created_at: MappedColumn[str] = mapped_column(String, nullable=False)
    last_activity_at: MappedColumn[str] = mapped_column(String, nullable=False)
    closed_at: MappedColumn[str | None] = mapped_column(String, nullable=True)
    approved_by: MappedColumn[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    approved_at: MappedColumn[str | None] = mapped_column(String, nullable=True)


class CountLineORM(Base):
    __tablename__ = "count_lines"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    session_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("count_sessions.id"), nullable=False, index=True
    )
    item_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("inventory_items.id"), nullable=False
    )
    location_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("locations.id"), nullable=False
    )
    expected_qty: MappedColumn[int] = mapped_column(Integer, nullable=False)
    counted_qty: MappedColumn[int] = mapped_column(Integer, nullable=False)
    variance_qty: MappedColumn[int] = mapped_column(Integer, nullable=False)
    variance_value: MappedColumn[str] = mapped_column(String, nullable=False)  # TEXT for Decimal
    requires_approval: MappedColumn[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    reason_code: MappedColumn[str | None] = mapped_column(String, nullable=True)


class CountApprovalORM(Base):
    __tablename__ = "count_approvals"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('APPROVED','REJECTED','NEEDS_REVISION')",
            name="ck_count_approvals_decision",
        ),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    session_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("count_sessions.id"), nullable=False
    )
    reviewed_by: MappedColumn[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    decision: MappedColumn[str] = mapped_column(String, nullable=False)
    notes: MappedColumn[str] = mapped_column(String, nullable=False)
    decided_at: MappedColumn[str] = mapped_column(String, nullable=False)


# ---------------------------------------------------------------------------
# Relocations
# ---------------------------------------------------------------------------

class RelocationORM(Base):
    __tablename__ = "relocations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_relocations_quantity"),
        CheckConstraint(
            "from_location_id != to_location_id",
            name="ck_relocations_distinct_locations",
        ),
        CheckConstraint(
            "device_source IN ('MANUAL','USB_SCANNER')",
            name="ck_relocations_device_source",
        ),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    item_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("inventory_items.id"), nullable=False
    )
    from_location_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("locations.id"), nullable=False
    )
    to_location_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("locations.id"), nullable=False
    )
    quantity: MappedColumn[int] = mapped_column(Integer, nullable=False)
    operator_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    device_source: MappedColumn[str] = mapped_column(String, nullable=False)
    created_at: MappedColumn[str] = mapped_column(String, nullable=False)
    ledger_debit_entry_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("ledger_entries.id"), nullable=False
    )
    ledger_credit_entry_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("ledger_entries.id"), nullable=False
    )


# ---------------------------------------------------------------------------
# Configuration center
# ---------------------------------------------------------------------------

class ConfigDictionaryORM(Base):
    __tablename__ = "config_dictionary"
    __table_args__ = (
        UniqueConstraint(
            "category", "key", name="uq_config_dictionary_category_key"
        ),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    category: MappedColumn[str] = mapped_column(String, nullable=False)
    key: MappedColumn[str] = mapped_column(String, nullable=False)
    value: MappedColumn[str] = mapped_column(String, nullable=False)
    description: MappedColumn[str] = mapped_column(String, nullable=False, default="")
    is_system: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: MappedColumn[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    updated_at: MappedColumn[str | None] = mapped_column(String, nullable=True)


class WorkflowNodeORM(Base):
    __tablename__ = "workflow_nodes"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    workflow_name: MappedColumn[str] = mapped_column(String, nullable=False, index=True)
    from_state: MappedColumn[str] = mapped_column(String, nullable=False)
    to_state: MappedColumn[str] = mapped_column(String, nullable=False)
    required_role: MappedColumn[str] = mapped_column(String, nullable=False)
    condition_json: MappedColumn[str | None] = mapped_column(String, nullable=True)


class NotificationTemplateORM(Base):
    __tablename__ = "notification_templates"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    name: MappedColumn[str] = mapped_column(String, nullable=False, unique=True)
    event_type: MappedColumn[str] = mapped_column(String, nullable=False)
    subject_template: MappedColumn[str] = mapped_column(String, nullable=False)
    body_template: MappedColumn[str] = mapped_column(String, nullable=False)
    is_active: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=True)


class DistrictDescriptorORM(Base):
    __tablename__ = "district_descriptors"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    key: MappedColumn[str] = mapped_column(String, nullable=False, unique=True)
    value: MappedColumn[str] = mapped_column(String, nullable=False)
    description: MappedColumn[str] = mapped_column(String, nullable=False, default="")
    region: MappedColumn[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------

class IntegrationClientORM(Base):
    __tablename__ = "integration_clients"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    name: MappedColumn[str] = mapped_column(String, nullable=False, unique=True)
    description: MappedColumn[str] = mapped_column(String, nullable=False, default="")
    is_active: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: MappedColumn[str] = mapped_column(String, nullable=False)


class HmacKeyORM(Base):
    __tablename__ = "hmac_keys"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    client_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("integration_clients.id"), nullable=False, index=True
    )
    key_encrypted: MappedColumn[str] = mapped_column(String, nullable=False)
    created_at: MappedColumn[str] = mapped_column(String, nullable=False)
    expires_at: MappedColumn[str] = mapped_column(String, nullable=False)
    is_active: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_next: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=False)


class OutboundEventORM(Base):
    __tablename__ = "outbound_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','DELIVERED','FAILED')",
            name="ck_outbound_events_status",
        ),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    client_id: MappedColumn[str] = mapped_column(
        String, ForeignKey("integration_clients.id"), nullable=False
    )
    event_type: MappedColumn[str] = mapped_column(String, nullable=False)
    payload_json: MappedColumn[str] = mapped_column(String, nullable=False)
    status: MappedColumn[str] = mapped_column(
        String, nullable=False, default="PENDING", index=True
    )
    created_at: MappedColumn[str] = mapped_column(String, nullable=False)
    delivered_at: MappedColumn[str | None] = mapped_column(String, nullable=True)
    retry_count: MappedColumn[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: MappedColumn[str | None] = mapped_column(String, nullable=True)


class RateLimitStateORM(Base):
    __tablename__ = "rate_limit_state"
    __table_args__ = (
        CheckConstraint("request_count >= 0", name="ck_rate_limit_state_count"),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    client_id: MappedColumn[str] = mapped_column(
        String,
        ForeignKey("integration_clients.id"),
        nullable=False,
        unique=True,
    )
    window_start: MappedColumn[str] = mapped_column(String, nullable=False)
    request_count: MappedColumn[int] = mapped_column(Integer, nullable=False, default=0)


# ---------------------------------------------------------------------------
# Checkpoint / recovery
# ---------------------------------------------------------------------------

class CheckpointRecordORM(Base):
    __tablename__ = "checkpoint_records"
    __table_args__ = (
        CheckConstraint(
            "job_type IN ('import','count','approval','scheduled')",
            name="ck_checkpoint_records_job_type",
        ),
        CheckConstraint(
            "status IN ('ACTIVE','COMPLETED','FAILED','ABANDONED')",
            name="ck_checkpoint_records_status",
        ),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    job_type: MappedColumn[str] = mapped_column(String, nullable=False)
    job_id: MappedColumn[str] = mapped_column(String, nullable=False)
    state_json: MappedColumn[str] = mapped_column(String, nullable=False)
    status: MappedColumn[str] = mapped_column(
        String, nullable=False, default="ACTIVE", index=True
    )
    created_at: MappedColumn[str] = mapped_column(String, nullable=False)
    updated_at: MappedColumn[str] = mapped_column(String, nullable=False)


# ---------------------------------------------------------------------------
# Update packages
# ---------------------------------------------------------------------------

class UpdatePackageORM(Base):
    __tablename__ = "update_packages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','APPLIED','ROLLED_BACK')",
            name="ck_update_packages_status",
        ),
    )

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    version: MappedColumn[str] = mapped_column(String, nullable=False)
    manifest_json: MappedColumn[str] = mapped_column(String, nullable=False)
    file_path: MappedColumn[str] = mapped_column(String, nullable=False)
    file_hash: MappedColumn[str] = mapped_column(String, nullable=False)
    imported_at: MappedColumn[str] = mapped_column(String, nullable=False)
    imported_by: MappedColumn[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    status: MappedColumn[str] = mapped_column(
        String, nullable=False, default="PENDING"
    )
    prior_version_ref: MappedColumn[str | None] = mapped_column(
        String, ForeignKey("update_packages.id"), nullable=True
    )
