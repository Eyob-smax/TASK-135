-- District Console — SQLite Schema Snapshot
-- Generated from migration 0001_initial_schema.py
-- Last updated: Prompt 2
--
-- IMPORTANT: This file is for human reference only. The authoritative schema
-- is defined in database/migrations/versions/0001_initial_schema.py.
-- Keep this file in sync when migrations are added.
--
-- SQLite pragmas applied at runtime (not in DDL):
--   PRAGMA journal_mode = WAL;
--   PRAGMA foreign_keys = ON;
--   PRAGMA synchronous = NORMAL;
--   PRAGMA busy_timeout = 5000;
--
-- All UUIDs stored as TEXT. All timestamps stored as TEXT (ISO-8601 UTC).
-- All Decimal values stored as TEXT to preserve precision.

-- ============================================================
-- RBAC
-- ============================================================

CREATE TABLE users (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,          -- Argon2id encoded string
    is_active       INTEGER NOT NULL DEFAULT 1,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,                   -- ISO-8601 UTC or NULL
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    CONSTRAINT ck_users_failed_attempts CHECK (failed_attempts >= 0 AND failed_attempts <= 10)
);

CREATE TABLE roles (
    id           TEXT PRIMARY KEY,
    role_type    TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    CONSTRAINT ck_roles_role_type
        CHECK (role_type IN ('ADMINISTRATOR','LIBRARIAN','TEACHER','COUNSELOR','REVIEWER'))
);

CREATE TABLE permissions (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,  -- e.g. "resources.publish"
    resource_name TEXT NOT NULL,
    action        TEXT NOT NULL
);

CREATE TABLE role_permissions (
    role_id       TEXT NOT NULL REFERENCES roles(id),
    permission_id TEXT NOT NULL REFERENCES permissions(id),
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE user_roles (
    user_id     TEXT NOT NULL REFERENCES users(id),
    role_id     TEXT NOT NULL REFERENCES roles(id),
    assigned_by TEXT NOT NULL REFERENCES users(id),
    assigned_at TEXT NOT NULL,
    PRIMARY KEY (user_id, role_id)
);

-- ============================================================
-- Scope hierarchy
-- ============================================================

CREATE TABLE schools (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    district_code TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE departments (
    id        TEXT PRIMARY KEY,
    school_id TEXT NOT NULL REFERENCES schools(id),
    name      TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE classes (
    id            TEXT PRIMARY KEY,
    department_id TEXT NOT NULL REFERENCES departments(id),
    name          TEXT NOT NULL,
    teacher_id    TEXT REFERENCES users(id),
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE individuals (
    id           TEXT PRIMARY KEY,
    class_id     TEXT NOT NULL REFERENCES classes(id),
    display_name TEXT NOT NULL,
    user_id      TEXT REFERENCES users(id)
);

CREATE TABLE scope_assignments (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    scope_type  TEXT NOT NULL,
    scope_ref_id TEXT NOT NULL,
    granted_by  TEXT NOT NULL REFERENCES users(id),
    granted_at  TEXT NOT NULL,
    CONSTRAINT ck_scope_assignments_scope_type
        CHECK (scope_type IN ('SCHOOL','DEPARTMENT','CLASS','INDIVIDUAL'))
);
CREATE INDEX ix_scope_assignments_user_id ON scope_assignments(user_id);

-- ============================================================
-- Resource library
-- ============================================================

CREATE TABLE resources (
    id                 TEXT PRIMARY KEY,
    title              TEXT NOT NULL,
    resource_type      TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'DRAFT',
    file_fingerprint   TEXT NOT NULL,
    isbn               TEXT,
    dedup_key          TEXT NOT NULL UNIQUE,
    created_by         TEXT NOT NULL REFERENCES users(id),
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    owner_scope_type   TEXT,
    -- owner_scope_ref_id references the PK of schools/departments/classes/individuals
    -- depending on owner_scope_type. A polymorphic FK cannot be expressed as a single
    -- SQL REFERENCES constraint in SQLite; referential integrity is enforced at the
    -- application layer (resource router + ResourceRepository).
    owner_scope_ref_id TEXT,
    CONSTRAINT ck_resources_resource_type
        CHECK (resource_type IN ('BOOK','PICTURE_BOOK','ARTICLE','AUDIO')),
    CONSTRAINT ck_resources_status
        CHECK (status IN ('DRAFT','IN_REVIEW','PUBLISHED','UNPUBLISHED')),
    CONSTRAINT ck_resources_owner_scope_type
        CHECK (owner_scope_type IS NULL OR owner_scope_type IN ('SCHOOL','DEPARTMENT','CLASS','INDIVIDUAL'))
);
CREATE INDEX ix_resources_status ON resources(status);
CREATE INDEX ix_resources_resource_type ON resources(resource_type);

CREATE TABLE resource_revisions (
    id              TEXT PRIMARY KEY,
    resource_id     TEXT NOT NULL REFERENCES resources(id),
    revision_number INTEGER NOT NULL,  -- 1-based, max 10 per resource
    file_path       TEXT NOT NULL,
    file_hash       TEXT NOT NULL,
    file_size       INTEGER NOT NULL,
    imported_by     TEXT NOT NULL REFERENCES users(id),
    created_at      TEXT NOT NULL,
    UNIQUE (resource_id, revision_number)
);
CREATE INDEX ix_resource_revisions_resource_id ON resource_revisions(resource_id);

CREATE TABLE categories (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    depth     INTEGER NOT NULL DEFAULT 0,
    path_slug TEXT NOT NULL UNIQUE,
    parent_id TEXT REFERENCES categories(id),
    is_active INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT ck_categories_depth CHECK (depth >= 0)
);

CREATE TABLE resource_metadata (
    resource_id      TEXT PRIMARY KEY REFERENCES resources(id),
    timeliness       TEXT,
    source           TEXT,
    copyright        TEXT,
    theme            TEXT,
    difficulty_level TEXT,
    age_range_min    INTEGER,
    age_range_max    INTEGER,
    CONSTRAINT ck_resource_metadata_timeliness
        CHECK (timeliness IS NULL OR timeliness IN ('EVERGREEN','CURRENT','ARCHIVED')),
    CONSTRAINT ck_resource_metadata_age_min  CHECK (age_range_min IS NULL OR age_range_min >= 0),
    CONSTRAINT ck_resource_metadata_age_max  CHECK (age_range_max IS NULL OR age_range_max <= 18),
    CONSTRAINT ck_resource_metadata_age_order
        CHECK (age_range_min IS NULL OR age_range_max IS NULL OR age_range_min <= age_range_max)
);

CREATE TABLE resource_categories (
    resource_id TEXT NOT NULL REFERENCES resources(id),
    category_id TEXT NOT NULL REFERENCES categories(id),
    PRIMARY KEY (resource_id, category_id)
);

CREATE TABLE resource_keywords (
    resource_id TEXT NOT NULL REFERENCES resources(id),
    keyword     TEXT NOT NULL,
    PRIMARY KEY (resource_id, keyword)
);

CREATE TABLE review_tasks (
    id          TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL REFERENCES resources(id),
    assigned_to TEXT NOT NULL REFERENCES users(id),
    decision    TEXT,
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    completed_at TEXT,
    CONSTRAINT ck_review_tasks_decision
        CHECK (decision IS NULL OR decision IN ('APPROVED','REJECTED','NEEDS_REVISION'))
);
CREATE INDEX ix_review_tasks_resource_id ON review_tasks(resource_id);

CREATE TABLE audit_events (
    -- APPEND-ONLY: no UPDATE or DELETE permitted on this table
    id            TEXT PRIMARY KEY,
    entity_type   TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    action        TEXT NOT NULL,
    actor_id      TEXT NOT NULL REFERENCES users(id),
    timestamp     TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX ix_audit_events_entity    ON audit_events(entity_type, entity_id);
CREATE INDEX ix_audit_events_actor     ON audit_events(actor_id);
CREATE INDEX ix_audit_events_timestamp ON audit_events(timestamp);

CREATE TABLE taxonomy_validation_rules (
    id          TEXT PRIMARY KEY,
    field       TEXT NOT NULL,
    rule_type   TEXT NOT NULL,
    rule_value  TEXT NOT NULL,  -- JSON-encoded constraint specification
    is_active   INTEGER NOT NULL DEFAULT 1,
    description TEXT
);

-- ============================================================
-- Inventory
-- ============================================================

CREATE TABLE inventory_items (
    id          TEXT PRIMARY KEY,
    sku         TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    unit_cost   TEXT NOT NULL,  -- TEXT for Decimal precision
    created_by  TEXT NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL
);

CREATE TABLE warehouses (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    school_id TEXT NOT NULL REFERENCES schools(id),
    address   TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE locations (
    id           TEXT PRIMARY KEY,
    warehouse_id TEXT NOT NULL REFERENCES warehouses(id),
    zone         TEXT NOT NULL,
    aisle        TEXT NOT NULL,
    bin_label    TEXT NOT NULL,
    is_active    INTEGER NOT NULL DEFAULT 1,
    UNIQUE (warehouse_id, bin_label)
);
CREATE INDEX ix_locations_warehouse_id ON locations(warehouse_id);

CREATE TABLE stock_balances (
    id           TEXT PRIMARY KEY,
    item_id      TEXT NOT NULL REFERENCES inventory_items(id),
    location_id  TEXT NOT NULL REFERENCES locations(id),
    batch_id     TEXT,
    serial_id    TEXT,
    status       TEXT NOT NULL DEFAULT 'AVAILABLE',
    quantity     INTEGER NOT NULL DEFAULT 0,
    is_frozen    INTEGER NOT NULL DEFAULT 0,
    freeze_reason TEXT,
    frozen_by    TEXT REFERENCES users(id),
    frozen_at    TEXT,
    CONSTRAINT ck_stock_balances_quantity CHECK (quantity >= 0),
    CONSTRAINT ck_stock_balances_status
        CHECK (status IN ('AVAILABLE','RESERVED','QUARANTINE','DISPOSED','FROZEN'))
);
CREATE INDEX ix_stock_balances_item_location ON stock_balances(item_id, location_id);

CREATE TABLE record_locks (
    id          TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    locked_by   TEXT NOT NULL REFERENCES users(id),
    locked_at   TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    nonce       TEXT NOT NULL,
    UNIQUE (entity_type, entity_id)
);

CREATE TABLE ledger_entries (
    -- APPEND-ONLY: no UPDATE or DELETE permitted on this table.
    -- Exception: is_reversed may be set to 1 when a CORRECTION entry references this row.
    id              TEXT PRIMARY KEY,
    item_id         TEXT NOT NULL REFERENCES inventory_items(id),
    location_id     TEXT NOT NULL REFERENCES locations(id),
    entry_type      TEXT NOT NULL,
    quantity_delta  INTEGER NOT NULL,
    quantity_after  INTEGER NOT NULL,
    operator_id     TEXT NOT NULL REFERENCES users(id),
    reason_code     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    reference_id    TEXT,               -- count_session_id, relocation_id, etc.
    is_reversed     INTEGER NOT NULL DEFAULT 0,
    reversal_of_id  TEXT REFERENCES ledger_entries(id),
    CONSTRAINT ck_ledger_entries_quantity_after CHECK (quantity_after >= 0),
    CONSTRAINT ck_ledger_entries_entry_type
        CHECK (entry_type IN ('RECEIPT','ADJUSTMENT','RELOCATION','CORRECTION','COUNT_CLOSE'))
);
CREATE INDEX ix_ledger_entries_item_location ON ledger_entries(item_id, location_id);
CREATE INDEX ix_ledger_entries_created_at    ON ledger_entries(created_at);

-- ============================================================
-- Count sessions
-- ============================================================

CREATE TABLE count_sessions (
    id              TEXT PRIMARY KEY,
    mode            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'ACTIVE',
    warehouse_id    TEXT NOT NULL REFERENCES warehouses(id),
    created_by      TEXT NOT NULL REFERENCES users(id),
    created_at      TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    closed_at       TEXT,
    approved_by     TEXT REFERENCES users(id),
    approved_at     TEXT,
    CONSTRAINT ck_count_sessions_mode   CHECK (mode IN ('OPEN','BLIND','CYCLE')),
    CONSTRAINT ck_count_sessions_status CHECK (status IN ('ACTIVE','CLOSED','EXPIRED','APPROVED'))
);

CREATE TABLE count_lines (
    id               TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES count_sessions(id),
    item_id          TEXT NOT NULL REFERENCES inventory_items(id),
    location_id      TEXT NOT NULL REFERENCES locations(id),
    expected_qty     INTEGER NOT NULL,
    counted_qty      INTEGER NOT NULL,
    variance_qty     INTEGER NOT NULL,
    variance_value   TEXT NOT NULL,  -- TEXT for Decimal
    requires_approval INTEGER NOT NULL DEFAULT 0,
    reason_code      TEXT
);
CREATE INDEX ix_count_lines_session_id ON count_lines(session_id);

CREATE TABLE count_approvals (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES count_sessions(id),
    reviewed_by TEXT NOT NULL REFERENCES users(id),
    decision    TEXT NOT NULL,
    notes       TEXT NOT NULL,
    decided_at  TEXT NOT NULL,
    CONSTRAINT ck_count_approvals_decision
        CHECK (decision IN ('APPROVED','REJECTED','NEEDS_REVISION'))
);

-- ============================================================
-- Relocations
-- ============================================================

CREATE TABLE relocations (
    id                    TEXT PRIMARY KEY,
    item_id               TEXT NOT NULL REFERENCES inventory_items(id),
    from_location_id      TEXT NOT NULL REFERENCES locations(id),
    to_location_id        TEXT NOT NULL REFERENCES locations(id),
    quantity              INTEGER NOT NULL,
    operator_id           TEXT NOT NULL REFERENCES users(id),
    device_source         TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    ledger_debit_entry_id  TEXT NOT NULL REFERENCES ledger_entries(id),
    ledger_credit_entry_id TEXT NOT NULL REFERENCES ledger_entries(id),
    CONSTRAINT ck_relocations_quantity  CHECK (quantity > 0),
    CONSTRAINT ck_relocations_distinct  CHECK (from_location_id != to_location_id),
    CONSTRAINT ck_relocations_device    CHECK (device_source IN ('MANUAL','USB_SCANNER'))
);

-- ============================================================
-- Configuration center
-- ============================================================

CREATE TABLE config_dictionary (
    id          TEXT PRIMARY KEY,
    category    TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_system   INTEGER NOT NULL DEFAULT 0,
    updated_by  TEXT REFERENCES users(id),
    updated_at  TEXT,
    UNIQUE (category, key)
);

CREATE TABLE workflow_nodes (
    id            TEXT PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    from_state    TEXT NOT NULL,
    to_state      TEXT NOT NULL,
    required_role TEXT NOT NULL,
    condition_json TEXT
);
CREATE INDEX ix_workflow_nodes_workflow ON workflow_nodes(workflow_name);

CREATE TABLE notification_templates (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE,
    event_type       TEXT NOT NULL,
    subject_template TEXT NOT NULL,
    body_template    TEXT NOT NULL,
    is_active        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE district_descriptors (
    id          TEXT PRIMARY KEY,
    key         TEXT NOT NULL UNIQUE,
    value       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    region      TEXT
);

-- ============================================================
-- Integrations
-- ============================================================

CREATE TABLE integration_clients (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE hmac_keys (
    id            TEXT PRIMARY KEY,
    client_id     TEXT NOT NULL REFERENCES integration_clients(id),
    key_encrypted TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    is_next       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_hmac_keys_client_id ON hmac_keys(client_id);

CREATE TABLE outbound_events (
    id           TEXT PRIMARY KEY,
    client_id    TEXT NOT NULL REFERENCES integration_clients(id),
    event_type   TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'PENDING',
    created_at   TEXT NOT NULL,
    delivered_at TEXT,
    retry_count  INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT,
    CONSTRAINT ck_outbound_events_status CHECK (status IN ('PENDING','DELIVERED','FAILED'))
);
CREATE INDEX ix_outbound_events_status ON outbound_events(status);

CREATE TABLE rate_limit_state (
    id            TEXT PRIMARY KEY,
    client_id     TEXT NOT NULL UNIQUE REFERENCES integration_clients(id),
    window_start  TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT ck_rate_limit_state_count CHECK (request_count >= 0)
);

-- ============================================================
-- Checkpoint / recovery
-- ============================================================

CREATE TABLE checkpoint_records (
    id         TEXT PRIMARY KEY,
    job_type   TEXT NOT NULL,
    job_id     TEXT NOT NULL,
    state_json TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CONSTRAINT ck_checkpoint_records_job_type
        CHECK (job_type IN ('import','count','approval','scheduled')),
    CONSTRAINT ck_checkpoint_records_status
        CHECK (status IN ('ACTIVE','COMPLETED','FAILED','ABANDONED'))
);
CREATE INDEX ix_checkpoint_records_status ON checkpoint_records(status);

-- ============================================================
-- Update packages
-- ============================================================

CREATE TABLE update_packages (
    id               TEXT PRIMARY KEY,
    version          TEXT NOT NULL,
    manifest_json    TEXT NOT NULL,
    file_path        TEXT NOT NULL,
    file_hash        TEXT NOT NULL,
    imported_at      TEXT NOT NULL,
    imported_by      TEXT NOT NULL REFERENCES users(id),
    status           TEXT NOT NULL DEFAULT 'PENDING',
    prior_version_ref TEXT REFERENCES update_packages(id),
    CONSTRAINT ck_update_packages_status
        CHECK (status IN ('PENDING','APPLIED','ROLLED_BACK'))
);
