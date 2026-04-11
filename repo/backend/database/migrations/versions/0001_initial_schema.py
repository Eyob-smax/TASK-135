"""Initial schema — all tables for District Console.

Revision ID: 0001
Revises: (none)
Create Date: 2026-04-10
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # RBAC: users, roles, permissions
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("username", sa.Text, nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
        sa.Column("failed_attempts", sa.Integer, nullable=False, default=0),
        sa.Column("locked_until", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.CheckConstraint("failed_attempts >= 0 AND failed_attempts <= 10",
                           name="ck_users_failed_attempts"),
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("role_type", sa.Text, nullable=False, unique=True),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.CheckConstraint(
            "role_type IN ('ADMINISTRATOR','LIBRARIAN','TEACHER','COUNSELOR','REVIEWER')",
            name="ck_roles_role_type",
        ),
    )

    op.create_table(
        "permissions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("resource_name", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Text, sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("permission_id", sa.Text, sa.ForeignKey("permissions.id"), nullable=False),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role_id", sa.Text, sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("assigned_by", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assigned_at", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )

    # ------------------------------------------------------------------
    # Scope hierarchy
    # ------------------------------------------------------------------
    op.create_table(
        "schools",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("district_code", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
    )

    op.create_table(
        "departments",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("school_id", sa.Text, sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
    )

    op.create_table(
        "classes",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("department_id", sa.Text, sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("teacher_id", sa.Text, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
    )

    op.create_table(
        "individuals",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("class_id", sa.Text, sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=True),
    )

    op.create_table(
        "scope_assignments",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("scope_type", sa.Text, nullable=False),
        sa.Column("scope_ref_id", sa.Text, nullable=False),
        sa.Column("granted_by", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("granted_at", sa.Text, nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('SCHOOL','DEPARTMENT','CLASS','INDIVIDUAL')",
            name="ck_scope_assignments_scope_type",
        ),
    )
    op.create_index("ix_scope_assignments_user_id", "scope_assignments", ["user_id"])

    # ------------------------------------------------------------------
    # Resource library
    # ------------------------------------------------------------------
    op.create_table(
        "resources",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("resource_type", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, default="DRAFT"),
        sa.Column("file_fingerprint", sa.Text, nullable=False),
        sa.Column("isbn", sa.Text, nullable=True),
        sa.Column("dedup_key", sa.Text, nullable=False, unique=True),
        sa.Column("created_by", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.CheckConstraint(
            "resource_type IN ('BOOK','PICTURE_BOOK','ARTICLE','AUDIO')",
            name="ck_resources_resource_type",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT','IN_REVIEW','PUBLISHED','UNPUBLISHED')",
            name="ck_resources_status",
        ),
    )
    op.create_index("ix_resources_status", "resources", ["status"])
    op.create_index("ix_resources_resource_type", "resources", ["resource_type"])

    op.create_table(
        "resource_revisions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("resource_id", sa.Text, sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("revision_number", sa.Integer, nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("file_hash", sa.Text, nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False),
        sa.Column("imported_by", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.UniqueConstraint("resource_id", "revision_number",
                            name="uq_resource_revisions_resource_revision"),
    )
    op.create_index("ix_resource_revisions_resource_id",
                    "resource_revisions", ["resource_id"])

    op.create_table(
        "categories",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("depth", sa.Integer, nullable=False, default=0),
        sa.Column("path_slug", sa.Text, nullable=False, unique=True),
        sa.Column("parent_id", sa.Text, sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
        sa.CheckConstraint("depth >= 0", name="ck_categories_depth"),
    )

    op.create_table(
        "resource_metadata",
        sa.Column("resource_id", sa.Text,
                  sa.ForeignKey("resources.id"), primary_key=True),
        sa.Column("timeliness", sa.Text, nullable=True),
        sa.Column("source", sa.Text, nullable=True),
        sa.Column("copyright", sa.Text, nullable=True),
        sa.Column("theme", sa.Text, nullable=True),
        sa.Column("difficulty_level", sa.Text, nullable=True),
        sa.Column("age_range_min", sa.Integer, nullable=True),
        sa.Column("age_range_max", sa.Integer, nullable=True),
        sa.CheckConstraint(
            "timeliness IS NULL OR timeliness IN ('EVERGREEN','CURRENT','ARCHIVED')",
            name="ck_resource_metadata_timeliness",
        ),
        sa.CheckConstraint(
            "age_range_min IS NULL OR age_range_min >= 0",
            name="ck_resource_metadata_age_min",
        ),
        sa.CheckConstraint(
            "age_range_max IS NULL OR age_range_max <= 18",
            name="ck_resource_metadata_age_max",
        ),
        sa.CheckConstraint(
            "age_range_min IS NULL OR age_range_max IS NULL OR age_range_min <= age_range_max",
            name="ck_resource_metadata_age_order",
        ),
    )

    op.create_table(
        "resource_categories",
        sa.Column("resource_id", sa.Text, sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("category_id", sa.Text, sa.ForeignKey("categories.id"), nullable=False),
        sa.PrimaryKeyConstraint("resource_id", "category_id"),
    )

    op.create_table(
        "resource_keywords",
        sa.Column("resource_id", sa.Text, sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("keyword", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("resource_id", "keyword"),
    )

    op.create_table(
        "review_tasks",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("resource_id", sa.Text, sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("assigned_to", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=False, default=""),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("completed_at", sa.Text, nullable=True),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('APPROVED','REJECTED','NEEDS_REVISION')",
            name="ck_review_tasks_decision",
        ),
    )
    op.create_index("ix_review_tasks_resource_id", "review_tasks", ["resource_id"])

    op.create_table(
        "audit_events",
        # APPEND-ONLY: this table must never receive UPDATE or DELETE statements.
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("entity_type", sa.Text, nullable=False),
        sa.Column("entity_id", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("actor_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("timestamp", sa.Text, nullable=False),
        sa.Column("metadata_json", sa.Text, nullable=False, default="{}"),
    )
    op.create_index("ix_audit_events_entity", "audit_events",
                    ["entity_type", "entity_id"])
    op.create_index("ix_audit_events_actor", "audit_events", ["actor_id"])
    op.create_index("ix_audit_events_timestamp", "audit_events", ["timestamp"])

    op.create_table(
        "taxonomy_validation_rules",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("field", sa.Text, nullable=False),
        sa.Column("rule_type", sa.Text, nullable=False),
        sa.Column("rule_value", sa.Text, nullable=False),  # JSON-encoded
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
        sa.Column("description", sa.Text, nullable=True),
    )

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------
    op.create_table(
        "inventory_items",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("sku", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("unit_cost", sa.Text, nullable=False),  # Stored as TEXT for Decimal precision
        sa.Column("created_by", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )

    op.create_table(
        "warehouses",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("school_id", sa.Text, sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("address", sa.Text, nullable=False, default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
    )

    op.create_table(
        "locations",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("warehouse_id", sa.Text,
                  sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("zone", sa.Text, nullable=False),
        sa.Column("aisle", sa.Text, nullable=False),
        sa.Column("bin_label", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
        sa.UniqueConstraint("warehouse_id", "bin_label",
                            name="uq_locations_warehouse_bin"),
    )
    op.create_index("ix_locations_warehouse_id", "locations", ["warehouse_id"])

    op.create_table(
        "stock_balances",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("item_id", sa.Text, sa.ForeignKey("inventory_items.id"), nullable=False),
        sa.Column("location_id", sa.Text, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("batch_id", sa.Text, nullable=True),
        sa.Column("serial_id", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, default="AVAILABLE"),
        sa.Column("quantity", sa.Integer, nullable=False, default=0),
        sa.Column("is_frozen", sa.Boolean, nullable=False, default=False),
        sa.Column("freeze_reason", sa.Text, nullable=True),
        sa.Column("frozen_by", sa.Text, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("frozen_at", sa.Text, nullable=True),
        sa.CheckConstraint("quantity >= 0", name="ck_stock_balances_quantity"),
        sa.CheckConstraint(
            "status IN ('AVAILABLE','RESERVED','QUARANTINE','DISPOSED','FROZEN')",
            name="ck_stock_balances_status",
        ),
    )
    op.create_index("ix_stock_balances_item_location",
                    "stock_balances", ["item_id", "location_id"])

    op.create_table(
        "record_locks",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("entity_type", sa.Text, nullable=False),
        sa.Column("entity_id", sa.Text, nullable=False),
        sa.Column("locked_by", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("locked_at", sa.Text, nullable=False),
        sa.Column("expires_at", sa.Text, nullable=False),
        sa.Column("nonce", sa.Text, nullable=False),
        sa.UniqueConstraint("entity_type", "entity_id",
                            name="uq_record_locks_entity"),
    )

    op.create_table(
        "ledger_entries",
        # APPEND-ONLY: this table must never receive UPDATE or DELETE statements.
        # Corrections are represented as new CORRECTION entries with reversal_of_id set.
        # The is_reversed flag on the original entry may be updated to True ONLY
        # when a CORRECTION entry references it — no other column may be updated.
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("item_id", sa.Text, sa.ForeignKey("inventory_items.id"), nullable=False),
        sa.Column("location_id", sa.Text, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("entry_type", sa.Text, nullable=False),
        sa.Column("quantity_delta", sa.Integer, nullable=False),
        sa.Column("quantity_after", sa.Integer, nullable=False),
        sa.Column("operator_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason_code", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("reference_id", sa.Text, nullable=True),
        sa.Column("is_reversed", sa.Boolean, nullable=False, default=False),
        sa.Column("reversal_of_id", sa.Text,
                  sa.ForeignKey("ledger_entries.id"), nullable=True),
        sa.CheckConstraint("quantity_after >= 0", name="ck_ledger_entries_quantity_after"),
        sa.CheckConstraint(
            "entry_type IN ('RECEIPT','ADJUSTMENT','RELOCATION','CORRECTION','COUNT_CLOSE')",
            name="ck_ledger_entries_entry_type",
        ),
    )
    op.create_index("ix_ledger_entries_item_location",
                    "ledger_entries", ["item_id", "location_id"])
    op.create_index("ix_ledger_entries_created_at", "ledger_entries", ["created_at"])

    # ------------------------------------------------------------------
    # Count sessions
    # ------------------------------------------------------------------
    op.create_table(
        "count_sessions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("mode", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, default="ACTIVE"),
        sa.Column("warehouse_id", sa.Text,
                  sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("created_by", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("last_activity_at", sa.Text, nullable=False),
        sa.Column("closed_at", sa.Text, nullable=True),
        sa.Column("approved_by", sa.Text, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.Text, nullable=True),
        sa.CheckConstraint("mode IN ('OPEN','BLIND','CYCLE')",
                           name="ck_count_sessions_mode"),
        sa.CheckConstraint(
            "status IN ('ACTIVE','CLOSED','EXPIRED','APPROVED')",
            name="ck_count_sessions_status",
        ),
    )

    op.create_table(
        "count_lines",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("count_sessions.id"), nullable=False),
        sa.Column("item_id", sa.Text, sa.ForeignKey("inventory_items.id"), nullable=False),
        sa.Column("location_id", sa.Text, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("expected_qty", sa.Integer, nullable=False),
        sa.Column("counted_qty", sa.Integer, nullable=False),
        sa.Column("variance_qty", sa.Integer, nullable=False),
        sa.Column("variance_value", sa.Text, nullable=False),  # TEXT for Decimal
        sa.Column("requires_approval", sa.Boolean, nullable=False, default=False),
        sa.Column("reason_code", sa.Text, nullable=True),
    )
    op.create_index("ix_count_lines_session_id", "count_lines", ["session_id"])

    op.create_table(
        "count_approvals",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("count_sessions.id"), nullable=False),
        sa.Column("reviewed_by", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", sa.Text, nullable=False),
        sa.Column("notes", sa.Text, nullable=False),
        sa.Column("decided_at", sa.Text, nullable=False),
        sa.CheckConstraint(
            "decision IN ('APPROVED','REJECTED','NEEDS_REVISION')",
            name="ck_count_approvals_decision",
        ),
    )

    # ------------------------------------------------------------------
    # Relocations
    # ------------------------------------------------------------------
    op.create_table(
        "relocations",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("item_id", sa.Text, sa.ForeignKey("inventory_items.id"), nullable=False),
        sa.Column("from_location_id", sa.Text, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("to_location_id", sa.Text, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("operator_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("device_source", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("ledger_debit_entry_id", sa.Text,
                  sa.ForeignKey("ledger_entries.id"), nullable=False),
        sa.Column("ledger_credit_entry_id", sa.Text,
                  sa.ForeignKey("ledger_entries.id"), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_relocations_quantity"),
        sa.CheckConstraint(
            "from_location_id != to_location_id",
            name="ck_relocations_distinct_locations",
        ),
        sa.CheckConstraint(
            "device_source IN ('MANUAL','USB_SCANNER')",
            name="ck_relocations_device_source",
        ),
    )

    # ------------------------------------------------------------------
    # Configuration center
    # ------------------------------------------------------------------
    op.create_table(
        "config_dictionary",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("is_system", sa.Boolean, nullable=False, default=False),
        sa.Column("updated_by", sa.Text, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.Text, nullable=True),
        sa.UniqueConstraint("category", "key", name="uq_config_dictionary_category_key"),
    )

    op.create_table(
        "workflow_nodes",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workflow_name", sa.Text, nullable=False),
        sa.Column("from_state", sa.Text, nullable=False),
        sa.Column("to_state", sa.Text, nullable=False),
        sa.Column("required_role", sa.Text, nullable=False),
        sa.Column("condition_json", sa.Text, nullable=True),
    )
    op.create_index("ix_workflow_nodes_workflow", "workflow_nodes", ["workflow_name"])

    op.create_table(
        "notification_templates",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("subject_template", sa.Text, nullable=False),
        sa.Column("body_template", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
    )

    op.create_table(
        "district_descriptors",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("key", sa.Text, nullable=False, unique=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("region", sa.Text, nullable=True),
    )

    # ------------------------------------------------------------------
    # Integrations
    # ------------------------------------------------------------------
    op.create_table(
        "integration_clients",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
        sa.Column("created_at", sa.Text, nullable=False),
    )

    op.create_table(
        "hmac_keys",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("client_id", sa.Text,
                  sa.ForeignKey("integration_clients.id"), nullable=False),
        sa.Column("key_encrypted", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("expires_at", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
        sa.Column("is_next", sa.Boolean, nullable=False, default=False),
    )
    op.create_index("ix_hmac_keys_client_id", "hmac_keys", ["client_id"])

    op.create_table(
        "outbound_events",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("client_id", sa.Text,
                  sa.ForeignKey("integration_clients.id"), nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, default="PENDING"),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("delivered_at", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, default=0),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING','DELIVERED','FAILED')",
            name="ck_outbound_events_status",
        ),
    )
    op.create_index("ix_outbound_events_status", "outbound_events", ["status"])

    op.create_table(
        "rate_limit_state",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("client_id", sa.Text,
                  sa.ForeignKey("integration_clients.id"), nullable=False, unique=True),
        sa.Column("window_start", sa.Text, nullable=False),
        sa.Column("request_count", sa.Integer, nullable=False, default=0),
        sa.CheckConstraint("request_count >= 0", name="ck_rate_limit_state_count"),
    )

    # ------------------------------------------------------------------
    # Checkpoint / recovery
    # ------------------------------------------------------------------
    op.create_table(
        "checkpoint_records",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("job_type", sa.Text, nullable=False),
        sa.Column("job_id", sa.Text, nullable=False),
        sa.Column("state_json", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, default="ACTIVE"),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.CheckConstraint(
            "job_type IN ('import','count','approval','scheduled')",
            name="ck_checkpoint_records_job_type",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','COMPLETED','FAILED','ABANDONED')",
            name="ck_checkpoint_records_status",
        ),
    )
    op.create_index("ix_checkpoint_records_status", "checkpoint_records", ["status"])

    # ------------------------------------------------------------------
    # Update packages
    # ------------------------------------------------------------------
    op.create_table(
        "update_packages",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("version", sa.Text, nullable=False),
        sa.Column("manifest_json", sa.Text, nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("file_hash", sa.Text, nullable=False),
        sa.Column("imported_at", sa.Text, nullable=False),
        sa.Column("imported_by", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.Text, nullable=False, default="PENDING"),
        sa.Column("prior_version_ref", sa.Text,
                  sa.ForeignKey("update_packages.id"), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING','APPLIED','ROLLED_BACK')",
            name="ck_update_packages_status",
        ),
    )


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("update_packages")
    op.drop_table("checkpoint_records")
    op.drop_table("rate_limit_state")
    op.drop_table("outbound_events")
    op.drop_table("hmac_keys")
    op.drop_table("integration_clients")
    op.drop_table("district_descriptors")
    op.drop_table("notification_templates")
    op.drop_table("workflow_nodes")
    op.drop_table("config_dictionary")
    op.drop_table("relocations")
    op.drop_table("count_approvals")
    op.drop_table("count_lines")
    op.drop_table("count_sessions")
    op.drop_table("ledger_entries")
    op.drop_table("record_locks")
    op.drop_table("stock_balances")
    op.drop_table("locations")
    op.drop_table("warehouses")
    op.drop_table("inventory_items")
    op.drop_table("taxonomy_validation_rules")
    op.drop_table("audit_events")
    op.drop_table("review_tasks")
    op.drop_table("resource_keywords")
    op.drop_table("resource_categories")
    op.drop_table("resource_metadata")
    op.drop_table("categories")
    op.drop_table("resource_revisions")
    op.drop_table("resources")
    op.drop_table("scope_assignments")
    op.drop_table("individuals")
    op.drop_table("classes")
    op.drop_table("departments")
    op.drop_table("schools")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("users")
