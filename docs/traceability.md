# District Console — Requirement-to-Test Traceability Matrix

This document maps every prompt requirement to the test file(s) and test
class/function that verify it. Acceptance reviewers can use this to confirm
that every stated requirement has executable test coverage.

---

## How to Read This Document

Each section corresponds to one prompt. Within each section, requirements
are bulleted under the area they belong to. For each requirement the
corresponding tests are listed as `test_file.py :: TestClass :: test_name`
(or just `test_file.py :: test_name` for module-level tests).

Test files live under `repo/backend/unit_tests/` and `repo/backend/api_tests/`.

---

## Prompt 2 — Domain Model and Schema

| Requirement | Test Coverage |
|---|---|
| All ResourceStatus transitions valid via VALID_RESOURCE_TRANSITIONS | `unit_tests/domain/test_enums.py :: TestResourceWorkflow` |
| ResourceStatus DRAFT/IN_REVIEW/PUBLISHED/UNPUBLISHED values | `unit_tests/domain/test_enums.py :: TestResourceStatus` |
| validate_resource_transition raises on invalid transition | `unit_tests/domain/test_enums.py :: TestResourceWorkflow` |
| LedgerEntryType values (ADJUSTMENT, CORRECTION, RELOCATION, COUNT_CLOSE) | `unit_tests/domain/test_enums.py :: TestLedgerEntryType` |
| CountMode BLIND/OPEN values | `unit_tests/domain/test_enums.py :: TestCountMode` |
| CountSessionStatus ACTIVE/CLOSED/EXPIRED/APPROVED values | `unit_tests/domain/test_enums.py` |
| ScopeType SCHOOL/DEPARTMENT/CLASS/INDIVIDUAL | `unit_tests/domain/test_enums.py` |
| All domain exception classes inherit DistrictConsoleError | `unit_tests/domain/test_exceptions.py :: TestDistrictConsoleError :: test_all_exceptions_inherit_from_base` |
| Exception .code attributes set correctly | `unit_tests/domain/test_exceptions.py` (all test classes) |
| Exception domain-specific fields accessible | `unit_tests/domain/test_exceptions.py` (field tests per class) |

---

## Prompt 3 — Security Foundation

| Requirement | Test Coverage |
|---|---|
| Password hashing uses Argon2id (not bcrypt/SHA-256) | `unit_tests/application/test_auth_service.py :: TestHashPassword :: test_hash_password_produces_argon2id_format` |
| Password minimum length = 12 characters | `unit_tests/application/test_auth_service.py :: TestHashPassword :: test_hash_password_too_short_raises` |
| Minimum length boundary: exactly 12 chars succeeds | `unit_tests/application/test_auth_service.py :: TestHashPassword :: test_hash_password_exactly_min_length_succeeds` |
| Failed login increments failed_attempts | `unit_tests/application/test_auth_service.py :: TestAuthenticate :: test_authenticate_wrong_password_increments_failed_attempts` |
| 5th failure sets locked_until | `unit_tests/application/test_auth_service.py :: TestAuthenticate :: test_authenticate_5th_failure_locks_account` |
| Locked account raises LockoutError | `unit_tests/application/test_auth_service.py :: TestAuthenticate :: test_authenticate_locked_account_raises_lockout_error` |
| Successful login resets failed_attempts to 0 | `unit_tests/application/test_auth_service.py :: TestAuthenticate :: test_authenticate_success_resets_failed_attempts` |
| Session token roundtrip validates correctly | `unit_tests/application/test_auth_service.py :: TestSessionManagement :: test_session_token_roundtrip_and_expiry` |
| Expired session returns None | `unit_tests/application/test_auth_service.py :: TestSessionManagement :: test_expired_session_returns_none` |
| Invalidated session returns None | `unit_tests/application/test_auth_service.py :: TestSessionManagement :: test_invalidated_session_returns_none` |
| RBAC has_permission returns True for matching role | `unit_tests/application/test_rbac_service.py :: TestPermissions :: test_has_permission_true_for_matching_role` |
| RBAC check_permission raises InsufficientPermissionError | `unit_tests/application/test_rbac_service.py :: TestPermissions :: test_check_permission_raises_insufficient_permission` |
| ADMINISTRATOR role bypasses all permission checks | `unit_tests/application/test_rbac_service.py :: TestAdministratorBypass` |
| filter_by_scope returns only assigned IDs | `unit_tests/application/test_rbac_service.py :: TestScopeEnforcement :: test_filter_by_scope_returns_only_assigned_ids` |
| check_scope raises ScopeViolationError for unassigned scope | `unit_tests/application/test_rbac_service.py :: TestScopeEnforcement :: test_check_scope_raises_scope_violation` |
| HMAC-SHA256 sign/verify roundtrip succeeds | `unit_tests/infrastructure/test_hmac_signer.py` |
| HMAC verify rejects wrong key | `unit_tests/infrastructure/test_hmac_signer.py` |
| HMAC verify rejects stale timestamp (> 5 min) | `unit_tests/infrastructure/test_hmac_signer.py` |
| HMAC API auth rejects expired active key | `api_tests/test_hmac_auth.py :: test_status_with_expired_active_key_returns_401` |
| Key lifecycle deactivates expired active/next keys | `unit_tests/application/test_integration_service.py :: test_enforce_key_lifecycle_deactivates_expired_active_and_next` |
| HMAC signature is constant-time safe (compare_digest) | Implementation contract; `test_hmac_signer.py :: test_tampered_body_fails_verification` |
| Rate limiter allows up to 60 rpm | `unit_tests/infrastructure/test_rate_limiter.py` |
| 61st request raises RateLimitExceededError | `unit_tests/infrastructure/test_rate_limiter.py :: test_exceeding_limit_raises` |
| Rate limit window resets after 60s | `unit_tests/infrastructure/test_rate_limiter.py :: test_window_reset_allows_new_requests` |
| Per-client independent rate limit windows | `unit_tests/infrastructure/test_rate_limiter.py :: test_different_clients_have_independent_limits` |
| Record lock acquire returns RecordLock domain object | `unit_tests/infrastructure/test_lock_manager.py` |
| Held lock raises RecordLockedError | `unit_tests/infrastructure/test_lock_manager.py :: test_held_lock_raises_record_locked_error` |
| Lock release allows re-acquire | `unit_tests/infrastructure/test_lock_manager.py :: test_release_allows_reacquire` |
| Expired lock can be overridden | `unit_tests/infrastructure/test_lock_manager.py :: test_expired_lock_can_be_overridden` |
| SanitizingFilter redacts passwords from log records | `unit_tests/infrastructure/test_logging_config.py :: TestSanitizingFilter` |
| SanitizingFilter redacts key_encrypted values | `unit_tests/infrastructure/test_logging_config.py :: TestSanitizingFilter` |
| Checkpoint save creates ACTIVE record | `unit_tests/infrastructure/test_checkpoint_store.py :: test_save_creates_active_checkpoint` |
| Checkpoint mark_completed updates status | `unit_tests/infrastructure/test_checkpoint_store.py` |
| Checkpoint get_active returns only ACTIVE records | `unit_tests/infrastructure/test_checkpoint_store.py` |
| Startup checkpoint resume marks completed/failed outcomes | `unit_tests/bootstrap/test_recovery_resume.py :: test_resume_recovered_checkpoints_marks_status_and_instruments` |
| Scheduler registers key lifecycle maintenance job | `unit_tests/bootstrap/test_recovery_resume.py :: test_start_scheduler_registers_key_lifecycle_job` |
| Auth login API returns 200 with token | `api_tests/test_auth_routes.py :: TestLogin :: test_login_valid_credentials_returns_200_with_token` |
| Auth login invalid password returns 401 INVALID_CREDENTIALS | `api_tests/test_auth_routes.py :: TestLogin :: test_login_invalid_password_returns_401` |
| Auth login locked account returns 423 ACCOUNT_LOCKED | `api_tests/test_auth_routes.py :: TestLogin :: test_login_locked_account_returns_423` |
| Auth logout invalidates session (subsequent whoami → 401) | `api_tests/test_auth_routes.py :: TestWhoAmI :: test_whoami_after_logout_returns_401` |
| Error responses use envelope format {error: {code, message}} | `api_tests/test_error_envelopes.py` |
| Unauthenticated request returns 401 envelope | `api_tests/test_security_middleware.py` |
| Schema validation failure returns 422 envelope | `api_tests/test_security_middleware.py` |

---

## Prompt 4 — Core Backend Workflows

### Resource Library

| Requirement | Test Coverage |
|---|---|
| import_file computes SHA-256 fingerprint | `unit_tests/application/test_resource_service.py :: test_import_file_creates_resource_and_revision` |
| import_file duplicate dedup_key raises DuplicateResourceError | `unit_tests/application/test_resource_service.py :: test_import_file_duplicate_dedup_key_raises` |
| import_csv processes multiple rows | `unit_tests/application/test_resource_service.py :: test_import_csv_processes_multiple_rows` |
| import_csv skips duplicate rows | `unit_tests/application/test_resource_service.py :: test_import_csv_skips_duplicate_rows` |
| create_revision increments revision_number | `unit_tests/application/test_resource_service.py :: test_create_revision_increments_number` |
| 11th revision raises RevisionLimitError (limit=10) | `unit_tests/application/test_resource_service.py :: test_create_revision_at_limit_raises_revision_limit_error` |
| submit_for_review transitions DRAFT → IN_REVIEW | `unit_tests/application/test_resource_service.py :: test_submit_for_review_transitions_draft_to_in_review` |
| submit_for_review on non-DRAFT raises InvalidStateTransitionError | `unit_tests/application/test_resource_service.py :: test_submit_for_review_non_draft_raises_invalid_transition` |
| publish requires non-empty reviewer_notes | `unit_tests/application/test_resource_service.py :: test_publish_requires_non_empty_reviewer_notes` |
| publish transitions IN_REVIEW → PUBLISHED | `unit_tests/application/test_resource_service.py :: test_publish_transitions_in_review_to_published` |
| unpublish transitions PUBLISHED → UNPUBLISHED | `unit_tests/application/test_resource_service.py :: test_unpublish_transitions_published_to_unpublished` |
| GET /resources/ returns paginated response | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_list_resources_returns_paginated` |
| GET /resources/ without auth returns 401 | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_list_resources_without_auth_returns_401` |
| GET /resources/{id} not found returns 404 | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_get_resource_not_found_returns_404` |
| POST /resources/ returns 201 DRAFT | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_create_resource_returns_201` |
| POST /resources/ without permission returns 403 | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_create_resource_without_permission_returns_403` |
| PUT /resources/{id} updates DRAFT title | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_update_resource_draft_returns_200` |
| PUT /resources/{id} on non-DRAFT returns 409 | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_update_resource_non_draft_returns_409` |
| PUT /resources/{id} missing returns 404 | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_update_resource_not_found_returns_404` |
| POST /import/file creates resource (dedup=false) | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_import_file_creates_resource` |
| POST /import/file duplicate returns 409 | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_import_file_duplicate_returns_409` |
| POST /import/csv creates multiple resources | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_import_csv_creates_multiple_resources` |
| POST /{id}/submit-review transitions to IN_REVIEW | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_submit_for_review_transitions_to_in_review` |
| POST /{id}/publish with empty notes returns 400/422 | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_publish_requires_reviewer_notes_non_empty` |
| POST /{id}/unpublish returns 200 UNPUBLISHED | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_unpublish_resource_returns_200` |
| GET /{id}/revisions returns revision history | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_list_revisions_returns_history` |
| GET /{id}/revisions missing returns 404 | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_revisions_not_found_returns_404` |
| GET /resources/?status=DRAFT filters by status | `api_tests/test_resource_routes.py :: TestResourceRoutes :: test_list_resources_with_status_filter` |

### Inventory and Ledger

| Requirement | Test Coverage |
|---|---|
| create_item stores unit_cost as string (Decimal-safe) | `unit_tests/application/test_inventory_service.py :: test_create_item_stores_decimal_as_string` |
| Duplicate SKU raises conflict | `unit_tests/application/test_inventory_service.py :: test_create_item_duplicate_sku_raises_conflict` |
| freeze_stock sets is_frozen=True and freeze_reason | `unit_tests/application/test_inventory_service.py :: test_freeze_stock_sets_is_frozen_and_reason` |
| unfreeze_stock clears frozen state | `unit_tests/application/test_inventory_service.py :: test_unfreeze_stock_clears_frozen_state` |
| freeze already frozen raises StockFrozenError | `unit_tests/application/test_inventory_service.py :: test_freeze_already_frozen_raises_stock_frozen_error` |
| add_adjustment creates LedgerEntry and updates balance | `unit_tests/application/test_inventory_service.py :: test_add_adjustment_creates_ledger_entry_and_updates_balance` |
| add_adjustment partitions balances by batch_id/serial_id/status | `unit_tests/application/test_inventory_service.py :: test_add_adjustment_uses_batch_partition_independently` |
| Negative balance adjustment raises InsufficientStockError | `unit_tests/application/test_inventory_service.py :: test_add_adjustment_negative_balance_raises_insufficient_stock` |
| add_correction reverses entry and updates balance | `unit_tests/application/test_inventory_service.py :: test_add_correction_reverses_entry_and_updates_balance` |
| Double correction raises AppendOnlyViolationError | `unit_tests/application/test_inventory_service.py :: test_add_correction_already_reversed_raises_append_only_violation` |
| LedgerEntry is append-only (no direct mutation) | `unit_tests/domain/test_audit_invariants.py` |
| POST /inventory/items/ returns 201 | `api_tests/test_inventory_routes.py :: test_create_inventory_item_returns_201` |
| POST /inventory/items/ duplicate SKU returns 409 | `api_tests/test_inventory_routes.py :: test_create_item_duplicate_sku_returns_409` |
| POST /stock/{id}/freeze requires reason field | `api_tests/test_inventory_routes.py :: test_freeze_stock_requires_reason` |
| POST /stock/{id}/freeze + unfreeze roundtrip | `api_tests/test_inventory_routes.py :: test_freeze_and_unfreeze_stock` |
| POST /ledger/adjustment creates entry | `api_tests/test_inventory_routes.py :: test_add_adjustment_creates_ledger_entry` |
| POST /ledger/adjustment preserves batch partition isolation | `api_tests/test_inventory_routes.py :: test_add_adjustment_respects_batch_partition` |
| POST /ledger/correction/{id} reverses entry | `api_tests/test_inventory_routes.py :: test_add_correction_reverses_entry` |

### Count Sessions

| Requirement | Test Coverage |
|---|---|
| open_session creates ACTIVE session and checkpoint | `unit_tests/application/test_count_session_service.py :: test_open_session_creates_active_session` |
| Checkpoint saved on session open | `unit_tests/application/test_count_session_service.py :: test_open_session_saves_checkpoint` |
| add_count_line evaluates variance_qty | `unit_tests/application/test_count_session_service.py :: test_add_count_line_evaluates_variance` |
| Expired session (> 8h) rejects new line | `unit_tests/application/test_count_session_service.py :: test_add_line_to_expired_session_raises` |
| close_session generates ledger entries for variances | `unit_tests/application/test_count_session_service.py :: test_close_session_generates_ledger_entries_for_variances` |
| requires_approval set for variance > $250 | `unit_tests/application/test_count_session_service.py :: test_close_session_marks_requires_approval_for_large_variance` |
| approve_session without inventory.approve_count raises | `unit_tests/application/test_count_session_service.py :: test_approve_session_without_permission_raises` |
| approve_session with admin succeeds | `unit_tests/application/test_count_session_service.py :: test_approve_session_with_admin_role_succeeds` |
| OPEN mode count session returns expected_qty | `api_tests/test_count_routes.py :: TestCountRoutes :: test_open_mode_reveals_expected_qty` |
| BLIND mode hides expected_qty (null) | `api_tests/test_count_routes.py :: TestCountRoutes :: test_blind_mode_masks_expected_qty` |
| PUT /count-sessions/{id}/lines/{id} recalculates variance | `api_tests/test_count_routes.py :: TestCountRoutes :: test_update_count_line` |
| GET /count-sessions/{id} not found returns 404 | `api_tests/test_count_routes.py :: TestCountRoutes :: test_get_count_session_not_found_returns_404` |
| POST /count-sessions/ without inventory.count returns 403 | `api_tests/test_count_routes.py :: TestCountRoutes :: test_open_count_session_requires_count_permission` |
| POST /count-sessions/{id}/approve without permission returns 403 | `api_tests/test_count_routes.py :: TestCountRoutes :: test_approve_session_requires_admin_role` |
| POST /count-sessions/{id}/approve with admin returns 200 APPROVED | `api_tests/test_count_routes.py :: TestCountRoutes :: test_approve_session_with_admin_succeeds` |

### Relocations

| Requirement | Test Coverage |
|---|---|
| relocate creates two LedgerEntries and updates balances | `unit_tests/application/test_relocation_service.py :: test_relocate_creates_two_ledger_entries_and_updates_balances` |
| cross-warehouse relocate raises DomainValidationError | `unit_tests/application/test_relocation_service.py :: test_relocate_cross_warehouse_raises_validation_error` |
| POST /inventory/relocations cross-warehouse returns 400 VALIDATION_ERROR | `api_tests/test_relocation_routes.py :: test_create_relocation_cross_warehouse_returns_400` |
| Same-location relocate raises DomainValidationError | `unit_tests/application/test_relocation_service.py :: test_relocate_same_location_raises_validation_error` |
| Zero-quantity relocate raises DomainValidationError | `unit_tests/application/test_relocation_service.py :: test_relocate_zero_quantity_raises_validation_error` |
| Insufficient stock raises InsufficientStockError | `unit_tests/application/test_relocation_service.py :: test_relocate_insufficient_stock_raises_error` |
| Frozen stock raises StockFrozenError | `unit_tests/application/test_relocation_service.py :: test_relocate_frozen_stock_raises_stock_frozen_error` |
| Relocation preserves batch/status partition semantics | `unit_tests/application/test_relocation_service.py :: test_relocate_uses_batch_partition_and_status` |
| POST /inventory/relocations accepts partition fields | `api_tests/test_relocation_routes.py :: test_create_relocation_with_partition_fields_returns_201` |

---

## Prompt 5 — Desktop Shell

| Requirement | Test Coverage |
|---|---|
| ShortcutManager registers all SHORTCUT_MAP bindings | `unit_tests/ui/test_shortcuts.py` |
| Ctrl+F triggers global_search | `unit_tests/ui/test_shortcuts.py :: TestShortcutBindings` |
| Ctrl+Shift+O triggers logout | `unit_tests/ui/test_shortcuts.py :: test_logout_is_ctrl_shift_o` |
| Ctrl+Shift+L opens inventory ledger | `unit_tests/ui/test_shortcuts.py :: test_open_inventory_ledger_is_ctrl_shift_l` |
| SystemTray context menu has restore action | `unit_tests/ui/test_tray.py` |
| SystemTray user label updates on session change | `unit_tests/ui/test_tray.py` |
| WorkspaceCoordinator opens singleton sub-windows | `unit_tests/ui/test_workspace.py :: TestWorkspaceCoordinator` |
| WorkspaceCoordinator close_all closes all windows | `unit_tests/ui/test_workspace.py` |
| Startup checkpoints hydrate AppState pending_checkpoints | `unit_tests/ui/test_app_startup_recovery.py` |
| RecoveryDialog displays checkpoint list | `unit_tests/ui/test_recovery_dialog.py` |
| RecoveryDialog default-checks all checkboxes | `unit_tests/ui/test_recovery_dialog.py` |

---

## Prompt 6 — Primary Screens

| Requirement | Test Coverage |
|---|---|
| DashboardWidget shows username and roles | `unit_tests/ui/test_dashboard.py :: TestDashboardInit` |
| Librarian sees resource and count cards | `unit_tests/ui/test_dashboard.py :: TestDashboardRoleCards` |
| Teacher does not see count card | `unit_tests/ui/test_dashboard.py :: TestDashboardRoleCards :: test_teacher_does_not_see_count_card` |
| Admin sees review card | `unit_tests/ui/test_dashboard.py :: TestDashboardRoleCards :: test_admin_sees_review_card` |
| SignInDialog has username + password fields | `unit_tests/ui/test_sign_in_dialog.py :: TestSignInDialogInit` |
| Password field uses EchoMode.Password | `unit_tests/ui/test_sign_in_dialog.py :: TestSignInDialogInit :: test_password_field_uses_echo_mode_password` |
| Empty username shows error | `unit_tests/ui/test_sign_in_dialog.py :: TestSignInDialogValidation` |
| Successful login populates state and emits signal | `unit_tests/ui/test_sign_in_dialog.py :: TestSignInDialogLoginSuccess` |
| ACCOUNT_LOCKED error shows lockout message | `unit_tests/ui/test_sign_in_dialog.py :: TestSignInDialogLoginError :: test_lockout_error_shows_lockout_message` |
| ResourceListWidget shows 5 columns | `unit_tests/ui/test_resource_screens.py :: TestResourceListInit :: test_table_has_correct_columns` |
| New resource button hidden for Teacher | `unit_tests/ui/test_resource_screens.py :: TestResourceListInit :: test_new_resource_button_hidden_for_teacher` |
| Submit button visible for DRAFT (Librarian) | `unit_tests/ui/test_resource_screens.py :: TestResourceDetailInit :: test_submit_button_visible_for_draft_with_permission` |
| Publish button hidden for DRAFT | `unit_tests/ui/test_resource_screens.py :: TestResourceDetailInit :: test_publish_button_hidden_for_draft` |
| Publish button visible for IN_REVIEW (Reviewer) | `unit_tests/ui/test_resource_screens.py :: TestResourceDetailInit :: test_publish_button_visible_for_in_review_reviewer` |
| Empty notes on publish shows warning | `unit_tests/ui/test_resource_screens.py :: TestResourceDetailInit :: test_reviewer_notes_required_shown_on_empty_publish` |
| BLIND mode hides expected_qty in count session widget | `unit_tests/ui/test_inventory_screens.py :: TestCountSessionWidget :: test_blind_mode_masks_expected_qty` |
| OPEN mode shows expected_qty | `unit_tests/ui/test_inventory_screens.py :: TestCountSessionWidget :: test_open_mode_shows_expected_qty` |
| requires_approval line shows "YES" | `unit_tests/ui/test_inventory_screens.py :: TestCountSessionWidget :: test_requires_approval_line_shows_yes` |
| Approve button visible only for ADMINISTRATOR | `unit_tests/ui/test_inventory_screens.py :: TestCountSessionWidget` |
| Expired session shows notification | `unit_tests/ui/test_inventory_screens.py :: TestCountSessionWidget :: test_expired_session_shows_notification` |
| ADMINISTRATOR has all permissions in AppState | `unit_tests/ui/test_role_visibility.py :: TestAdminPermissions :: test_admin_has_all_permissions` |
| Teacher cannot adjust/count/freeze inventory | `unit_tests/ui/test_role_visibility.py :: TestTeacherPermissions` |
| Reviewer can publish but not adjust inventory | `unit_tests/ui/test_role_visibility.py :: TestReviewerPermissions` |
| Counselor can classify but not freeze | `unit_tests/ui/test_role_visibility.py :: TestCounselorPermissions` |

---

## Prompt 7 — Config Center, Taxonomy, Integration, Update Manager, Audit

### Config Center

| Requirement | Test Coverage |
|---|---|
| upsert_config creates new entry | `unit_tests/application/test_config_service.py :: test_upsert_creates_entry` |
| upsert_config updates existing entry | `unit_tests/application/test_config_service.py :: test_upsert_updates_entry` |
| Empty category raises DomainValidationError | `unit_tests/application/test_config_service.py :: test_empty_category_raises` |
| delete_config removes entry | `unit_tests/application/test_config_service.py :: test_delete_removes_entry` |
| delete_config on is_system=True raises SystemEntryProtectedError | `unit_tests/application/test_config_service.py :: test_delete_system_entry_raises` |
| save_workflow_node persists node | `unit_tests/application/test_config_service.py :: test_save_workflow_node` |
| GET /admin/config/ requires auth | `api_tests/test_config_routes.py :: test_list_config_requires_auth` |
| PUT /admin/config/ requires admin.manage_config | `api_tests/test_config_routes.py :: test_upsert_requires_admin_permission` |
| PUT /admin/config/ with admin creates/updates | `api_tests/test_config_routes.py :: test_upsert_with_admin_returns_200` |
| PUT /admin/config/ with empty value returns 422 | `api_tests/test_config_routes.py :: test_upsert_empty_value_returns_422` |

### Taxonomy

| Requirement | Test Coverage |
|---|---|
| create_category at root has depth=0 | `unit_tests/application/test_taxonomy_service.py :: test_create_root_category` |
| Child category has depth=parent.depth+1 | `unit_tests/application/test_taxonomy_service.py :: test_child_category_depth` |
| path_slug generated from name | `unit_tests/application/test_taxonomy_service.py :: test_path_slug_from_name` |
| Duplicate slug gets UUID suffix | `unit_tests/application/test_taxonomy_service.py :: test_duplicate_slug_gets_suffix` |
| update_category recomputes path_slug | `unit_tests/application/test_taxonomy_service.py :: test_update_recomputes_slug` |
| save/list validation rules | `unit_tests/application/test_taxonomy_service.py :: test_save_list_validation_rules` |
| GET /admin/taxonomy/categories/ requires auth | `api_tests/test_admin_routes.py :: test_list_categories_requires_auth` |
| GET /admin/taxonomy/categories/ any authenticated user | `api_tests/test_admin_routes.py :: test_list_categories_with_auth_returns_200` |
| POST /admin/taxonomy/categories/ requires admin | `api_tests/test_admin_routes.py :: test_create_category_requires_admin` |
| POST /admin/taxonomy/categories/ with admin returns 201 | `api_tests/test_admin_routes.py :: test_create_category_with_admin_returns_201` |
| PUT /admin/taxonomy/categories/{id} updates name+slug | `api_tests/test_admin_routes.py :: test_update_category_with_admin_returns_200` |
| PUT requires admin | `api_tests/test_admin_routes.py :: test_update_category_requires_admin` |
| DELETE /admin/taxonomy/categories/{id} soft-deletes | `api_tests/test_admin_routes.py :: test_deactivate_category_with_admin_returns_204` |
| DELETE requires admin | `api_tests/test_admin_routes.py :: test_deactivate_category_requires_admin` |
| Child category depth=1 | `api_tests/test_admin_routes.py :: test_create_child_category_increments_depth` |
| ?flat=true returns all categories | `api_tests/test_admin_routes.py :: test_list_categories_flat_returns_all` |
| GET /admin/taxonomy/rules/ returns list | `api_tests/test_admin_routes.py :: test_list_taxonomy_rules_with_auth_returns_200` |
| POST /admin/taxonomy/rules/ creates rule | `api_tests/test_admin_routes.py :: test_create_taxonomy_rule_with_admin_returns_201` |
| POST /admin/taxonomy/rules/ requires admin | `api_tests/test_admin_routes.py :: test_create_taxonomy_rule_requires_admin` |
| DELETE /admin/taxonomy/rules/{id} removes rule | `api_tests/test_admin_routes.py :: test_delete_taxonomy_rule_with_admin_returns_204` |

### Integration Surface

| Requirement | Test Coverage |
|---|---|
| create_client returns client + initial key (64-char hex) | `unit_tests/application/test_integration_service.py :: test_create_client_returns_client_and_key` |
| deactivate_client sets is_active=False | `unit_tests/application/test_integration_service.py :: test_deactivate_client` |
| rotate_key creates next key | `unit_tests/application/test_integration_service.py :: test_rotate_creates_next_key` |
| Rotate twice raises KeyRotationError | `unit_tests/application/test_integration_service.py :: test_rotate_twice_raises` |
| commit_rotation promotes next key to active | `unit_tests/application/test_integration_service.py :: test_commit_rotation` |
| write_event with disabled outbox → PENDING status | `unit_tests/application/test_integration_service.py :: test_write_event_disabled_stays_pending` |
| retry marks FAILED after max retries | `unit_tests/application/test_integration_service.py :: test_retry_marks_failed_after_max_retries` |
| GET /integrations/ requires auth | `api_tests/test_integration_routes.py :: test_list_clients_requires_auth` |
| POST /integrations/ requires admin | `api_tests/test_integration_routes.py :: test_create_client_requires_admin_permission` |
| POST /integrations/ creates client with 64-char key | `api_tests/test_integration_routes.py :: test_create_client_with_admin_returns_201` |
| POST /{id}/rotate-key requires admin | `api_tests/test_integration_routes.py :: test_rotate_key_requires_admin` |
| rotate + commit workflow succeeds | `api_tests/test_integration_routes.py :: test_rotate_and_commit_key_succeeds_as_admin` |
| rotate response has is_next=True | `api_tests/test_integration_routes.py :: test_rotate_key_response_has_expected_fields` |
| DELETE /{id} deactivates client | `api_tests/test_integration_routes.py :: test_deactivate_client_with_admin_returns_204` |
| DELETE requires admin | `api_tests/test_integration_routes.py :: test_deactivate_client_requires_admin` |
| GET /events/ requires admin (not librarian) | `api_tests/test_integration_routes.py :: test_list_events_requires_admin_permission` |
| POST /events/{client_id}/emit with admin returns 201 event payload | `api_tests/test_integration_routes.py :: test_emit_event_with_admin_returns_201` |
| POST /events/{client_id}/emit requires admin | `api_tests/test_integration_routes.py :: test_emit_event_requires_admin_permission` |
| POST /events/retry returns result dict | `api_tests/test_integration_routes.py :: test_retry_events_returns_result` |

### Update Manager

| Requirement | Test Coverage |
|---|---|
| import_package validates ZIP manifest | `unit_tests/application/test_update_service.py :: test_import_creates_pending_package` |
| Invalid ZIP raises ManifestValidationError | `unit_tests/application/test_update_service.py :: test_invalid_zip_raises_manifest_error` |
| Missing manifest raises ManifestValidationError | `unit_tests/application/test_update_service.py :: test_missing_manifest_raises` |
| apply_package transitions PENDING → APPLIED | `unit_tests/application/test_update_service.py :: test_apply_transitions_to_applied` |
| rollback restores prior version | `unit_tests/application/test_update_service.py :: test_rollback_restores_prior` |
| rollback without prior version raises RollbackError | `unit_tests/application/test_update_service.py :: test_rollback_without_prior_raises` |
| GET /admin/updates/ requires auth | `api_tests/test_update_routes.py :: test_list_packages_requires_auth` |
| POST /admin/updates/import requires admin | `api_tests/test_update_routes.py :: test_import_requires_admin` |
| POST /admin/updates/import with valid ZIP creates PENDING | `api_tests/test_update_routes.py :: test_import_with_admin_creates_pending` |
| POST /admin/updates/import invalid ZIP returns 422 | `api_tests/test_update_routes.py :: test_import_invalid_zip_returns_422` |
| POST /admin/updates/{id}/apply transitions to APPLIED | `api_tests/test_update_routes.py :: test_apply_transitions_to_applied` |

### Audit Log

| Requirement | Test Coverage |
|---|---|
| list_audit_events supports entity_type filter | `unit_tests/application/test_audit_service.py :: test_filter_by_entity_type` |
| list_security_events returns only LOGIN/ACCOUNT_LOCKED | `unit_tests/application/test_audit_service.py :: test_security_events_filter` |
| list_checkpoint_status excludes COMPLETED | `unit_tests/application/test_audit_service.py :: test_checkpoint_status_excludes_completed` |
| GET /admin/audit/events/ requires admin | `api_tests/test_admin_routes.py :: test_list_audit_events_without_admin_returns_403` |
| GET /admin/audit/events/ with admin returns items list | `api_tests/test_admin_routes.py :: test_list_audit_events_with_admin_returns_200` |
| GET /admin/audit/events/security/ returns 200 | `api_tests/test_admin_routes.py :: test_list_security_events_with_admin_returns_200` |
| GET /admin/audit/checkpoints/ returns list | `api_tests/test_admin_routes.py :: test_list_checkpoints_with_admin_returns_200` |

### Infrastructure (Prompt 7)

| Requirement | Test Coverage |
|---|---|
| OutboxWriter disabled raises OutboxDisabledError | `unit_tests/infrastructure/test_outbox_writer.py :: test_disabled_raises_outbox_disabled_error` |
| OutboxWriter.is_enabled=False when path=None | `unit_tests/infrastructure/test_outbox_writer.py :: test_is_enabled_false_when_no_path` |
| OutboxWriter creates JSON file with event_type in name | `unit_tests/infrastructure/test_outbox_writer.py :: test_creates_json_file_with_naming` |
| BarcodeInputHandler ≤50ms → USB_SCANNER | `unit_tests/infrastructure/test_barcode_input.py` |
| BarcodeInputHandler >50ms resets buffer | `unit_tests/infrastructure/test_barcode_input.py :: test_manual_speed_no_completion` |
| InstrumentationHooks record_startup_time stores ms | `unit_tests/infrastructure/test_instrumentation.py :: test_startup_time_stored` |
| InstrumentationHooks record_memory_sample returns rss/vms | `unit_tests/infrastructure/test_instrumentation.py :: test_memory_sample_returns_keys` |

---

## Prompt 8 — Test Suite Hardening

| Requirement | Test Coverage |
|---|---|
| ValidationResult add_error marks invalid | `unit_tests/application/test_validation.py :: TestValidationResultErrors :: test_add_error_marks_invalid` |
| ValidationResult raise_if_invalid raises DomainValidationError | `unit_tests/application/test_validation.py :: TestValidationResultErrors :: test_raise_if_invalid_raises_domain_validation_error` |
| ValidationResult to_dict returns all errors | `unit_tests/application/test_validation.py :: TestValidationResultErrors :: test_to_dict_returns_all_errors_in_order` |
| FieldError is frozen | `unit_tests/application/test_validation.py :: TestFieldError :: test_field_error_is_frozen` |
| Exception .code attributes correct | `unit_tests/domain/test_exceptions.py` (all test classes) |
| Exception domain-specific fields correct | `unit_tests/domain/test_exceptions.py` (field tests) |
| Exception messages contain identifying info | `unit_tests/domain/test_exceptions.py` (message tests) |

---

## Domain Invariant Tests

The following tests verify system-wide invariants that apply across all prompts.

| Invariant | Test Coverage |
|---|---|
| AuditEvent is a frozen dataclass (immutable) | `unit_tests/domain/test_audit_invariants.py` |
| LedgerEntry is a frozen dataclass (immutable) | `unit_tests/domain/test_audit_invariants.py` |
| CORRECTION entry has reversal_of_id pointing to original | `unit_tests/domain/test_audit_invariants.py` |
| AppendOnlyViolationError raised for non-correction mutations | `unit_tests/domain/test_audit_invariants.py` |
| Revision cap = 10 (MAX_RESOURCE_REVISIONS) | `unit_tests/domain/test_revision_retention.py` |
| ResourceRevision is immutable (frozen dataclass) | `unit_tests/domain/test_revision_retention.py` |
| Revision numbers are sequential and unique per resource | `unit_tests/domain/test_revision_retention.py` |

---

## Error Code → HTTP Status Mapping (Acceptance Checkpoint)

The middleware maps domain error codes to HTTP statuses. These must match the
`api-spec.md` contract exactly.

| Error Code | Expected HTTP Status | Test Coverage |
|---|---|---|
| UNAUTHENTICATED / SESSION_EXPIRED | 401 | `api_tests/test_auth_routes.py` |
| INVALID_CREDENTIALS | 401 | `api_tests/test_auth_routes.py :: TestLogin :: test_login_invalid_password_returns_401` |
| ACCOUNT_LOCKED | 423 | `api_tests/test_auth_routes.py :: TestLogin :: test_login_locked_account_returns_423` |
| INSUFFICIENT_PERMISSION | 403 | `api_tests/test_resource_routes.py :: test_create_resource_without_permission_returns_403` |
| NOT_FOUND | 404 | `api_tests/test_resource_routes.py :: test_get_resource_not_found_returns_404` |
| INVALID_STATE_TRANSITION | 409 | `api_tests/test_resource_routes.py :: test_update_resource_non_draft_returns_409` |
| DUPLICATE_RESOURCE | 409 | `api_tests/test_resource_routes.py :: test_import_file_duplicate_returns_409` |
| VALIDATION_ERROR | 422 | `api_tests/test_resource_routes.py :: test_publish_requires_reviewer_notes_non_empty` |
| Error envelope schema {error: {code, message}} | All errors | `api_tests/test_error_envelopes.py` |

---

## Prompt 9 — Dockerization, Config Hardening, Documentation Synchronization

| Requirement | Test Coverage |
|---|---|
| AppConfig defaults (host=127.0.0.1, port=8765, log=INFO, lan_events="") | `unit_tests/bootstrap/test_config.py :: TestAppConfig :: test_defaults_without_env` |
| DC_DB_PATH default resolves to data/district.db relative to cwd | `unit_tests/bootstrap/test_config.py :: TestAppConfig :: test_db_path_default_contains_data_district` |
| DC_API_HOST env var override | `unit_tests/bootstrap/test_config.py :: TestAppConfig :: test_api_host_override` |
| DC_API_PORT env var parsed as int | `unit_tests/bootstrap/test_config.py :: TestAppConfig :: test_api_port_override` |
| DC_LOG_LEVEL env var override | `unit_tests/bootstrap/test_config.py :: TestAppConfig :: test_log_level_override` |
| DC_LAN_EVENTS_PATH env var override | `unit_tests/bootstrap/test_config.py :: TestAppConfig :: test_lan_events_path_override` |
| Empty DC_LAN_EVENTS_PATH disables OutboxWriter (falsy) | `unit_tests/bootstrap/test_config.py :: TestAppConfig :: test_lan_events_path_empty_string_is_falsy` |
| api_url() returns correct base URL | `unit_tests/bootstrap/test_config.py :: TestAppConfig :: test_api_url_combines_host_and_port` |

---

## Prompt 10 — Static Readiness Audit

| Requirement | Verification |
|---|---|
| All Original Prompt domains implemented or documented in questions.md | Audit 1 sweep — see design.md §9 traceability table |
| Repo structure matches execution_plan.md contract | Audit 2 sweep — all required files present |
| Auth/lockout constants correct (5 attempts, 15 min, 12 char min) | `unit_tests/application/test_auth_service.py`; `domain/policies.py` verified |
| Session token URL-safe random, 8h TTL, in-memory | `application/auth_service.py` (SESSION_TTL_HOURS=8, secrets.token_urlsafe) |
| HMAC replay window = 300s | `infrastructure/hmac_signer.py` (HMAC_SIGN_MAX_AGE_SECONDS=300); `unit_tests/infrastructure/test_hmac_signer.py` |
| Log sanitization active | `infrastructure/logging_config.py` (SanitizingFilter registered on all handlers) |
| Append-only tables protected at repository layer | `infrastructure/repositories.py` (LedgerRepository, AuditRepository — INSERT only) |
| No hardcoded secrets in source | Static grep of `src/` — no literal credentials found |
| Port 8765 consistent across Dockerfile, docker-compose, AppConfig, README, api-spec.md | Audit 5 sweep — all consistent |
| windows-packaging.md marked docs-only, no stale Prompt 5 notes | `docs/windows-packaging.md` Known Limitations section updated in Prompt 9 |
| design.md Section 3 router table matches api/app.py | Updated in Prompt 9 |
| design.md Section 9 traceability paths match actual module layout | Updated in Prompt 10 |

---

## Coverage Configuration

Coverage is configured in `repo/backend/pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "--cov=district_console --cov-report=term-missing"

[tool.coverage.run]
branch = true
source = ["district_console"]

[tool.coverage.report]
fail_under = 90
```

Run the suite via `repo/run_tests.sh`. The test run exits non-zero if coverage
drops below 90% when coverage mode is enabled (for example `repo/run_tests.sh --cov`),
preventing regressions in coverage from being merged.
