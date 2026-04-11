-- Reference data seed for District Console
-- Run after the initial schema migration (0001_initial_schema).
-- All IDs use deterministic UUIDs for reproducibility.

-- ---------------------------------------------------------------------------
-- Roles (system roles seeded on first run)
-- ---------------------------------------------------------------------------
INSERT INTO roles (id, role_type, display_name) VALUES
    ('00000001-0000-0000-0000-000000000001', 'ADMINISTRATOR', 'Administrator'),
    ('00000001-0000-0000-0000-000000000002', 'LIBRARIAN',     'Librarian / Inventory Clerk'),
    ('00000001-0000-0000-0000-000000000003', 'TEACHER',       'Teacher'),
    ('00000001-0000-0000-0000-000000000004', 'COUNSELOR',     'Counselor'),
    ('00000001-0000-0000-0000-000000000005', 'REVIEWER',      'Reviewer / Approver')
ON CONFLICT(role_type) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Permissions
-- ---------------------------------------------------------------------------
INSERT INTO permissions (id, name, resource_name, action) VALUES
    ('00000002-0000-0000-0000-000000000001', 'admin.manage_users',       'admin',       'manage_users'),
    ('00000002-0000-0000-0000-000000000002', 'admin.view_audit_log',     'admin',       'view_audit_log'),
    ('00000002-0000-0000-0000-000000000003', 'admin.manage_config',      'admin',       'manage_config'),
    ('00000002-0000-0000-0000-000000000004', 'resources.view',           'resources',   'view'),
    ('00000002-0000-0000-0000-000000000005', 'resources.create',         'resources',   'create'),
    ('00000002-0000-0000-0000-000000000006', 'resources.edit',           'resources',   'edit'),
    ('00000002-0000-0000-0000-000000000007', 'resources.import',         'resources',   'import'),
    ('00000002-0000-0000-0000-000000000008', 'resources.submit_review',  'resources',   'submit_review'),
    ('00000002-0000-0000-0000-000000000009', 'resources.publish',        'resources',   'publish'),
    ('00000002-0000-0000-0000-000000000010', 'resources.classify',       'resources',   'classify'),
    ('00000002-0000-0000-0000-000000000011', 'inventory.view',           'inventory',   'view'),
    ('00000002-0000-0000-0000-000000000012', 'inventory.adjust',         'inventory',   'adjust'),
    ('00000002-0000-0000-0000-000000000013', 'inventory.freeze',         'inventory',   'freeze'),
    ('00000002-0000-0000-0000-000000000014', 'inventory.count',          'inventory',   'count'),
    ('00000002-0000-0000-0000-000000000015', 'inventory.relocate',       'inventory',   'relocate'),
    ('00000002-0000-0000-0000-000000000016', 'inventory.approve_count',  'inventory',   'approve_count'),
    ('00000002-0000-0000-0000-000000000017', 'integrations.manage',      'integrations','manage'),
    ('00000002-0000-0000-0000-000000000018', 'updates.manage',           'updates',     'manage')
ON CONFLICT(name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Role → Permission mappings
-- ---------------------------------------------------------------------------

-- Administrator: all permissions
INSERT INTO role_permissions (role_id, permission_id)
SELECT '00000001-0000-0000-0000-000000000001', id FROM permissions
ON CONFLICT DO NOTHING;

-- Librarian: resources (view/create/edit/import/submit_review) + inventory (all except approve)
INSERT INTO role_permissions (role_id, permission_id)
SELECT '00000001-0000-0000-0000-000000000002', id FROM permissions
WHERE name IN (
    'resources.view','resources.create','resources.edit','resources.import',
    'resources.submit_review',
    'inventory.view','inventory.adjust','inventory.freeze',
    'inventory.count','inventory.relocate'
)
ON CONFLICT DO NOTHING;

-- Teacher: resources view only
INSERT INTO role_permissions (role_id, permission_id)
SELECT '00000001-0000-0000-0000-000000000003', id FROM permissions
WHERE name IN ('resources.view')
ON CONFLICT DO NOTHING;

-- Counselor: resources view + classify
INSERT INTO role_permissions (role_id, permission_id)
SELECT '00000001-0000-0000-0000-000000000004', id FROM permissions
WHERE name IN ('resources.view','resources.classify')
ON CONFLICT DO NOTHING;

-- Reviewer: resources view + publish
INSERT INTO role_permissions (role_id, permission_id)
SELECT '00000001-0000-0000-0000-000000000005', id FROM permissions
WHERE name IN ('resources.view','resources.publish','inventory.approve_count')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Configuration dictionary — timeliness options (system entries)
-- ---------------------------------------------------------------------------
INSERT INTO config_dictionary (id, category, key, value, description, is_system) VALUES
    ('00000003-0000-0000-0000-000000000001', 'timeliness_options', 'EVERGREEN', 'Evergreen',
     'Content remains relevant indefinitely', 1),
    ('00000003-0000-0000-0000-000000000002', 'timeliness_options', 'CURRENT',   'Current',
     'Content is relevant now but may become outdated', 1),
    ('00000003-0000-0000-0000-000000000003', 'timeliness_options', 'ARCHIVED',  'Archived',
     'Content has been superseded or is no longer current', 1)
ON CONFLICT(category, key) DO NOTHING;

-- Adjustment reason codes
INSERT INTO config_dictionary (id, category, key, value, description, is_system) VALUES
    ('00000003-0000-0000-0000-000000000010', 'reason_codes', 'DAMAGED',       'Damaged',         'Item damaged beyond use', 1),
    ('00000003-0000-0000-0000-000000000011', 'reason_codes', 'LOST',          'Lost',            'Item cannot be located', 1),
    ('00000003-0000-0000-0000-000000000012', 'reason_codes', 'FOUND',         'Found',           'Previously lost item located', 1),
    ('00000003-0000-0000-0000-000000000013', 'reason_codes', 'DATA_ENTRY',    'Data Entry Error','Correction of a data entry mistake', 1),
    ('00000003-0000-0000-0000-000000000014', 'reason_codes', 'DONATION',      'Donation',        'Item received as a donation', 1),
    ('00000003-0000-0000-0000-000000000015', 'reason_codes', 'TRANSFER_IN',   'Transfer In',     'Transfer from another warehouse', 1),
    ('00000003-0000-0000-0000-000000000016', 'reason_codes', 'TRANSFER_OUT',  'Transfer Out',    'Transfer to another warehouse', 1)
ON CONFLICT(category, key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Workflow nodes — resource review workflow
-- ---------------------------------------------------------------------------
INSERT INTO workflow_nodes (id, workflow_name, from_state, to_state, required_role) VALUES
    ('00000004-0000-0000-0000-000000000001', 'resource_review', 'DRAFT',        'IN_REVIEW',   'LIBRARIAN'),
    ('00000004-0000-0000-0000-000000000002', 'resource_review', 'IN_REVIEW',    'PUBLISHED',   'REVIEWER'),
    ('00000004-0000-0000-0000-000000000003', 'resource_review', 'IN_REVIEW',    'UNPUBLISHED', 'REVIEWER'),
    ('00000004-0000-0000-0000-000000000004', 'resource_review', 'PUBLISHED',    'UNPUBLISHED', 'REVIEWER'),
    ('00000004-0000-0000-0000-000000000005', 'resource_review', 'UNPUBLISHED',  'IN_REVIEW',   'LIBRARIAN')
ON CONFLICT DO NOTHING;

-- Count approval workflow
INSERT INTO workflow_nodes (id, workflow_name, from_state, to_state, required_role) VALUES
    ('00000004-0000-0000-0000-000000000010', 'count_approval', 'ACTIVE', 'CLOSED',   'LIBRARIAN'),
    ('00000004-0000-0000-0000-000000000011', 'count_approval', 'CLOSED', 'APPROVED', 'ADMINISTRATOR')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- District descriptors (defaults — Administrator should update for their org)
-- ---------------------------------------------------------------------------
INSERT INTO district_descriptors (id, key, value, description) VALUES
    ('00000005-0000-0000-0000-000000000001', 'district_name',        'District Name',   'Full legal name of the school district'),
    ('00000005-0000-0000-0000-000000000002', 'region_code',          '',                'Regional identifier for reporting'),
    ('00000005-0000-0000-0000-000000000003', 'fiscal_year',          '',                'Current fiscal year (e.g. 2025-2026)'),
    ('00000005-0000-0000-0000-000000000004', 'reporting_currency',   'USD',             'Currency used in financial reporting')
ON CONFLICT(key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Notification templates
-- ---------------------------------------------------------------------------
INSERT INTO notification_templates (id, name, event_type, subject_template, body_template, is_active) VALUES
    ('00000006-0000-0000-0000-000000000001',
     'count_session_expired',
     'count_session_expired',
     'Count Session Expired: {session_id}',
     'Count session {session_id} in warehouse {warehouse_name} expired after 8 hours of inactivity. '
     'Please reopen or create a new session.',
     1),
    ('00000006-0000-0000-0000-000000000002',
     'hmac_key_rotation_due',
     'hmac_key_rotation_due',
     'HMAC Key Rotation Due: {client_name}',
     'The HMAC signing key for integration client "{client_name}" expires on {expires_at}. '
     'Please rotate the key before the expiry date.',
     1),
    ('00000006-0000-0000-0000-000000000003',
     'variance_approval_required',
     'variance_approval_required',
     'Count Variance Requires Approval',
     'Count session {session_id} has variance entries exceeding approval thresholds. '
     'Supervisor approval is required before ledger entries are posted.',
     1)
ON CONFLICT(name) DO NOTHING;
