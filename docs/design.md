# District Console — System Design

## 1. Offline Desktop Runtime Model

District Console is a fully offline Windows 11 desktop application. It has no internet dependency and no browser-based UI. All data is stored in a local SQLite database file. All integrations are local-only: the embedded REST service listens on `127.0.0.1:8765` and outbound webhook events are written as files to a LAN-shared folder path.

The application process hosts three concurrent execution contexts:
1. **PyQt6 main thread** — UI event loop, windows, dialogs, system tray
2. **FastAPI service thread** — uvicorn ASGI server on `127.0.0.1:8765` for local REST clients
3. **APScheduler thread pool** — background jobs (count session expiry and outbound event retry)

All three share a single SQLite connection pool managed by SQLAlchemy 2.x with WAL mode enabled, allowing concurrent reads without blocking writes.

## 2. PyQt6 Client Composition

The desktop UI is structured as a main `DistrictConsoleWindow` (QMainWindow) hosting a central MDI area (`QMdiArea`) and a persistent sidebar panel. Modal and non-modal dialogs are launched from the main window or from context menus.

Key UI sub-systems:
- **System tray icon** (`QSystemTrayIcon`) — minimise-to-tray, restore, and quick-action menu
- **MDI sub-windows** — simultaneous ledger, item detail, and count session windows side-by-side
- **Keyboard shortcut manager** — global shortcuts registered at `QApplication` level (not widget-level) so they fire regardless of focus:
  - `Ctrl+F` — global search bar
  - `Ctrl+N` — new record (context-sensitive: resource, item, count session)
  - `Ctrl+Shift+L` — open inventory ledger window
- **Context menus** — right-click on inventory items for freeze/unfreeze, relocate, and publish/unpublish
- **Role-aware menus** — menu items and toolbar actions are enabled/disabled based on the authenticated user's roles and scope assignments

High-DPI awareness is enabled via `QApplication.setHighDpiScaleFactorRoundingPolicy` and the `AA_EnableHighDpiScaling` attribute. The baseline design target is 1920×1080.

## 3. Embedded Local REST Service

FastAPI runs in a background daemon thread started at application boot. The ASGI server (uvicorn) is configured to bind only to `127.0.0.1:8765`. It is not accessible from outside the local machine.

Router structure mirrors the domain:
```
/api/v1/auth/              — authentication and session
/api/v1/resources/         — resource library and review workflow
/api/v1/inventory/         — ledger, stock, count sessions, relocations
/api/v1/integrations/      — integration clients and HMAC key management
/api/v1/admin/config/      — configuration center (dict items, workflow nodes, templates, descriptors)
/api/v1/admin/taxonomy/    — metadata taxonomy categories and validation rules
/api/v1/admin/updates/     — offline package import and rollback
/api/v1/admin/audit/       — immutable audit trail, security events, checkpoints
```

All requests from registered integration clients must include an `X-DC-Signature: hmac-sha256 <hex>` header computed over `method + path + body` using the client's active HMAC-SHA256 key. Rate limiting enforces a maximum of 60 requests per minute per client using a sliding window backed by the `rate_limit_state` table.

## 4. SQLite Persistence and Migration Approach

A single SQLite file stores all application data. Pragmas applied at connection time:
```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
```

Schema migrations are managed by **Alembic**. Migration scripts live in `repo/backend/database/migrations/versions/`. On application startup, the bootstrap module runs `alembic upgrade head` to apply any pending migrations before opening the main window.

All append-only tables (`ledger_entries`, `audit_events`) have application-layer guards that prevent UPDATE or DELETE. There is no DB-level trigger enforcement (SQLite trigger support is limited), so the invariant is enforced in repository classes.

## 5. Background Scheduler / System Tray / Checkpoint Recovery

**APScheduler** uses an in-process `BackgroundScheduler` started during bootstrap.

Registered background jobs:
| Job | Schedule | Description |
|-----|----------|-------------|
| `expire_count_sessions` | Every 1 hour | Expire count sessions inactive for >8 hours |
| `retry_pending_events` | Every 5 minutes | Retry pending LAN-folder event writes |
| `enforce_hmac_key_lifecycle` | Every 24 hours | Deactivate expired active/next HMAC keys |

**Checkpoint handling at startup** performs discovery and service-level resume dispatch. Bootstrap loads `ACTIVE` checkpoints and invokes resume handlers by job type (`import`, `count`, `approval`). Completed checkpoints are marked `COMPLETED`, non-resumable checkpoints are marked `FAILED`, and remaining active records are then hydrated into `AppState.pending_checkpoints` for recovery UI visibility.

## 6. Docker Validation Model

Docker is the official acceptance and verification path. The application is not expected to produce a running `.msi` installer at this stage; that is documentation-only.

Services defined in `repo/docker-compose.yml`:
- **`app`** — runs the full desktop+API stack (PyQt in offscreen mode, API on port 8765)
- **`test`** — executes pytest inside Docker (backend suites by default via `run_tests.sh`)

To run tests:
```bash
./run_tests.sh
./run_tests.sh --cov
```

`run_tests.sh` defaults to backend API + backend unit directories and can enable
coverage/fail-under gates with `--cov`.

The `test` service uses `QT_QPA_PLATFORM=offscreen` so PyQt widgets can initialize in a headless environment. The `xvfb` and related Mesa packages in the Dockerfile support this when UI tests are run explicitly.

No host-level Python or pip install is required. All dependencies are declared in `requirements.txt` and `requirements-dev.txt` and resolved at Docker build time.

## 7. Windows Packaging Strategy

MSI packaging for Windows distribution is **documentation-only** at this stage. See `docs/windows-packaging.md` for the step-by-step future guide using PyInstaller and WiX Toolset.

The application is designed for native Windows 11 execution. When run natively (not in Docker), it requires Python 3.10 and the packages in `requirements.txt`. The PyInstaller freeze path bundles all dependencies into a single directory or one-file executable.

## 8. Security Boundaries and RBAC Scope Strategy

### Authentication
- Passwords are hashed with **Argon2id** (argon2-cffi) and never stored in plaintext or reversibly encoded form
- Minimum password length: 12 characters
- Failed attempt tracking: 5 failed attempts trigger a 15-minute lockout stored in `users.locked_until`
- Session tokens are issued at login and validated on every API request; token lifetime is appropriate for a desktop session (8 hours default)

### RBAC
Five primary roles with distinct permission sets:

| Role | Key Permissions |
|------|----------------|
| Administrator | Full system access, user management, audit log, config center |
| Librarian | Resource import/edit, inventory management, count sessions, relocations |
| Teacher | Resource viewing, classroom allocation requests |
| Counselor | Timeliness and audience classification of student-facing materials |
| Reviewer | Review workflow (submit-review, publish, unpublish) |

Permissions are enforced at three levels:
1. **Menu/UI level** — actions are disabled/hidden for unauthorised roles
2. **API level** — every route handler validates the authenticated user's role before processing
3. **Data-scope level** — records are filtered to the user's assigned scope (school / department / class / individual)

### HMAC Signing (Integration Clients)
Integration clients authenticate REST requests using `HMAC-SHA256` signatures. Keys rotate every 90 days with an active+next overlap window so clients can transition without downtime. Key material is stored encrypted in `hmac_keys` (encryption at rest handled by the infrastructure layer).

---

## 9. Requirement Traceability Table

| Original Prompt Domain | Module(s) |
|---|---|
| Auth / Lockout (12-char pw, 5-attempt lockout, Argon2id) | `domain/entities/user.py`, `domain/policies.py`, `application/auth_service.py`, `api/routers/auth.py`, `infrastructure/repositories.py` (UserRepository) |
| Resource Library / File Import / CSV Import | `domain/entities/resource.py`, `application/resource_service.py`, `api/routers/resources.py`, `infrastructure/repositories.py` (ResourceRepository) |
| Deduplication (fingerprint + ISBN) | `domain/entities/resource.py` (dedup_key field), `application/resource_service.py` (_compute_fingerprint, _compute_dedup_key) |
| Revision History (retain last 10) | `domain/entities/resource.py` (ResourceRevision), `domain/policies.py` (MAX_RESOURCE_REVISIONS), `application/resource_service.py` |
| Review Workflow (Draft→InReview→Published/Unpublished) | `domain/entities/resource.py` (ReviewTask), `domain/enums.py` (ResourceStatus, VALID_RESOURCE_TRANSITIONS), `application/resource_service.py` |
| Immutable Audit Trail | `infrastructure/audit_writer.py`, `infrastructure/repositories.py` (AuditRepository — INSERT only) |
| Inventory Ledger (append-only, warehouse/location/batch/serial) | `domain/entities/inventory.py`, `domain/entities/ledger.py`, `application/inventory_service.py`, `infrastructure/repositories.py` (LedgerRepository — append-only) |
| Freeze/Unfreeze + Record-Level Locking | `domain/entities/inventory.py` (StockBalance), `infrastructure/lock_manager.py`, `infrastructure/repositories.py` (LockRepository) |
| Count Sessions (open/blind/cycle, 8h expiry, variance approval) | `domain/entities/count.py`, `domain/policies.py` (thresholds), `application/count_session_service.py`, `api/routers/count_sessions.py` |
| Relocations (from/to bin, device source) | `domain/entities/relocation.py`, `application/relocation_service.py`, `api/routers/relocations.py` |
| Correction Entries (append-only reversal) | `domain/entities/ledger.py` (reversal_of_id), `application/inventory_service.py`, `infrastructure/repositories.py` (LedgerRepository.mark_reversed) |
| RBAC (menu, API, data-scope) | `domain/entities/role.py`, `domain/entities/scope.py`, `application/rbac_service.py`, `api/dependencies.py` (require_permission) |
| Metadata Taxonomy (categories, keywords, timeliness, age range, etc.) | `domain/entities/resource_metadata.py`, `application/taxonomy_service.py`, `api/routers/admin/taxonomy.py` |
| Configuration Center (dictionary, workflow nodes, templates, descriptors) | `domain/entities/config.py`, `application/config_service.py`, `api/routers/admin/config.py` |
| HMAC Signing + Key Rotation (90 days, active/next overlap) | `domain/entities/integration.py` (HmacKey), `infrastructure/hmac_signer.py`, `application/integration_service.py` |
| Rate Limiting (60 rpm per client) | `domain/entities/integration.py` (RateLimitState), `infrastructure/rate_limiter.py`, `api/middleware.py` |
| Outbound Webhook Events (LAN folder) | `domain/entities/integration.py` (OutboundEvent), `infrastructure/outbox_writer.py`, `api/routers/integrations.py` |
| Crash-Safe Checkpointing | `domain/entities/checkpoint.py`, `infrastructure/checkpoint_store.py`, `bootstrap/__init__.py` (active checkpoint discovery at startup) |
| Offline Update Packages + Rollback | `domain/entities/update.py`, `application/update_service.py`, `api/routers/admin/updates.py` |
| Desktop UI (keyboard-first, shortcuts, context menus, MDI, tray) | `ui/shell/main_window.py`, `ui/shortcuts.py`, `ui/tray.py`, `ui/screens/`, `ui/widgets/` |
| Local REST API | `api/routers/` (auth, resources, inventory, count_sessions, relocations, integrations, admin/*), `api/middleware.py`, `api/schemas.py` |
| Background Scheduler + System Tray | `bootstrap/__init__.py` (APScheduler wiring), `ui/tray.py` |
| Performance (<5s start, <200MB steady-state) | `infrastructure/instrumentation.py` (InstrumentationHooks), `bootstrap/__init__.py` (startup ordering) |

---

## 10. Sequence Flows

*(Added in Prompt 2 — see below)*

### 10.1 Resource Import → Review → Publish

```
User selects file / uploads CSV
  → infrastructure/file_importer: compute SHA-256 fingerprint
  → infrastructure/fingerprint: check dedup_key in resources table
    → if duplicate: return existing resource ID + revision diff
    → if new: create Resource(status=DRAFT) + ResourceRevision(revision_number=1)
  → infrastructure/checkpoint_store: record CheckpointRecord(job_type=import)
  → application/resource_service: validate metadata (age_range, timeliness, categories)
  → UI shows import result summary

User submits for review (requires Librarian or higher)
  → validate ResourceStatus transition: DRAFT → IN_REVIEW
  → create ReviewTask(assigned_to=<reviewer_user_id>)
  → append AuditEvent(action=SUBMITTED_FOR_REVIEW, immutable)

Reviewer approves and publishes
  → validate transition: IN_REVIEW → PUBLISHED
  → require ReviewTask.notes to be non-empty
  → set Resource.status = PUBLISHED
  → append AuditEvent(action=PUBLISHED, actor=reviewer, timestamp=utcnow, immutable)
  → CheckpointRecord marked COMPLETED
```

### 10.2 Count Session Close → Variance → Approval

```
Librarian closes count session
  → CountSession.status: ACTIVE → CLOSED
  → For each CountLine:
      variance_qty = counted_qty - expected_qty
      variance_value = |variance_qty| × item.unit_cost
      requires_approval = policies.requires_supervisor_approval(variance_value, variance_pct)
  → If any line requires_approval == True:
      create CountApproval record (status=PENDING)
      notify supervisor via UI alert
  → If no approval required:
      create LedgerEntry(entry_type=COUNT_CLOSE) for each adjusted line
      append AuditEvent(action=COUNT_CLOSED)

Supervisor approves
  → CountApproval.decision = APPROVED
  → create LedgerEntry(COUNT_CLOSE) for approved lines
  → CountSession.status = APPROVED
  → append AuditEvent(action=COUNT_APPROVED)
```

### 10.3 Intra-Warehouse Relocation

```
Operator scans or enters from_location + to_location + quantity + device_source
  + optional partition: status + batch_id + serial_id
  → acquire RecordLock on source StockBalance (timeout=30s, user feedback if locked)
  → acquire RecordLock on destination StockBalance
  → resolve source and destination in same warehouse
  → validate: source.quantity >= quantity in selected partition
  → create Relocation record (device_source=MANUAL|USB_SCANNER)
  → append LedgerEntry(entry_type=RELOCATION, quantity_delta=-qty) on source
  → append LedgerEntry(entry_type=RELOCATION, quantity_delta=+qty) on destination
  → update StockBalance.quantity on both locations
  → release both RecordLocks
  → append AuditEvent(action=RELOCATED)
```

### 10.4 Append-Only Correction (Ledger Reversal)

```
Supervisor selects incorrect LedgerEntry to reverse
  → validate: entry.is_reversed == False (cannot reverse twice)
  → create new LedgerEntry(
        entry_type=CORRECTION,
        quantity_delta = -(original.quantity_delta),
        reversal_of_id = original.id
    )
  → mark original: is_reversed = True, reversal_ref = new_entry.id
  → update StockBalance.quantity_after accordingly
  → append AuditEvent(action=CORRECTION_APPLIED)
  NOTE: No DELETE or UPDATE is ever issued on ledger_entries.
```

---

## 9. Security Architecture (Prompt 3)

### 9.1 Authentication Flow

```
User enters username + password
  → AuthService.authenticate(session, username, password, now)
  → UserRepository.get_by_username → User domain object
  → User.is_locked_out(now)? → raise LockoutError (423)
  → AuthService.verify_password (Argon2id) → mismatch?
      → User.record_failed_attempt(now) → save
      → raise InvalidCredentialsError (401)
  → User.reset_failed_attempts(now) → save
  → RoleRepository.get_roles_for_user → list[Role]
  → AuthService.create_session(user_id, roles) → token (43-char URL-safe base64)
  → Return LoginResponse {user_id, username, roles, token, expires_at}
```

Session tokens are stored in an in-memory dict inside `AuthService`. Sessions
expire after 8 hours. Restarting the application invalidates all sessions —
appropriate for a local desktop app where the operator is physically present.

### 9.2 Password Policy

| Policy | Value | Source |
|--------|-------|--------|
| Minimum length | 12 characters | `MIN_PASSWORD_LENGTH` |
| Hashing algorithm | Argon2id | `argon2-cffi PasswordHasher()` |
| Failed attempt limit | 5 attempts | `MAX_FAILED_ATTEMPTS` |
| Lockout duration | 15 minutes | `LOCKOUT_DURATION_MINUTES` |

### 9.3 RBAC — Permission Matrix

Permissions are dot-separated strings: `<resource>.<action>`.
Five roles are seeded at first run. The Administrator role bypasses all
permission and scope checks.

| Role | Key Permissions |
|------|----------------|
| Administrator | All permissions (implicit bypass) |
| Librarian | resources.create, resources.publish, resources.import |
| Teacher | resources.read, inventory.read |
| Counselor | resources.read, inventory.read, config.read |
| Reviewer | resources.review, resources.publish |

`RbacService.check_permission(roles, permission_name)` raises
`InsufficientPermissionError` (403) if denied. Used via `require_permission()`
FastAPI dependency in route handlers.

### 9.4 Scope Enforcement

Users are assigned to one or more scope levels:
`SCHOOL > DEPARTMENT > CLASS > INDIVIDUAL`

`RbacService.check_scope(scopes, scope_type, ref_id)` raises
`ScopeViolationError` (403) if `ref_id` is not in the user's scope assignments
for the given `scope_type`. Hierarchy expansion (SCHOOL scope covers all
children) is deferred to Prompt 4 application services.

### 9.5 HMAC Request Signing Protocol

For integration client requests (not UI sessions):

```
Signing message:
  {METHOD}\n{path}\n{timestamp_unix_epoch}\n{sha256_hex(body)}

Headers sent:
  X-DC-Signature: hmac-sha256 {hex_digest}
  X-DC-Timestamp: {unix_epoch_int}

Replay protection:
  Requests with |now - timestamp| > 300 seconds are rejected.

Key storage:
  Key bytes stored as hex string in hmac_keys.key_encrypted.
  At-rest encryption deferred to Prompt 7.
  Key bytes never appear in log output (SanitizingFilter covers this).
```

### 9.6 Rate Limiting

Fixed-window counter per integration client. Window = 60 seconds.
Limit = 60 requests/minute (`RATE_LIMIT_RPM`).
61st request in window raises `RateLimitExceededError` (429).
Window resets when `now - window_start >= 60s`.
State persisted in `rate_limit_state` table (one row per client).

### 9.7 Record Lock TTL

Default TTL: 300 seconds (5 minutes). Refreshable via `LockManager.refresh()`.
On acquisition: expired locks are purged first, then a new lock is inserted.
Conflict detection uses the UNIQUE constraint on `(entity_type, entity_id)`.
`nonce` field (random hex) prevents accidental release by a different session.

### 9.8 Log Sanitization

`SanitizingFilter` is registered on the root logger at bootstrap.
Fields in `SENSITIVE_KEYS` are redacted to `[REDACTED]` in all log records:

```python
SENSITIVE_KEYS = {
    "password", "password_hash", "key", "key_encrypted",
    "secret", "token", "hmac", "signature", "authorization",
    "hash", "credential", "api_key", "private_key",
}
```

Applies to dict `args`, tuple `args`, string message `key=value` patterns,
and extra attributes attached directly to log records.

---

### 10.5 Restart Recovery via Checkpoint

```
Application starts
  → bootstrap: run alembic upgrade head
  → infrastructure/checkpoint_store: query checkpoint_records WHERE status = 'ACTIVE'
  → Convert to UI summary records: [{job_type, job_id}, ...]
  → Store summary on AppContainer._active_checkpoints
  → Start scheduler jobs (expire_count_sessions + retry_pending_events)
  → Main window opens after login; recovery prompt depends on UI state wiring
```

---

## 10. Workflow Architecture (Prompt 4)

### 10.6 Resource Import Flow

```
import_file:
  SHA-256(bytes) → fingerprint
  SHA-256(fingerprint + (isbn or "")) → dedup_key
  get_by_dedup_key → DuplicateResourceError if found
  INSERT Resource(status=DRAFT)
  INSERT ResourceRevision(revision_number=1, file_hash=fingerprint, file_size=len(bytes))
  save metadata if provided
  AuditEvent(action=IMPORTED)
  Checkpoint(job_type="import", status=COMPLETED)

import_csv:
  Iterate csv.DictReader rows
  Per-row fingerprint from (title + isbn).encode()
  Catch DuplicateResourceError per row → add to duplicates list
  Checkpoint every 10 rows with progress cursor
  Mark COMPLETED at end
  Return {created, duplicates, errors, checkpoint_id}
```

### 10.7 Review/Publish Workflow

```
DRAFT ──submit_for_review──▶ IN_REVIEW ──publish──▶ PUBLISHED ──unpublish──▶ UNPUBLISHED
                                                                              │
                                           ◀──submit_for_review──────────────┘

Guards:
  resources.submit_review required (Librarian+)
  resources.publish required (Reviewer only)
  reviewer_notes must be non-empty on publish + unpublish
  Record lock acquired for each status transition
  ReviewTask created on submit; completed (APPROVED) on publish
```

### 10.8 Ledger Engine

```
Append-only rule: ledger_entries accepts only INSERT
  LedgerRepository.append() is the sole INSERT path

Correction pattern:
  LedgerRepository.append(CORRECTION entry with reversal_of_id=original.id)
  LedgerRepository.mark_reversed(original_id) — UPDATE is_reversed=True ONLY
  No other column of ledger_entries is ever updated

Stock balance:
  Materialized running total updated synchronously with each ledger write
  StockBalance.quantity = last quantity_after for that item+location

freeze/unfreeze:
  StockBalance mutation only (no ledger entry created)
  Lock acquired for freeze and unfreeze operations
```

### 10.9 Count Session Flow

```
open → ACTIVE → (add/update lines)* → close → CLOSED
  If any line.requires_approval: → approve (ADMIN) → APPROVED
  Inactivity > 8h: → EXPIRED; checkpoint FAILED

close_session processing:
  For each line with variance_qty != 0:
    Append LedgerEntry(COUNT_CLOSE, delta=variance_qty)
    Update StockBalance.quantity
  Set session.status = CLOSED
  Set checkpoint step = awaiting_approval | completed

Variance approval threshold:
  requires_approval = variance_dollar > $250 OR variance_pct > 2%

Blind mode:
  expected_qty stored internally for variance calculation
  API returns expected_qty = null in CountLineResponse
```

### 10.10 Relocation Flow

```
relocate:
  Validate from_location != to_location (DomainValidationError)
  Validate quantity > 0 (DomainValidationError)
  Validate source/destination are in same warehouse
  Resolve partition by status + batch_id + serial_id
  Load from_balance in partition → check qty >= quantity → InsufficientStockError
  Check from_balance.is_frozen → StockFrozenError
  Acquire lock on from_balance
  Load or create to_balance in same partition (quantity=0 if new)
  Append DEBIT LedgerEntry(RELOCATION, -quantity) on from_location
  Append CREDIT LedgerEntry(RELOCATION, +quantity) on to_location
  Update both StockBalance.quantity values
  INSERT Relocation(ledger_debit_entry_id, ledger_credit_entry_id)
  AuditEvent(action=RELOCATION, metadata={device_source})
  Release lock
```

### Traceability

| Service | Prompt | Key Files |
|---------|--------|-----------|
| ResourceService | 4 | application/resource_service.py |
| InventoryService | 4 | application/inventory_service.py |
| CountSessionService | 4 | application/count_session_service.py |
| RelocationService | 4 | application/relocation_service.py |
| ResourceRepository + 7 new repos | 4 | infrastructure/repositories.py |
| Desktop shell, screens, tray | 5–6 | ui/ (see Section 11) |

---

## 11. Desktop Shell Architecture (Prompts 5–6)

### 11.1 Application Lifecycle

```
configure_highdpi()          ← before QApplication creation
QApplication created          ← theme applied (Fusion + Windows 11 palette)
bootstrap() (async)           ← runs in temp event loop; returns AppContainer
uvicorn started (daemon thread) ← binds 127.0.0.1:8765
AppState + ApiClient created  ← shared across all UI components
SystemTray created (hidden)   ← shown after login
SignInDialog shown             ← blocks until login_success or quit
  ↓ login_success
MainWindow created            ← MDI shell, menu bar, nav dock, shortcuts
RecoveryDialog (if checkpoints exist)
Qt event loop runs
  ↓ logout_requested
SignInDialog re-shown         ← MainWindow destroyed
```

### 11.2 Module Map

```
src/district_console/ui/
├── app.py               run_application() — entry point, lifecycle wiring
├── state.py             AppState — token, roles, permissions, tray mode
├── client.py            ApiClient — synchronous httpx, ApiError wrapper
├── theme.py             Windows 11 Fluent light palette; configure_highdpi()
├── shortcuts.py         ShortcutManager — global QAction shortcuts
├── tray.py              SystemTray — minimize-to-tray, safe quit
├── shell/
│   ├── main_window.py   MainWindow — MDI host, nav dock, menu bar, shell
│   ├── sign_in_dialog.py  SignInDialog — login form with error states
│   └── workspace.py     WorkspaceCoordinator — singleton sub-window management
├── widgets/
│   ├── loading_overlay.py   Semi-transparent overlay during API calls
│   ├── notification_bar.py  Top bar: info/success/warning/error
│   ├── empty_state.py       Centred icon+heading for empty lists
│   ├── lock_conflict_dialog.py  RecordLockedError dialog
│   └── recovery_dialog.py   Checkpoint resume selection dialog
├── utils/
│   └── async_worker.py  ApiWorker(QThread) — runs blocking calls off main thread
└── screens/
    ├── dashboard.py         Role-filtered summary cards and quick-launch
    ├── resources/
    │   ├── resource_list.py   Searchable resource table, context menu
    │   ├── resource_detail.py  Tabbed detail/editor with status transitions
    │   └── review_queue.py    IN_REVIEW list for reviewers
    ├── inventory/
    │   ├── ledger_viewer.py   Split: stock balances + ledger entries
    │   ├── item_detail.py     Item form + per-location stock table
    │   └── count_session.py   Full count session workspace (open/add/close/approve)
    ├── users/session_status.py   Session/user info panel
    ├── teacher/allocation_view.py  Browse published resources, request allocation
    ├── counselor/classification_view.py  Age range + timeliness classification
    └── approval/approval_inbox.py  Tabbed inbox: resource reviews + count approvals
```

### 11.3 Keyboard Shortcut Map

| Shortcut | Action |
|----------|--------|
| Ctrl+F | Global search (focus search bar in active screen) |
| Ctrl+N | New record (context-sensitive to active MDI sub-window) |
| Ctrl+Shift+L | Logout |
| Ctrl+W | Close active MDI sub-window |
| Ctrl+S | Save current form |
| Ctrl+R / F5 | Refresh active screen |
| Ctrl+1 … Ctrl+5 | Navigate: Dashboard, Resources, Inventory, Count Sessions, Approvals |
| Escape | Dismiss notification bar |

All shortcuts use `Qt.ShortcutContext.ApplicationShortcut` so they fire
regardless of which sub-window has focus inside the MDI area.

### 11.4 Multi-Window Workspace Model

`WorkspaceCoordinator` wraps `QMdiArea` with singleton sub-window management:

- Each logical screen is registered under a string key: `"dashboard"`, `"resources"`, etc.
- `open(key)` returns the existing sub-window if one is already open, preventing duplicates.
- Per-resource detail windows use dynamic keys: `"resource_{resource_id}"`.
- `close_all()` is called on logout to tear down all managed sub-windows.
- `tile()` and `cascade()` are exposed via the View menu.

### 11.5 Tray Mode and Safe Shutdown

When `AppState.tray_mode = True` (default), minimizing the window hides it
instead of minimizing to the taskbar. The `SystemTray` icon appears in the
notification area and provides restore/quit actions.

`_safe_quit()` checks `AppState.has_resumable_work()` (active workers or
pending checkpoints). If in-flight work exists, a confirmation dialog is shown
before `QApplication.quit()` is called.

### 11.6 Role-Based Visibility

Permission checking is done entirely via `AppState.has_permission(name)` which
mirrors the server-side `RbacService` permission model. ADMINISTRATOR bypasses
all checks (wildcard `"*"` sentinel). The UI enforces visibility at three layers:

1. **Navigation dock** — entries filtered by `has_permission(required_perm)`
2. **Menu and toolbar actions** — built conditionally in `_build_menus()` / `_build_toolbar()`
3. **Screen-level actions** — buttons shown/hidden per `has_permission()` in each widget

The server enforces actual RBAC on every API call. UI gating is cosmetic/UX only.

### 11.7 Screen Data Flow

All screens follow the same asynchronous pattern:

```
Screen.__init__()
  → _build_ui()                    build widgets, hide overlay
  → load_data()                    show overlay
      → ApiWorker(client.list_*)
            ↓ result signal
          _on_data_loaded(data)    populate table, hide overlay
            ↓ error signal
          _on_error(exc)           show notification bar with error message
```

`ApiWorker` (a `QThread` subclass) emits `result`, `error`, and `finished_clean`
signals. Widget holds a reference to the worker to prevent GC during execution.

### 11.8 Desktop Layout Standards

- Base resolution: 1920×1080; high-DPI PassThrough policy enabled
- Font: Segoe UI 10pt (Windows default)
- Style engine: Fusion (cross-platform baseline, styled via QStyleSheet)
- Palette: Windows 11 Fluent light (accent `#0078d4`, surface `#ffffff`, bg `#f3f3f3`)
- Table row height: ~28px (4px padding + 10pt text)
- Button height: ~32px (6px padding + 10pt label)
- MDI sub-window default: 900×600, minimum shell: 1024×600

---

## 12. Secondary Modules (Prompt 7)

### 12.1 Configuration Center

The configuration center provides ADMINISTRATOR-only access to four categories of system settings:

| Module | Entity | Description |
|--------|--------|-------------|
| `ConfigDictionary` | key-value pairs | System and user-defined settings by category |
| `WorkflowNode` | workflow transitions | Per-role state machine edges (from_state → to_state) |
| `NotificationTemplate` | message templates | Subject/body templates for application notifications |
| `DistrictDescriptor` | district metadata | School name, region, and district-level descriptors |

`is_system=True` entries in `ConfigDictionary` are read-only — the API returns HTTP 403 on delete attempts. All mutations write an `AuditEvent`.

### 12.2 Taxonomy Administration

The category tree uses a recursive adjacency model: each `Category` row has `parent_id`, `depth` (0=root), and `path_slug` (ancestor chain joined by `/`). Path slugs are computed by `_slugify()` (lower-cased, non-alphanumeric chars replaced with hyphens) with a UUID suffix appended on slug collision.

`TaxonomyValidationRule` rows enforce field-level constraints (e.g., `copyright` must be one of an allowed_values set). Rules are referenced by the resource metadata validation logic.

### 12.3 Local Integration Surface

Integration clients authenticate to the local API using HMAC-SHA256. The key lifecycle follows a two-phase rotation to prevent downtime:

```
rotate_key()    → INSERT HmacKey(is_next=True)     ← client reconfigures
commit_rotation() → old key: is_active=False
                  → next key: is_active=True, is_next=False
```

Outbound events are written as JSON files to `DC_LAN_EVENTS_PATH` atomically via `tempfile.mkstemp + os.replace()`. If the path is not configured, writes fail with `OutboxDisabledError` and the event stays `PENDING`. Retry is attempted every 5 minutes by APScheduler (up to 5 retries). Events exceeding `_MAX_RETRY_COUNT` are marked `FAILED`.

File naming: `{event_id}_{event_type}.json`

### 12.4 Offline Update Package Import / Rollback

Update packages are ZIP archives with a required `manifest.json`:

```json
{
  "version": "1.2.3",
  "build_id": "build-001",
  "file_list": ["data/config.json"],
  "checksums": {"data/config.json": "sha256hex..."}
}
```

State machine: `PENDING` → `APPLIED` → `ROLLED_BACK`

Rollback chain: each imported package stores `prior_version_ref` pointing to the currently `APPLIED` package at import time. `rollback_package()` marks the current package `ROLLED_BACK` and restores the prior package to `APPLIED`.

### 12.5 Barcode Scanner Input

`BarcodeInputHandler` classifies keyboard input by inter-keystroke timing:

| Interval | Classification |
|----------|---------------|
| ≤ 50 ms | `USB_SCANNER` |
| > 50 ms  | `MANUAL` (buffer reset) |

When a terminator character (`\n`, `\r`, or `\t`) is received and the buffer contains ≥ `min_scan_chars` (default 4) characters that arrived at scanner speed, the complete barcode value is returned and `device_source()` returns `DeviceSource.USB_SCANNER`.

`BarcodeInputField` (a `QLineEdit` subclass) wraps `BarcodeInputHandler` and emits `scan_completed(value: str, source: DeviceSource)` for scanner-detected scans, while falling through to default `QLineEdit` handling for manual keystrokes.

### 12.6 Resilience Instrumentation

`InstrumentationHooks` emits structured `logging.INFO` records for four event types:

| Method | Log event key | Purpose |
|--------|--------------|---------|
| `record_startup_time(ms)` | `startup_complete` | Capture bootstrap duration |
| `record_memory_sample()` | `memory_sample` | RSS/VMS via psutil (optional) |
| `record_scheduler_tick(job_id, ms, success)` | `scheduler_tick` | Per-job execution result |
| `record_recovery_event(type, id, outcome)` | `checkpoint_recovery` | Resume attempt result |

psutil is optional: if not installed, memory samples return `rss_mb=0.0`, `vms_mb=0.0` without error.

### 12.7 Admin UI Screens

All five admin screens are registered in `MainWindow._register_screens()` behind the `admin.manage_config` permission check. An "Administration" menu entry is also added to the menu bar for ADMINISTRATOR users.

| Screen | Registry Key | Widget |
|--------|-------------|--------|
| Config Center | `config_center` | `ConfigCenterWidget` (4-tab: Dictionary, Workflow, Templates, Descriptors) |
| Taxonomy Admin | `taxonomy_admin` | `TaxonomyAdminWidget` (QSplitter: category tree + validation rules) |
| Integration Admin | `integration_admin` | `IntegrationAdminWidget` (client list + key rotation + event log) |
| Update Manager | `update_manager` | `UpdateManagerWidget` (version history + import/apply/rollback) |
| Audit Log | `audit_log` | `AuditLogViewerWidget` (3-tab: All Events, Security, Checkpoints) |

### 12.8 Traceability Table (Prompt 7 Additions)

| Service | Prompt |
|---------|--------|
| ConfigService | 7 |
| TaxonomyService | 7 |
| IntegrationService | 7 |
| UpdateService | 7 |
| AuditService | 7 |
| OutboxWriter | 7 |
| BarcodeInputHandler | 7 |
| InstrumentationHooks | 7 |
