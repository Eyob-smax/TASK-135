# Static Fix Check Round 4 for audit_report-1.md

## Scope
- Static verification only (no implementation, no runtime execution in this pass).
- Baseline reviewed: .tmp/audit_report-1.md Section 5 issues (Blocker, High, Medium).

## Round-4 Summary
- Blocker: not technically fixed (documented policy override exists).
- High: 2 fixed.
- Medium: 2 fixed.

## Detailed Results

### 1) [Blocker] Signed MSI deliverable not actually delivered
- Baseline: Fail
- Round-4 status: Not Fixed (Policy Override Present)
- Evidence:
  - docs/windows-packaging.md:3 (Dockerized delivery is active acceptance path)
  - docs/windows-packaging.md:4 (MSI guide is reference-only)
  - docs/windows-packaging.md:17 (MSI still described as native distribution artifact)
- Assessment:
  - This remains a governance/policy override, not a technical closure of signed MSI artifact delivery.

### 2) [High] Resource-level data-scope isolation structurally under-implemented
- Baseline: Fail
- Round-4 status: Fixed
- Evidence:
  - repo/backend/database/schema_snapshot.sql:123 (owner_scope_type present)
  - repo/backend/database/schema_snapshot.sql:124 (owner_scope_ref_id present)
  - repo/backend/src/district_console/api/schemas.py:102 and repo/backend/src/district_console/api/schemas.py:103 (create request accepts ownership fields)
  - repo/backend/src/district_console/api/routers/resources.py:111 (list applies allowed_scope_ref_ids filtering)
  - repo/backend/src/district_console/api/routers/resources.py:185 (GET object-level scope check)
  - repo/backend/src/district_console/api/routers/resources.py:223 and repo/backend/src/district_console/api/routers/resources.py:224 (UPDATE object-level scope check)
  - repo/backend/api_tests/test_scope_enforcement.py:751 and repo/backend/api_tests/test_scope_enforcement.py:788 (list hidden/visible scope tests)
  - repo/backend/api_tests/test_scope_enforcement.py:819 (GET cross-scope denial)
  - repo/backend/api_tests/test_scope_enforcement.py:848 (PUT cross-scope denial)
- Residual note:
  - owner_scope_ref_id is polymorphic and enforced primarily at application level (no single DB FK possible in SQLite for this polymorphic relation).
- Assessment:
  - The original structural and endpoint-enforcement gap is now addressed in schema, route logic, and scope-enforcement tests.

### 3) [High] UI/API contract mismatch likely breaks count-session open workflow
- Baseline: Fail
- Round-4 status: Fixed
- Evidence:
  - repo/backend/src/district_console/api/routers/inventory.py:230 (warehouses endpoint returns paginated envelope)
  - repo/backend/src/district_console/ui/screens/inventory/count_session.py:229 (UI consumes items envelope)
  - repo/backend/api_tests/test_inventory_routes.py:161 (explicit warehouses envelope contract test)
- Assessment:
  - The previously identified warehouse payload mismatch is aligned and regression-covered.

### 4) [Medium] API docs inconsistent audit-security endpoint definitions
- Baseline: Partial Fail
- Round-4 status: Fixed
- Evidence:
  - docs/api-spec.md:304 (documents /events/security/)
  - docs/api-spec.md:659 (documents /api/v1/admin/audit/events/security/)
- Assessment:
  - Documentation is consistent with the implemented audit-security route shape.

### 5) [Medium] Local-only API exposure default, not strict hard lock
- Baseline: Suspected Risk (Partial Fail)
- Round-4 status: Fixed
- Evidence:
  - repo/backend/src/district_console/bootstrap/config.py:14 (loopback allow-list)
  - repo/backend/src/district_console/bootstrap/config.py:55 and repo/backend/src/district_console/bootstrap/config.py:56 (non-loopback validation)
  - repo/backend/unit_tests/bootstrap/test_config.py:36 (non-loopback host raises ValueError)
  - repo/backend/unit_tests/bootstrap/test_config.py:42 and repo/backend/unit_tests/bootstrap/test_config.py:48 (loopback variants accepted)
- Assessment:
  - Strict loopback enforcement is implemented and test-covered.

## Final Round-4 Classification
- Fixed: 4
- Not Fixed (policy-overridden): 1

## Static-Only Caveat
- This report is based on static code/document inspection only and does not claim runtime behavior validation.
