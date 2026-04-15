# Unified Audit Report (Strict Static Inspection)

Date: 2026-04-15
Scope: static inspection only (no test/runtime execution)
Workspace root: TASK-135

## 1) Test Coverage Audit

### Method and Scope
- Endpoint source of truth: `repo/backend/src/district_console/api/app.py` and router modules under `repo/backend/src/district_console/api/routers/`.
- Test evidence source: `repo/backend/api_tests/` and `repo/backend/unit_tests/`.
- Coverage rule applied: endpoint covered only when a test sends a request to exact METHOD + resolved PATH and reaches the real route handler.
- True no-mock API rule applied strictly: requires real TCP HTTP layer (uvicorn + loopback), not ASGI short-circuit.

### Backend Endpoint Inventory
Resolved from router mounts in `repo/backend/src/district_console/api/app.py` (lines 57-67) plus per-router decorators.

1. POST /api/v1/auth/login (`repo/backend/src/district_console/api/routers/auth.py`:35)
2. POST /api/v1/auth/logout (`repo/backend/src/district_console/api/routers/auth.py`:62)
3. GET /api/v1/auth/whoami (`repo/backend/src/district_console/api/routers/auth.py`:84)
4. GET /api/v1/resources/ (`repo/backend/src/district_console/api/routers/resources.py`:87)
5. POST /api/v1/resources/ (`repo/backend/src/district_console/api/routers/resources.py`:134)
6. GET /api/v1/resources/{resource_id} (`repo/backend/src/district_console/api/routers/resources.py`:165)
7. PUT /api/v1/resources/{resource_id} (`repo/backend/src/district_console/api/routers/resources.py`:198)
8. POST /api/v1/resources/import/file (`repo/backend/src/district_console/api/routers/resources.py`:242)
9. POST /api/v1/resources/import/csv (`repo/backend/src/district_console/api/routers/resources.py`:275)
10. GET /api/v1/resources/{resource_id}/revisions (`repo/backend/src/district_console/api/routers/resources.py`:297)
11. POST /api/v1/resources/{resource_id}/submit-review (`repo/backend/src/district_console/api/routers/resources.py`:319)
12. POST /api/v1/resources/{resource_id}/publish (`repo/backend/src/district_console/api/routers/resources.py`:353)
13. POST /api/v1/resources/{resource_id}/unpublish (`repo/backend/src/district_console/api/routers/resources.py`:385)
14. POST /api/v1/resources/{resource_id}/classify (`repo/backend/src/district_console/api/routers/resources.py`:417)
15. POST /api/v1/resources/{resource_id}/request-allocation (`repo/backend/src/district_console/api/routers/resources.py`:453)
16. GET /api/v1/inventory/items/ (`repo/backend/src/district_console/api/routers/inventory.py`:123)
17. POST /api/v1/inventory/items/ (`repo/backend/src/district_console/api/routers/inventory.py`:150)
18. GET /api/v1/inventory/items/{item_id} (`repo/backend/src/district_console/api/routers/inventory.py`:179)
19. PUT /api/v1/inventory/items/{item_id} (`repo/backend/src/district_console/api/routers/inventory.py`:198)
20. GET /api/v1/inventory/warehouses/ (`repo/backend/src/district_console/api/routers/inventory.py`:230)
21. POST /api/v1/inventory/warehouses/ (`repo/backend/src/district_console/api/routers/inventory.py`:255)
22. GET /api/v1/inventory/locations/ (`repo/backend/src/district_console/api/routers/inventory.py`:283)
23. POST /api/v1/inventory/locations/ (`repo/backend/src/district_console/api/routers/inventory.py`:315)
24. GET /api/v1/inventory/stock/ (`repo/backend/src/district_console/api/routers/inventory.py`:344)
25. POST /api/v1/inventory/stock/{balance_id}/freeze (`repo/backend/src/district_console/api/routers/inventory.py`:395)
26. POST /api/v1/inventory/stock/{balance_id}/unfreeze (`repo/backend/src/district_console/api/routers/inventory.py`:428)
27. GET /api/v1/inventory/ledger/ (`repo/backend/src/district_console/api/routers/inventory.py`:462)
28. POST /api/v1/inventory/ledger/adjustment (`repo/backend/src/district_console/api/routers/inventory.py`:509)
29. POST /api/v1/inventory/ledger/correction/{entry_id} (`repo/backend/src/district_console/api/routers/inventory.py`:564)
30. GET /api/v1/inventory/count-sessions/ (`repo/backend/src/district_console/api/routers/count_sessions.py`:79)
31. POST /api/v1/inventory/count-sessions/ (`repo/backend/src/district_console/api/routers/count_sessions.py`:116)
32. GET /api/v1/inventory/count-sessions/{session_id} (`repo/backend/src/district_console/api/routers/count_sessions.py`:147)
33. POST /api/v1/inventory/count-sessions/{session_id}/line (`repo/backend/src/district_console/api/routers/count_sessions.py`:187)
34. PUT /api/v1/inventory/count-sessions/{session_id}/lines/{line_id} (`repo/backend/src/district_console/api/routers/count_sessions.py`:229)
35. POST /api/v1/inventory/count-sessions/{session_id}/close (`repo/backend/src/district_console/api/routers/count_sessions.py`:268)
36. POST /api/v1/inventory/count-sessions/{session_id}/approve (`repo/backend/src/district_console/api/routers/count_sessions.py`:294)
37. POST /api/v1/inventory/relocations/ (`repo/backend/src/district_console/api/routers/relocations.py`:51)
38. GET /api/v1/inventory/relocations/ (`repo/backend/src/district_console/api/routers/relocations.py`:112)
39. GET /api/v1/integrations/ (`repo/backend/src/district_console/api/routers/integrations.py`:37)
40. POST /api/v1/integrations/ (`repo/backend/src/district_console/api/routers/integrations.py`:50)
41. DELETE /api/v1/integrations/{client_id} (`repo/backend/src/district_console/api/routers/integrations.py`:70)
42. POST /api/v1/integrations/{client_id}/rotate-key (`repo/backend/src/district_console/api/routers/integrations.py`:86)
43. POST /api/v1/integrations/{client_id}/commit-rotation (`repo/backend/src/district_console/api/routers/integrations.py`:103)
44. GET /api/v1/integrations/events/ (`repo/backend/src/district_console/api/routers/integrations.py`:125)
45. POST /api/v1/integrations/events/{client_id}/emit (`repo/backend/src/district_console/api/routers/integrations.py`:150)
46. POST /api/v1/integrations/events/retry (`repo/backend/src/district_console/api/routers/integrations.py`:183)
47. GET /api/v1/integrations/inbound/status (`repo/backend/src/district_console/api/routers/integration_inbound.py`:21)
48. GET /api/v1/admin/config/ (`repo/backend/src/district_console/api/routers/admin/config.py`:48)
49. DELETE /api/v1/admin/config/{entry_id} (`repo/backend/src/district_console/api/routers/admin/config.py`:69)
50. GET /api/v1/admin/config/workflow-nodes/ (`repo/backend/src/district_console/api/routers/admin/config.py`:94)
51. POST /api/v1/admin/config/workflow-nodes/ (`repo/backend/src/district_console/api/routers/admin/config.py`:108)
52. DELETE /api/v1/admin/config/workflow-nodes/{node_id} (`repo/backend/src/district_console/api/routers/admin/config.py`:133)
53. GET /api/v1/admin/config/templates/ (`repo/backend/src/district_console/api/routers/admin/config.py`:151)
54. PUT /api/v1/admin/config/templates/{name} (`repo/backend/src/district_console/api/routers/admin/config.py`:163)
55. GET /api/v1/admin/config/descriptors/ (`repo/backend/src/district_console/api/routers/admin/config.py`:192)
56. PUT /api/v1/admin/config/descriptors/{key} (`repo/backend/src/district_console/api/routers/admin/config.py`:204)
57. PUT /api/v1/admin/config/{category}/{key} (`repo/backend/src/district_console/api/routers/admin/config.py`:226)
58. GET /api/v1/admin/taxonomy/categories/ (`repo/backend/src/district_console/api/routers/admin/taxonomy.py`:36)
59. POST /api/v1/admin/taxonomy/categories/ (`repo/backend/src/district_console/api/routers/admin/taxonomy.py`:55)
60. PUT /api/v1/admin/taxonomy/categories/{category_id} (`repo/backend/src/district_console/api/routers/admin/taxonomy.py`:74)
61. DELETE /api/v1/admin/taxonomy/categories/{category_id} (`repo/backend/src/district_console/api/routers/admin/taxonomy.py`:92)
62. GET /api/v1/admin/taxonomy/rules/ (`repo/backend/src/district_console/api/routers/admin/taxonomy.py`:112)
63. POST /api/v1/admin/taxonomy/rules/ (`repo/backend/src/district_console/api/routers/admin/taxonomy.py`:126)
64. DELETE /api/v1/admin/taxonomy/rules/{rule_id} (`repo/backend/src/district_console/api/routers/admin/taxonomy.py`:150)
65. GET /api/v1/admin/updates/ (`repo/backend/src/district_console/api/routers/admin/updates.py`:27)
66. POST /api/v1/admin/updates/import (`repo/backend/src/district_console/api/routers/admin/updates.py`:47)
67. POST /api/v1/admin/updates/{package_id}/apply (`repo/backend/src/district_console/api/routers/admin/updates.py`:72)
68. POST /api/v1/admin/updates/{package_id}/rollback (`repo/backend/src/district_console/api/routers/admin/updates.py`:89)
69. GET /api/v1/admin/audit/events/ (`repo/backend/src/district_console/api/routers/admin/audit.py`:31)
70. GET /api/v1/admin/audit/events/security/ (`repo/backend/src/district_console/api/routers/admin/audit.py`:69)
71. GET /api/v1/admin/audit/approval-queue/ (`repo/backend/src/district_console/api/routers/admin/audit.py`:89)
72. GET /api/v1/admin/audit/checkpoints/ (`repo/backend/src/district_console/api/routers/admin/audit.py`:102)

### API Test Mapping Table
Legend:
- Type A = true no-mock HTTP (real TCP/uvicorn)
- Type B = unit-only/indirect HTTP (ASGI in-process transport)

| Endpoint | Covered | Test type | Test files | Evidence (test reference) |
|---|---|---|---|---|
| POST /api/v1/auth/login | yes | Type A | test_real_http.py | test_login_via_real_http |
| POST /api/v1/auth/logout | yes | Type A | test_real_http.py | test_logout_via_real_http |
| GET /api/v1/auth/whoami | yes | Type A | test_real_http.py | test_auth_workflow_via_real_http |
| GET /api/v1/resources/ | yes | Type B | test_resource_routes.py | test_list_resources_returns_paginated |
| POST /api/v1/resources/ | yes | Type A | test_real_http.py | test_create_resource_via_real_http |
| GET /api/v1/resources/{resource_id} | yes | Type A | test_real_http.py | test_resource_not_found_returns_404_via_real_http |
| PUT /api/v1/resources/{resource_id} | yes | Type A | test_real_http_extra.py | test_resource_mutation_workflow_via_real_http |
| POST /api/v1/resources/import/file | yes | Type B | test_resource_routes.py | test_import_file_creates_resource |
| POST /api/v1/resources/import/csv | yes | Type B | test_resource_routes.py | test_import_csv_creates_multiple_resources |
| GET /api/v1/resources/{resource_id}/revisions | yes | Type A | test_real_http_extra.py | test_resource_mutation_workflow_via_real_http |
| POST /api/v1/resources/{resource_id}/submit-review | yes | Type A | test_real_http_extra.py | test_resource_mutation_workflow_via_real_http |
| POST /api/v1/resources/{resource_id}/publish | yes | Type A | test_real_http_extra.py | test_resource_mutation_workflow_via_real_http |
| POST /api/v1/resources/{resource_id}/unpublish | yes | Type A | test_real_http_extra.py | test_resource_mutation_workflow_via_real_http |
| POST /api/v1/resources/{resource_id}/classify | yes | Type A | test_real_http_extra.py | test_resource_mutation_workflow_via_real_http |
| POST /api/v1/resources/{resource_id}/request-allocation | yes | Type A | test_real_http_extra.py | test_resource_mutation_workflow_via_real_http |
| GET /api/v1/inventory/items/ | yes | Type B | test_inventory_routes.py | test_list_items_returns_paginated |
| POST /api/v1/inventory/items/ | yes | Type A | test_real_http.py | test_create_inventory_item_via_real_http |
| GET /api/v1/inventory/items/{item_id} | yes | Type A | test_real_http_extra.py | test_inventory_mutation_workflow_via_real_http |
| PUT /api/v1/inventory/items/{item_id} | yes | Type A | test_real_http_extra.py | test_inventory_mutation_workflow_via_real_http |
| GET /api/v1/inventory/warehouses/ | yes | Type A | test_real_http.py | test_list_warehouses_via_real_http |
| POST /api/v1/inventory/warehouses/ | yes | Type A | test_real_http_extra.py | test_inventory_mutation_workflow_via_real_http |
| GET /api/v1/inventory/locations/ | yes | Type A | test_real_http_extra.py | test_inventory_mutation_workflow_via_real_http |
| POST /api/v1/inventory/locations/ | yes | Type A | test_real_http_extra.py | test_inventory_mutation_workflow_via_real_http |
| GET /api/v1/inventory/stock/ | yes | Type A | test_real_http_extra.py | test_inventory_mutation_workflow_via_real_http |
| POST /api/v1/inventory/stock/{balance_id}/freeze | yes | Type A | test_real_http_extra.py | test_inventory_mutation_workflow_via_real_http |
| POST /api/v1/inventory/stock/{balance_id}/unfreeze | yes | Type A | test_real_http_extra.py | test_inventory_mutation_workflow_via_real_http |
| GET /api/v1/inventory/ledger/ | yes | Type A | test_real_http_extra.py | test_inventory_mutation_workflow_via_real_http |
| POST /api/v1/inventory/ledger/adjustment | yes | Type A | test_real_http_extra.py | test_inventory_mutation_workflow_via_real_http |
| POST /api/v1/inventory/ledger/correction/{entry_id} | yes | Type A | test_real_http_extra.py | test_inventory_mutation_workflow_via_real_http |
| GET /api/v1/inventory/count-sessions/ | yes | Type A | test_real_http_extra.py | test_count_and_relocation_workflow_via_real_http |
| POST /api/v1/inventory/count-sessions/ | yes | Type A | test_real_http_extra.py | test_count_and_relocation_workflow_via_real_http |
| GET /api/v1/inventory/count-sessions/{session_id} | yes | Type A | test_real_http_extra.py | test_count_and_relocation_workflow_via_real_http |
| POST /api/v1/inventory/count-sessions/{session_id}/line | yes | Type A | test_real_http_extra.py | test_count_and_relocation_workflow_via_real_http |
| PUT /api/v1/inventory/count-sessions/{session_id}/lines/{line_id} | yes | Type A | test_real_http_extra.py | test_count_and_relocation_workflow_via_real_http |
| POST /api/v1/inventory/count-sessions/{session_id}/close | yes | Type A | test_real_http_extra.py | test_count_and_relocation_workflow_via_real_http |
| POST /api/v1/inventory/count-sessions/{session_id}/approve | yes | Type A | test_real_http_extra.py | test_count_and_relocation_workflow_via_real_http |
| POST /api/v1/inventory/relocations/ | yes | Type A | test_real_http_extra.py | test_count_and_relocation_workflow_via_real_http |
| GET /api/v1/inventory/relocations/ | yes | Type A | test_real_http_extra.py | test_count_and_relocation_workflow_via_real_http |
| GET /api/v1/integrations/ | yes | Type A | test_real_http.py | test_list_integrations_via_real_http |
| POST /api/v1/integrations/ | yes | Type A | test_real_http.py | test_create_integration_client_via_real_http |
| DELETE /api/v1/integrations/{client_id} | yes | Type A | test_real_http_extra.py | test_integrations_hmac_and_events_via_real_http |
| POST /api/v1/integrations/{client_id}/rotate-key | yes | Type A | test_real_http_extra.py | test_integrations_hmac_and_events_via_real_http |
| POST /api/v1/integrations/{client_id}/commit-rotation | yes | Type A | test_real_http_extra.py | test_integrations_hmac_and_events_via_real_http |
| GET /api/v1/integrations/events/ | yes | Type A | test_real_http_extra.py | test_integrations_hmac_and_events_via_real_http |
| POST /api/v1/integrations/events/{client_id}/emit | yes | Type A | test_real_http_extra.py | test_integrations_hmac_and_events_via_real_http |
| POST /api/v1/integrations/events/retry | yes | Type A | test_real_http_extra.py | test_integrations_hmac_and_events_via_real_http |
| GET /api/v1/integrations/inbound/status | yes | Type A | test_real_http_extra.py | test_integrations_hmac_and_events_via_real_http |
| GET /api/v1/admin/config/ | yes | Type A | test_real_http.py | test_list_config_with_valid_token_via_real_http |
| DELETE /api/v1/admin/config/{entry_id} | yes | Type A | test_real_http_extra.py | test_admin_config_taxonomy_updates_and_audit_misc_via_real_http |
| GET /api/v1/admin/config/workflow-nodes/ | yes | Type A | test_real_http.py | test_list_workflow_nodes_via_real_http |
| POST /api/v1/admin/config/workflow-nodes/ | yes | Type A | test_real_http_extra.py | test_admin_config_taxonomy_updates_and_audit_misc_via_real_http |
| DELETE /api/v1/admin/config/workflow-nodes/{node_id} | yes | Type A | test_real_http_extra.py | test_admin_config_taxonomy_updates_and_audit_misc_via_real_http |
| GET /api/v1/admin/config/templates/ | yes | Type A | test_real_http.py | test_list_templates_via_real_http |
| PUT /api/v1/admin/config/templates/{name} | yes | Type A | test_real_http.py | test_upsert_template_via_real_http |
| GET /api/v1/admin/config/descriptors/ | yes | Type A | test_real_http.py | test_list_descriptors_via_real_http |
| PUT /api/v1/admin/config/descriptors/{key} | yes | Type A | test_real_http.py | test_upsert_descriptor_via_real_http |
| PUT /api/v1/admin/config/{category}/{key} | yes | Type A | test_real_http.py | test_upsert_config_via_real_http |
| GET /api/v1/admin/taxonomy/categories/ | yes | Type A | test_real_http.py | test_list_categories_via_real_http |
| POST /api/v1/admin/taxonomy/categories/ | yes | Type A | test_real_http.py | test_create_category_via_real_http |
| PUT /api/v1/admin/taxonomy/categories/{category_id} | yes | Type A | test_real_http_extra.py | test_admin_config_taxonomy_updates_and_audit_misc_via_real_http |
| DELETE /api/v1/admin/taxonomy/categories/{category_id} | yes | Type A | test_real_http_extra.py | test_admin_config_taxonomy_updates_and_audit_misc_via_real_http |
| GET /api/v1/admin/taxonomy/rules/ | yes | Type A | test_real_http.py | test_list_taxonomy_rules_via_real_http |
| POST /api/v1/admin/taxonomy/rules/ | yes | Type A | test_real_http_extra.py | test_admin_config_taxonomy_updates_and_audit_misc_via_real_http |
| DELETE /api/v1/admin/taxonomy/rules/{rule_id} | yes | Type A | test_real_http_extra.py | test_admin_config_taxonomy_updates_and_audit_misc_via_real_http |
| GET /api/v1/admin/updates/ | yes | Type A | test_real_http.py | test_list_update_packages_via_real_http |
| POST /api/v1/admin/updates/import | yes | Type A | test_real_http_extra.py | test_admin_config_taxonomy_updates_and_audit_misc_via_real_http |
| POST /api/v1/admin/updates/{package_id}/apply | yes | Type A | test_real_http_extra.py | test_admin_config_taxonomy_updates_and_audit_misc_via_real_http |
| POST /api/v1/admin/updates/{package_id}/rollback | yes | Type A | test_real_http_extra.py | test_admin_config_taxonomy_updates_and_audit_misc_via_real_http |
| GET /api/v1/admin/audit/events/ | yes | Type A | test_real_http.py | test_list_audit_events_via_real_http |
| GET /api/v1/admin/audit/events/security/ | yes | Type A | test_real_http_extra.py | test_admin_config_taxonomy_updates_and_audit_misc_via_real_http |
| GET /api/v1/admin/audit/approval-queue/ | yes | Type A | test_real_http_extra.py | test_admin_config_taxonomy_updates_and_audit_misc_via_real_http |
| GET /api/v1/admin/audit/checkpoints/ | yes | Type A | test_real_http.py | test_list_checkpoints_via_real_http |

### API Test Classification

1. True No-Mock HTTP
- `repo/backend/api_tests/test_real_http.py` (uvicorn loopback fixture `real_http_url` in `repo/backend/api_tests/conftest.py`:276)
- `repo/backend/api_tests/test_real_http_extra.py` (same fixture)

2. HTTP with Mocking
- None detected by static scan for explicit mocking constructs in `repo/backend/api_tests`.
- Evidence: no matches for `monkeypatch`, `patch(`, `MagicMock`, `AsyncMock`, `dependency_overrides`.

3. Non-HTTP (unit/integration without HTTP)
- `repo/backend/api_tests/test_schema_contracts.py` (pure Pydantic contract tests)
- Non-HTTP section in `repo/backend/api_tests/test_error_envelopes.py` (model-level tests at top of file)

Additional strict note:
- Most API files are HTTP tests but in-process ASGI transport (`http_client` fixture in `repo/backend/api_tests/conftest.py`:173-182). They are endpoint tests, but they do not satisfy the strict true no-mock HTTP-over-TCP definition.

### Mock Detection Findings
- API tests: no explicit mocking/stubbing APIs found.
- Therefore no endpoint was downgraded to "HTTP with mocking" due to explicit mock constructs.
- Unit tests may still use test doubles in places (not part of API true-no-mock classification).

### Coverage Summary
- Total endpoints: 72
- Endpoints with HTTP tests (any HTTP transport): 72
- Endpoints with true no-mock HTTP tests (real TCP): 68

Computed metrics:
- HTTP coverage = 72/72 = 100.00%
- True API coverage = 68/72 = 94.44%

Endpoints covered only by in-process ASGI HTTP (not true TCP):
- GET /api/v1/resources/
- POST /api/v1/resources/import/file
- POST /api/v1/resources/import/csv
- GET /api/v1/inventory/items/

### Unit Test Summary
Test file inventory (high-level):
- Application layer: auth, RBAC, resource, inventory, count sessions, relocation, config, taxonomy, integration, update, audit, validation
- Infrastructure layer: repositories, DB, migrations, lock manager, checkpoint store, HMAC signer, rate limiter, outbox, instrumentation, logging, barcode input
- Domain layer: enums, policies, exceptions, scope entities, audit invariants, revision retention
- Bootstrap layer: config, container wiring, entrypoint, key validation, recovery
- UI layer: startup/recovery, dashboard, inventory/resource screens, shortcuts, tray, sign-in, role visibility, workspace, dialogs, context menus

Important modules with no clearly dedicated unit test file (static naming inference):
- `repo/backend/src/district_console/api/app.py`
- `repo/backend/src/district_console/ui/client.py`
- `repo/backend/src/district_console/ui/theme.py`
- `repo/backend/src/district_console/ui/state.py`

### API Observability Check
Result: mostly strong.
- Endpoint clarity: explicit method + concrete path usage across API tests.
- Request input visibility: bodies/params are explicit in most tests.
- Response visibility: status and response-body assertions are explicit and non-trivial in core route tests.

Weak spots:
- Some broad workflow tests in `test_real_http_extra.py` validate many endpoints in one function, reducing per-endpoint fault isolation.

### Tests Check
- Success paths: extensive across all route groups.
- Failure paths: strong coverage (401/403/404/409/422 and domain-specific failures).
- Edge cases: present (HMAC replay/timestamp, update package checksum/path traversal, scope enforcement).
- Validation depth: present in auth/config/resource/inventory/update tests.
- Auth/permissions: strong role and scope coverage.
- Integration boundaries: present via real TCP tests and in-process HTTP suites.
- Superficial assertions: limited; most tests assert body shape and key fields.

`run_tests.sh` check:
- Docker-based execution enforced (`docker compose`/`docker-compose` only): PASS.
- Host-local dependency installation required: NOT DETECTED.

### End-to-End Expectation Check
Project type is desktop app with local backend API (not browser fullstack).
- No FE<->BE browser E2E is expected.
- Compensating evidence is strong: broad API coverage + substantial unit coverage + workflow tests.

### Test Coverage Score (0-100)
Score: 93/100

### Score Rationale
- + Full endpoint HTTP coverage (100%).
- + Very high true no-mock TCP coverage (94.44%).
- + Strong negative-path/security/scope/update-package testing depth.
- + No explicit API-layer mocking/stubbing detected.
- - Four endpoints are not covered by true TCP tests (ASGI-only).
- - A few important runtime modules do not show clearly dedicated unit tests by filename.

### Key Gaps
1. Missing true TCP coverage for:
- GET /api/v1/resources/
- POST /api/v1/resources/import/file
- POST /api/v1/resources/import/csv
- GET /api/v1/inventory/items/
2. Some high-value route groups are validated in large multi-step tests; failures may be harder to localize quickly.

### Confidence & Assumptions
- Confidence: high.
- Assumptions:
  - Endpoint inventory is derived from static decorators and include_router prefixes only.
  - No dynamic route registration outside inspected files.
  - Test classification is based on visible transport setup and explicit mock-detection patterns.

Final verdict (Test Coverage Audit): PASS WITH STRICT GAPS

---

## 2) README Audit

### README Location Check
- Required file exists: `repo/README.md`.

### Project Type Detection
- Declared near top: "Project type: desktop application with local backend API." (`repo/README.md`)
- Inferred type: desktop (clear, no fallback needed).

### Hard Gates

1. Formatting
- Clean markdown structure with clear sectioning and tables.
- Result: PASS

2. Startup Instructions
- Desktop startup instructions present and Docker-contained:
  - `cd repo`
  - `docker compose up app`
- Also documents compatibility fallback command.
- Result: PASS

3. Access Method
- API URL and port provided: `http://127.0.0.1:8765`.
- Desktop launch method via Docker included.
- Result: PASS

4. Verification Method
- Explicit curl-based verification flow provided (login, whoami, admin endpoint).
- Expected outcomes listed.
- Desktop verification notes included.
- Result: PASS

5. Environment Rules (strict)
- Explicitly forbids host-local `npm install`, `pip install`, `apt-get`, manual DB setup in acceptance path.
- Docker-first execution path documented.
- Result: PASS

6. Demo Credentials (auth-conditional)
- Auth clearly exists.
- README provides username/password across roles: Administrator, Librarian, Reviewer, Teacher, Counselor.
- Result: PASS

### Engineering Quality
- Tech stack clarity: strong.
- Architecture explanation: strong layered model and constraints.
- Testing instructions: comprehensive and Docker-first.
- Security/roles: clearly documented.
- Workflow and presentation quality: high.

### High Priority Issues
- None.

### Medium Priority Issues
- None.

### Low Priority Issues
- README mixes "desktop launch" and API-first verification emphasis; acceptable but could be tightened around primary operator journey.

### Hard Gate Failures
- None.

### README Verdict
PASS

---

## Final Verdicts
- Test Coverage Audit: PASS WITH STRICT GAPS
- README Audit: PASS
