# District Resource & Inventory Operations Console

A fully offline Windows 11 desktop application for K-12 organizations to manage
reading resources, physical inventory, and administrative operations.

---

## Stack

| Component | Technology |
|-----------|------------|
| Desktop UI | PyQt6 |
| Local REST API | FastAPI on `127.0.0.1:8765` |
| Persistence | SQLite ≥ 3.39 (WAL mode, FK enforcement) |
| ORM / Migrations | SQLAlchemy 2.x + Alembic |
| Password Hashing | Argon2id (argon2-cffi) |
| Background Scheduling | APScheduler 3.x |
| Language | Python 3.10 |
| Test Framework | pytest, pytest-cov, pytest-qt, pytest-asyncio, httpx |
| Containerization | Docker + docker-compose (acceptance path) |

---

## Repository Structure

```
TASK-135/
├── docs/
│   ├── design.md                   System architecture and sequence flows
│   ├── api-spec.md                 Local REST API specification
│   └── windows-packaging.md        Future MSI build guide (docs-only)
├── repo/
│   ├── README.md                   This file
│   ├── docker-compose.yml          Container services (app + test)
│   ├── run_tests.sh                Docker-first test runner
│   └── backend/
│       ├── Dockerfile              Python 3.10-slim + Qt deps
│       ├── pyproject.toml          Package metadata and dependency bounds
│       ├── requirements.txt        Runtime dependencies
│       ├── requirements-dev.txt    Development and test dependencies
│       ├── alembic.ini             Alembic migration configuration
│       ├── database/
│       │   ├── migrations/         Alembic migration scripts
│       │   ├── seeds/              Reference data SQL
│       │   └── schema_snapshot.sql Human-readable full DDL
│       ├── unit_tests/             Non-API tests (domain, security, services, UI)
│       ├── api_tests/              REST/integration tests
│       └── src/district_console/
│           ├── ui/                 PyQt6 windows, dialogs, tray, shortcuts
│           ├── application/        Use-case orchestration services
│           ├── domain/             Entities, enums, policies (pure Python)
│           │   └── entities/       Domain entity dataclasses
│           ├── infrastructure/     SQLite repos, HMAC, checkpointing, locking
│           ├── api/                FastAPI routers and Pydantic schemas
│           ├── bootstrap/          Startup composition and config loading
│           └── packaging/          Windows MSI documentation helpers
├── sessions/                       Do not modify
├── prompt.md
├── execution_plan.md
└── metadata.json
```

---

## Offline and Local Constraints

- **No internet access** is used or required at any time.
- The embedded REST service is bound to `127.0.0.1:8765` (loopback only).
- Outbound webhook events are written as JSON files to a configurable LAN-shared folder path (`DC_LAN_EVENTS_PATH`). If unset, outbound events are disabled.
- All data is stored in a single local SQLite file (default: `data/district.db`).
- Updates are applied via offline package import through the admin UI; there is no auto-update mechanism.

---

## Running the Application (Docker)

The Docker services include a runtime default key for local development/testing.
You may still override it by setting `DC_KEY_ENCRYPTION_KEY` in your shell.

```bash
cd repo
docker compose up app
```

The application starts the embedded FastAPI service on `http://127.0.0.1:8765`. The PyQt UI runs in offscreen mode inside the container; for native Windows use, run the application directly with Python 3.10.

---

## Running Tests

Tests are run exclusively through the Docker container. Do not invoke pytest directly on the host.

```bash
cd repo
./run_tests.sh              # Default backend suite (api + backend unit dirs)
./run_tests.sh unit         # Backend unit tests only
./run_tests.sh api          # API/integration tests only
./run_tests.sh --cov        # Enable coverage reporting + fail-under gate
./run_tests.sh -k "auth"    # Run tests matching a keyword (forwarded to pytest)
```

The default run excludes `backend/unit_tests/ui/` because those tests depend on
Qt widget/runtime conditions that are not part of the backend acceptance path.

### Test layout

| Folder | Contents |
|---|---|
| `backend/unit_tests/domain/` | Enums, policies, entity invariants, exception hierarchy |
| `backend/unit_tests/application/` | Service logic: auth, RBAC, resource, inventory, count, relocation, config, taxonomy, integration, update, audit, validation |
| `backend/unit_tests/infrastructure/` | HMAC, rate limiter, lock manager, logging sanitiser, checkpoint, outbox, barcode, instrumentation |
| `backend/unit_tests/ui/` | Qt widgets (pytest-qt, offscreen): shell, shortcuts, tray, workspace, dialogs, primary screens, role visibility |
| `backend/api_tests/` | FastAPI routes via httpx ASGI transport: auth, resources, inventory, count sessions, relocations, config, taxonomy, integrations, updates, audit |

### Coverage

Coverage is measured over `src/district_console` with branch coverage enabled when
`--cov` is passed. In that mode, the run **fails if coverage drops below 90%**
(enforced by `[tool.coverage.report] fail_under = 90` in `pyproject.toml`).

A requirement-to-test traceability matrix is maintained at [`docs/traceability.md`](../docs/traceability.md).

---

## Architecture Overview

The application uses a strict layered architecture:

```
UI (PyQt6)           ← presentation only, delegates to application layer
Application          ← use-case services, orchestrates domain + infrastructure
Domain               ← pure Python entities, enums, policies, exceptions
Infrastructure       ← SQLAlchemy ORM, Alembic, locking, HMAC, checkpointing
API (FastAPI)        ← local REST routers, Pydantic schemas, middleware
Bootstrap            ← startup composition, config, dependency wiring
```

No layer may import upward (UI cannot import from Infrastructure directly; API cannot contain persistence logic).

---

## Primary Roles

| Role | Key Capabilities |
|------|-----------------|
| Administrator | Full system access, user management, config center, audit log |
| Librarian | Resource import/cataloging, inventory management, count sessions |
| Teacher | Resource viewing, classroom allocation requests |
| Counselor | Timeliness and audience classification of student-facing materials |
| Reviewer | Review workflow (submit-review, publish, unpublish) |

---

## Security

| Concern | Implementation |
|---------|---------------|
| Password hashing | Argon2id via argon2-cffi (never plaintext or reversible) |
| Minimum password length | 12 characters |
| Login lockout | 5 failed attempts → 15-minute lockout |
| Session tokens | URL-safe random 43-char tokens; 8-hour TTL; in-memory store |
| RBAC | 5 roles; per-endpoint `require_permission()` dependency |
| Scope enforcement | 4 scope levels: SCHOOL, DEPARTMENT, CLASS, INDIVIDUAL |
| Integration signing | HMAC-SHA256; 5-minute replay window; active+next key rotation |
| Rate limiting | 60 requests/minute per integration client (fixed window) |
| Record locking | DB-backed advisory locks; 5-minute TTL; refresh-able |
| Log sanitization | `SanitizingFilter` redacts passwords, keys, tokens in all logs |
| Append-only tables | `audit_events` and `ledger_entries` never receive UPDATE/DELETE |
| No hardcoded credentials | All keys stored in DB; no secrets in source code |

---

## Desktop Module Layout

```
src/district_console/ui/
├── app.py                  run_application() entry point, lifecycle wiring
├── state.py                AppState — session token, roles, permission checks
├── client.py               ApiClient — synchronous httpx REST client
├── theme.py                Windows 11 Fluent palette, high-DPI config
├── shortcuts.py            ShortcutManager — global keyboard shortcuts
├── tray.py                 SystemTray — minimize-to-tray, balloon notifications
├── shell/
│   ├── main_window.py      MDI shell, navigation dock, menu bar, toolbar
│   ├── sign_in_dialog.py   Login dialog with error/lockout handling
│   └── workspace.py        WorkspaceCoordinator — singleton MDI sub-windows
├── widgets/
│   ├── loading_overlay.py  In-flight API call overlay
│   ├── notification_bar.py Dismissible top banner (info/success/warning/error)
│   ├── empty_state.py      Empty list placeholder widget
│   ├── lock_conflict_dialog.py  RecordLocked conflict prompt
│   ├── recovery_dialog.py  Checkpoint resume dialog (shown at startup)
│   └── barcode_input_field.py  QLineEdit with USB scanner timing detection
├── utils/
│   └── async_worker.py     ApiWorker(QThread) — off-main-thread API calls
└── screens/
    ├── dashboard.py        Role-filtered summary cards + quick launch
    ├── resources/          Resource list, detail editor, review queue
    ├── inventory/          Ledger viewer, item detail, count session workspace
    ├── users/              Session status panel
    ├── teacher/            Classroom allocation / resource request view
    ├── counselor/          Age range + timeliness classification editor
    ├── approval/           Approval inbox (resource reviews + count approvals)
    └── admin/              Admin-only screens (ADMINISTRATOR role)
        ├── config_center.py       Configuration dictionary, workflow, templates
        ├── taxonomy_admin.py      Category tree + validation rules
        ├── integration_admin.py   Integration clients + key rotation + event log
        ├── update_manager.py      Offline update package import/apply/rollback
        └── audit_log_viewer.py    Immutable audit trail + security + checkpoints
```

## Development Status

| Prompt | Scope | Status |
|--------|-------|--------|
| 1 | Architecture framing, repo contract, planning artifacts | Complete |
| 2 | Domain model, SQLite schema, API contract | Complete |
| 3 | Security foundation, RBAC, ORM, auth routes | Complete |
| 4 | Core workflows: resource lifecycle, ledger engine, count sessions, relocations | Complete |
| 5 | Desktop shell, MDI workspace, tray, shortcuts, feedback widgets | Complete |
| 6 | Primary screens: dashboard, resources, inventory, count sessions, approvals | Complete |
| 7 | Config center, taxonomy admin, integration surface, update manager, audit log, barcode scanner, resilience instrumentation | Complete |
| 8 | Test suite hardening, coverage enforcement, traceability matrix, run_tests.sh | Complete |
| 9 | Dockerization, config hardening, documentation synchronization | Complete |
| 10 | Final static readiness audit, requirement completeness, security sweep | Complete |

All 10 implementation prompts are complete. Docker-based execution and test execution are both available as described above.

---

## Windows Packaging

MSI packaging for native Windows distribution is documentation-only at this stage.
See [`docs/windows-packaging.md`](../docs/windows-packaging.md) for the future build and signing guide using PyInstaller + WiX Toolset.
