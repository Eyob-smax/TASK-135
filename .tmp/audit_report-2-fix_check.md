# Audit Report 2 Fix Check - Round 2

## Static Check Boundary
- Input baseline: .tmp/audit_report-2.md (Section 5 issues list).
- Method: static-only re-verification of current repository state.
- Not performed: runtime execution, Docker, tests, external services.

## Round 2 Summary
- Prior issues checked: 8
- Fixed: 7
- Not Fixed: 1(OVER-RIDDEN)
- Partially Fixed: 0

## Issue-by-Issue Status

### 1) Delivery modality deviates from signed MSI requirement
- Prior severity: Blocker
- Status: Not Fixed
- Evidence:
  - prompt.md:1
  - docs/windows-packaging.md:3
  - docs/windows-packaging.md:4
  - repo/README.md:75
  - repo/README.md:250
  - File search for MSI artifact in workspace: none found
- Conclusion:
  - Delivery remains Docker-first with MSI documented as reference/future, so the original signed MSI delivery requirement is still not satisfied.

### 2) Object-level scope enforcement missing on resource mutation endpoints
- Prior severity: High
- Status: Fixed
- Evidence (route implementation):
  - repo/backend/src/district_console/api/routers/resources.py:324
  - repo/backend/src/district_console/api/routers/resources.py:358
  - repo/backend/src/district_console/api/routers/resources.py:390
  - repo/backend/src/district_console/api/routers/resources.py:422
  - repo/backend/src/district_console/api/routers/resources.py:458
- Evidence (coverage added):
  - repo/backend/api_tests/test_scope_enforcement.py:860
  - repo/backend/api_tests/test_scope_enforcement.py:891
  - repo/backend/api_tests/test_scope_enforcement.py:922
  - repo/backend/api_tests/test_scope_enforcement.py:953
  - repo/backend/api_tests/test_scope_enforcement.py:984
- Conclusion:
  - Scope checks are now present on all previously flagged resource mutation routes, with targeted denial tests.

### 3) Resource scope matching ignored scope type
- Prior severity: High
- Status: Fixed
- Evidence:
  - repo/backend/src/district_console/api/routers/resources.py:111
  - repo/backend/src/district_console/infrastructure/repositories.py:603
  - repo/backend/src/district_console/infrastructure/repositories.py:604
  - repo/backend/api_tests/test_scope_enforcement.py:1014
- Conclusion:
  - Authorization and filtering now use scope pairs, and a scope-type collision regression test exists.

### 4) Update package integrity verification incomplete
- Prior severity: High
- Status: Fixed
- Evidence (implementation):
  - repo/backend/src/district_console/application/update_service.py:163
  - repo/backend/src/district_console/application/update_service.py:220
  - repo/backend/src/district_console/application/update_service.py:222
  - repo/backend/src/district_console/application/update_service.py:223
  - repo/backend/src/district_console/application/update_service.py:227
- Evidence (tests):
  - repo/backend/unit_tests/application/test_update_service.py:217
  - repo/backend/unit_tests/application/test_update_service.py:240
  - repo/backend/api_tests/test_update_routes.py:139
  - repo/backend/api_tests/test_update_routes.py:166
- Conclusion:
  - Manifest parity and undeclared-file rejection are now enforced and covered.

### 5) Hardcoded key-encryption secret in compose
- Prior severity: High
- Status: Fixed
- Evidence:
  - repo/docker-compose.yml:22
  - repo/docker-compose.yml:38
  - repo/README.md:78
  - repo/README.md:83
- Conclusion:
  - Secret is now required from environment instead of hardcoded value.

### 6) Revision retention semantics inconsistent with last-10 requirement
- Prior severity: Medium
- Status: Fixed
- Evidence:
  - repo/backend/src/district_console/application/resource_service.py:341
  - repo/backend/src/district_console/infrastructure/repositories.py:695
  - repo/backend/unit_tests/application/test_resource_service.py:183
  - repo/backend/src/district_console/domain/entities/resource.py:53
- Conclusion:
  - Rolling window behavior is implemented by pruning oldest revision at cap.

### 7) Documentation readiness statements internally inconsistent
- Prior severity: Medium
- Status: Fixed
- Evidence:
  - repo/README.md:75
  - repo/README.md:230
  - repo/README.md:215
- Conclusion:
  - Prior contradiction about deferred execution vs completion is removed; README is now internally consistent.

### 8) Installer metadata had external help URL (offline drift)
- Prior severity: Low
- Status: Fixed
- Evidence:
  - repo/installer/district-console.wxs:122
  - repo/installer/district-console.wxs:123
- Conclusion:
  - ARP external help link entry is no longer present.

## Final Round 2 Verdict
- Partial
- Reason:
  - 7 of 8 previously reported issues are fixed.
  - The blocker about signed MSI delivery alignment remains open.
