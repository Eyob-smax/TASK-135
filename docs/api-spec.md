# District Console — Local REST API Specification

## Overview

The District Console exposes a local-only REST API via an embedded FastAPI service. All endpoints are bound to `127.0.0.1:8765` and are accessible only from the local machine. There is no internet exposure and no reverse proxy.

In Docker acceptance runs, `docker-compose.yml` publishes the API as `127.0.0.1:8765:8765` and sets `DC_API_HOST=127.0.0.1` to preserve loopback-only access.

**Base URL:** `http://127.0.0.1:8765/api/v1`

**Protocol:** HTTP/1.1 (local loopback only)

**Content-Type:** `application/json` for all request and response bodies, except file upload endpoints which use `multipart/form-data`.

---

## Authentication

### Desktop Session (UI-initiated)
The PyQt desktop UI authenticates via `POST /api/v1/auth/login`. The returned session token is attached to all subsequent API requests as a Bearer token:
```
Authorization: Bearer <session_token>
```

### Integration Client Authentication (HMAC-SHA256)
Registered integration clients must include a request signature header on every request:
```
X-DC-Client-ID: <client_uuid>
X-DC-Signature: hmac-sha256 <hex_signature>
X-DC-Timestamp: <unix_epoch_seconds>
```

The signature is computed as:
```
HMAC-SHA256(key, method + "\n" + path + "\n" + timestamp + "\n" + body_sha256)
```
where `body_sha256` is the hex-encoded SHA-256 of the raw request body (empty string for no-body requests). Requests with a timestamp more than 300 seconds (5 minutes) old are rejected (replay protection).

---

## Error Envelope

All error responses use a consistent envelope:
```json
{
  "error": {
    "code": "ERROR_CODE_CONSTANT",
    "message": "Human-readable description.",
    "details": null
  }
}
```

`details` may be an object or array for validation errors (e.g. field-level messages). It is `null` for all other error types.

### HTTP Status Codes

| Status | When Used |
|--------|-----------|
| 200 | Successful read or update |
| 201 | Successful creation |
| 204 | Successful deletion or logout (no body) |
| 400 | Business rule violation or malformed request |
| 401 | Not authenticated (missing or invalid token) |
| 403 | Authenticated but insufficient permission |
| 404 | Resource not found |
| 409 | Conflict (duplicate, record locked, invalid state transition) |
| 422 | Pydantic schema validation error (malformed input shape) |
| 423 | Account locked out |
| 429 | Rate limit exceeded (60 req/min per integration client) |
| 500 | Unexpected server error (sanitised message, no stack trace) |

### Standard Error Codes

| Code | HTTP | Meaning |
|------|------|---------|
| `SESSION_EXPIRED` | 401 | Missing, invalid, or expired session token |
| `UNAUTHENTICATED` | 401 | Legacy alias accepted by middleware |
| `ACCOUNT_LOCKED` | 423 | User locked out for 15 minutes |
| `INVALID_CREDENTIALS` | 401 | Wrong username or password |
| `INSUFFICIENT_PERMISSION` | 403 | Role does not allow this action |
| `SCOPE_VIOLATION` | 403 | Record is outside user's assigned scope |
| `NOT_FOUND` | 404 | Entity does not exist |
| `RECORD_LOCKED` | 409 | Another session holds a record lock |
| `INVALID_STATE_TRANSITION` | 409 | Workflow state change not permitted |
| `DUPLICATE_RESOURCE` | 409 | Fingerprint + ISBN dedup match found |
| `APPEND_ONLY_VIOLATION` | 409 | Attempted to delete or update an immutable record |
| `VALIDATION_ERROR` | 422 | Input schema or field constraint violated |
| `RATE_LIMIT_EXCEEDED` | 429 | Client exceeded 60 requests/minute |
| `SIGNATURE_INVALID` | 401 | HMAC signature verification failed |
| `REVISION_LIMIT_REACHED` | 409 | Resource already has 10 revisions |
| `INTERNAL_ERROR` | 500 | Unexpected server-side failure |

---

## Pagination

List endpoints support offset-based pagination:
```
GET /api/v1/resources/?offset=0&limit=50
```
Response envelope for lists:
```json
{
  "items": [...],
  "total": 142,
  "offset": 0,
  "limit": 50
}
```

---

## API Groups

### Auth (`/api/v1/auth/`)

| Method | Path | Description | Roles |
|--------|------|-------------|-------|
| POST | `/login` | Authenticate with username+password, returns session token | All |
| POST | `/logout` | Invalidate current session token | Authenticated |
| GET | `/whoami` | Return current user identity, roles, and scope assignments | Authenticated |

**POST /login request:**
```json
{"username": "jsmith", "password": "..."}
```
**POST /login response (200):**
```json
{"user_id": "uuid", "username": "jsmith", "roles": ["LIBRARIAN"], "token": "...", "expires_at": "ISO-8601"}
```
**POST /login response (401 — invalid credentials):**
```json
{"error": {"code": "INVALID_CREDENTIALS", "message": "Invalid username or password.", "details": null}}
```
**POST /login response (423 — locked out):**
```json
{"error": {"code": "ACCOUNT_LOCKED", "message": "Account locked until 2024-01-01T12:30:00. Too many failed login attempts.", "details": null}}
```

**GET /whoami response (200):**
```json
{
  "user_id": "uuid",
  "username": "jsmith",
  "roles": ["LIBRARIAN"],
  "scopes": [{"scope_type": "SCHOOL", "scope_ref_id": "uuid"}]
}
```

**Authorization header for protected routes:**
```
Authorization: Bearer <session_token>
```
Missing or expired tokens → `401 SESSION_EXPIRED`.

**Rate-limit response headers (integration client endpoints):**
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 42
X-RateLimit-Reset: 1712345720
```

---

### Resources (`/api/v1/resources/`)

| Method | Path | Description | Roles |
|--------|------|-------------|-------|
| GET | `/` | List resources (paginated, filterable by status/type/category) | All |
| POST | `/` | Create a new draft resource record | Librarian+ |
| GET | `/{id}` | Get resource detail including metadata and current revision | All |
| PUT | `/{id}` | Update draft resource (blocked if status ≠ DRAFT) | Librarian+ |
| DELETE | `/{id}` | Not permitted — resources are never hard-deleted | — |
| POST | `/import/file` | Multipart file upload; returns dedup result + checkpoint_id | Librarian+ |
| POST | `/import/csv` | CSV bulk import; returns job_id + checkpoint_id | Librarian+ |
| GET | `/{id}/revisions` | List up to 10 revisions (oldest first) | All |
| POST | `/{id}/submit-review` | Transition DRAFT → IN_REVIEW; assigns reviewer | Librarian+ |
| POST | `/{id}/publish` | Transition IN_REVIEW → PUBLISHED (requires reviewer notes) | Reviewer |
| POST | `/{id}/unpublish` | Transition PUBLISHED → UNPUBLISHED | Reviewer |

**Filters for GET /:** `status`, `resource_type`, `category_id`, `keyword`, `timeliness`, `created_by`, `offset`, `limit`

---

### Inventory (`/api/v1/inventory/`)

#### Items
| Method | Path | Description | Roles |
|--------|------|-------------|-------|
| GET | `/items/` | List inventory items | Librarian+ |
| POST | `/items/` | Create inventory item (SKU, name, unit_cost) | Librarian+ |
| GET | `/items/{id}` | Item detail | Librarian+ |
| PUT | `/items/{id}` | Update item (name, description, unit_cost) | Librarian+ |

#### Warehouses and Locations
| Method | Path | Description | Roles |
|--------|------|-------------|-------|
| GET | `/warehouses/` | List warehouses | Librarian+ |
| POST | `/warehouses/` | Create warehouse | Administrator |
| GET | `/locations/` | List locations (filter by warehouse_id) | Librarian+ |
| POST | `/locations/` | Create location (zone/aisle/bin) | Administrator |

#### Stock and Freeze
| Method | Path | Description | Roles |
|--------|------|-------------|-------|
| GET | `/stock/` | Query stock balances (filter by item_id, location_id, batch_id, serial_id, status) | Librarian+ |
| POST | `/stock/{id}/freeze` | Freeze a stock balance record (requires reason) | Librarian+ |
| POST | `/stock/{id}/unfreeze` | Unfreeze a stock balance record | Librarian+ |

#### Ledger (Append-Only)
| Method | Path | Description | Roles |
|--------|------|-------------|-------|
| GET | `/ledger/` | View ledger entries (filter by item_id, location_id, entry_type) | Librarian+ |
| POST | `/ledger/adjustment` | Add manual adjustment entry with reason_code | Librarian+ |
| POST | `/ledger/correction/{entry_id}` | Create a reversal correction for a prior entry | Librarian+ |

#### Count Sessions
| Method | Path | Description | Roles |
|--------|------|-------------|-------|
| POST | `/count-sessions/` | Open a new count session (mode: OPEN/BLIND/CYCLE) | Librarian+ |
| GET | `/count-sessions/{id}` | Get session detail with all count lines | Librarian+ |
| POST | `/count-sessions/{id}/line` | Add or update a count line | Librarian+ |
| PUT | `/count-sessions/{id}/lines/{line_id}` | Update counted quantity | Librarian+ |
| POST | `/count-sessions/{id}/close` | Close session; triggers variance evaluation | Librarian+ |
| POST | `/count-sessions/{id}/approve` | Approve variance (supervisor only, if required) | Administrator |

#### Relocations
| Method | Path | Description | Roles |
|--------|------|-------------|-------|
| POST | `/relocations/` | Record intra-warehouse relocation (from/to bin, qty, device_source) | Librarian+ |
| GET | `/relocations/` | List relocations (filter by item_id, operator_id, date range) | Librarian+ |

---

### Configuration Center (`/api/v1/admin/config/`)

| Method | Path | Description | Roles |
|--------|------|-------------|-------|
| GET | `/` | List config dictionary entries (filter by category) | All |
| PUT | `/{category}/{key}` | Create or update a dictionary entry (system entries protected) | Administrator |
| DELETE | `/{entry_id}` | Delete a non-system dictionary entry by entry UUID | Administrator |
| GET | `/workflow-nodes/` | List workflow transition nodes | All |
| POST | `/workflow-nodes/` | Create workflow node | Administrator |
| DELETE | `/workflow-nodes/{node_id}` | Delete workflow node | Administrator |
| GET | `/templates/` | List notification templates | All |
| PUT | `/templates/{name}` | Create or update a notification template by name | Administrator |
| GET | `/descriptors/` | List district/regional descriptors | All |
| PUT | `/descriptors/{key}` | Create or update a district descriptor by key | Administrator |

---

### Taxonomy (`/api/v1/admin/taxonomy/`)

| Method | Path | Description | Roles |
|--------|------|-------------|-------|
| GET | `/categories/` | List taxonomy categories (filter by parent_id, flat=true for all) | All |
| POST | `/categories/` | Create taxonomy category | Administrator |
| PUT | `/categories/{id}` | Update category name | Administrator |
| DELETE | `/categories/{id}` | Deactivate (soft-delete) a taxonomy category | Administrator |
| GET | `/rules/` | List validation rules (filter by field) | All |
| POST | `/rules/` | Create a validation rule | Administrator |
| DELETE | `/rules/{id}` | Delete a validation rule | Administrator |

---

### Integrations (`/api/v1/integrations/`)

#### Admin Management (Bearer token auth)
| Method | Path | Description | Roles |
|--------|------|-------------|-------|
| GET | `/` | List integration clients | Administrator |
| POST | `/` | Register new integration client (returns client + initial key) | Administrator |
| DELETE | `/{client_id}` | Deactivate integration client | Administrator |
| POST | `/{client_id}/rotate-key` | Initiate key rotation (generate next key) | Administrator |
| POST | `/{client_id}/commit-rotation` | Commit rotation: next key becomes active | Administrator |
| GET | `/events/` | List outbound events (filter by client_id, status) | Administrator |
| POST | `/events/{client_id}/emit` | Emit a controlled outbound event payload for a specific active client | Administrator |
| POST | `/events/retry` | Retry all pending outbound events | Administrator |

#### Inbound Client Endpoints (HMAC-SHA256 auth — see §Authentication)
| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/inbound/status` | Health check; verifies HMAC signature and rate limit | HMAC |

---

### Updates (`/api/v1/admin/updates/`)

| Method | Path | Description | Roles |
|--------|------|-------------|-------|
| GET | `/` | List all imported update packages (paginated) | Administrator |
| POST | `/import` | Import offline update package (multipart ZIP upload) | Administrator |
| POST | `/{package_id}/apply` | Apply a PENDING package; extracts files to staging directory | Administrator |
| POST | `/{package_id}/rollback` | Rollback to the prior APPLIED version | Administrator |

---

### Audit Log (`/api/v1/admin/audit/`)

| Method | Path | Description | Roles |
|--------|------|-------------|-------|
| GET | `/events/` | Query immutable audit log (filter by entity_type, entity_id, actor_id, date range) | Administrator |
| GET | `/events/security/` | Security-specific audit events (auth failures, lockouts, HMAC errors) | Administrator |
| GET | `/checkpoints/` | List active crash-safe checkpoints (in-progress jobs) | Administrator |

---

### User and Role Management (`/api/v1/admin/`)

> **Note:** User and role management is handled through the admin UI screens and is not
> currently exposed as separate REST endpoints. The admin UI calls the application layer directly.
> Future REST endpoints for user management will follow the pattern below when implemented.

| Planned Method | Path | Description | Roles |
|--------|------|-------------|-------|
| GET | `/users/` | List users | Administrator |
| POST | `/users/` | Create user (sets initial password, assigns role) | Administrator |
| PUT | `/users/{id}` | Update user (name, is_active, scope assignments) | Administrator |
| POST | `/users/{id}/unlock` | Manually clear lockout before 15-minute expiry | Administrator |

---

## Request/Response Examples (Prompt 4)

### POST /api/v1/resources/ — Create Draft Resource
Request:
```json
{"title": "Introduction to Algebra", "resource_type": "BOOK", "isbn": "978-0-00-000000-0"}
```
Response (201):
```json
{
  "resource_id": "uuid",
  "title": "Introduction to Algebra",
  "resource_type": "BOOK",
  "status": "DRAFT",
  "file_fingerprint": "sha256hex",
  "isbn": "978-0-00-000000-0",
  "dedup_key": "sha256hex",
  "created_by": "uuid",
  "created_at": "2024-01-01T12:00:00",
  "updated_at": "2024-01-01T12:00:00"
}
```

### POST /api/v1/resources/import/file — File Import with Dedup
Request: `multipart/form-data` with `file=<bytes>` and form fields: `title=...`, `resource_type=BOOK`, `isbn=...` (optional)

Response (201 — new):
```json
{"resource_id": "uuid", "revision_id": "uuid", "is_duplicate": false, "checkpoint_id": "uuid"}
```
Response (409 — duplicate):
```json
{"error": {"code": "DUPLICATE_RESOURCE", "message": "...", "details": {"existing_id": "uuid"}}}
```

### POST /api/v1/resources/{id}/submit-review
Request:
```json
{"reviewer_id": "uuid"}
```
Response (200):
```json
{"resource_id": "uuid", "status": "IN_REVIEW", ...}
```

### POST /api/v1/resources/{id}/publish
Request:
```json
{"reviewer_notes": "Content verified and approved for publication."}
```
Response (200):
```json
{"resource_id": "uuid", "status": "PUBLISHED", ...}
```

### POST /api/v1/inventory/items/ — Create Inventory Item
Request:
```json
{"sku": "BK-001", "name": "Reading Chair", "description": "Classroom reading chair", "unit_cost": "89.99"}
```
Response (201):
```json
{"item_id": "uuid", "sku": "BK-001", "name": "Reading Chair", "unit_cost": "89.99", "created_at": "..."}
```

### POST /api/v1/inventory/ledger/adjustment
Request:
```json
{
  "item_id": "uuid",
  "location_id": "uuid",
  "quantity_delta": 50,
  "reason_code": "RECEIPT",
  "status": "AVAILABLE",
  "batch_id": "BATCH-2026-04",
  "serial_id": null
}
```
Response (201):
```json
{
  "entry_id": "uuid", "item_id": "uuid", "location_id": "uuid",
  "entry_type": "ADJUSTMENT", "quantity_delta": 50, "quantity_after": 150,
  "operator_id": "uuid", "reason_code": "RECEIPT", "created_at": "...",
  "reference_id": null, "is_reversed": false, "reversal_of_id": null
}
```

### POST /api/v1/inventory/ledger/correction/{entry_id}
Request:
```json
{"reason_code": "DATA_ENTRY_ERROR"}
```
Response (201):
```json
{
  "entry_id": "uuid", "entry_type": "CORRECTION", "quantity_delta": -50, "quantity_after": 100,
  "is_reversed": false, "reversal_of_id": "original_entry_id"
}
```

### POST /api/v1/inventory/count-sessions/ — Open Count Session
Request:
```json
{"mode": "BLIND", "warehouse_id": "uuid"}
```
Response (201):
```json
{
  "session_id": "uuid", "mode": "BLIND", "status": "ACTIVE",
  "warehouse_id": "uuid", "created_by": "uuid",
  "created_at": "2024-01-01T10:00:00", "last_activity_at": "2024-01-01T10:00:00",
  "closed_at": null, "approved_by": null, "approved_at": null,
  "expires_at": "2024-01-01T18:00:00"
}
```

### POST /api/v1/inventory/count-sessions/{id}/line — Blind Mode
Request:
```json
{"item_id": "uuid", "location_id": "uuid", "counted_qty": 47}
```
Response (201) — blind mode hides expected_qty:
```json
{
  "line_id": "uuid", "session_id": "uuid",
  "expected_qty": null,
  "counted_qty": 47, "variance_qty": -3,
  "variance_value": "29.97", "requires_approval": false
}
```

### POST /api/v1/inventory/count-sessions/{id}/close
Response (200):
```json
{"session_id": "uuid", "status": "CLOSED", "closed_at": "2024-01-01T11:30:00", ...}
```

### POST /api/v1/inventory/relocations/ — Relocation
Request:
```json
{
  "item_id": "uuid",
  "from_location_id": "uuid",
  "to_location_id": "uuid",
  "quantity": 25,
  "device_source": "USB_SCANNER",
  "status": "AVAILABLE",
  "batch_id": "LOT-99",
  "serial_id": null
}
```
Response (201):
```json
{
  "relocation_id": "uuid", "item_id": "uuid",
  "from_location_id": "uuid", "to_location_id": "uuid",
  "quantity": 25, "operator_id": "uuid", "device_source": "USB_SCANNER",
  "created_at": "...",
  "ledger_debit_entry_id": "uuid",
  "ledger_credit_entry_id": "uuid"
}
```

---

## Admin Config — `POST /api/v1/admin/config/{category}/{key}`

Request (PUT):
```json
{
  "value": "25",
  "description": "Items per page"
}
```
Response (200):
```json
{
  "entry_id": "uuid",
  "category": "display",
  "key": "page_size",
  "value": "25",
  "description": "Items per page",
  "is_system": false,
  "updated_at": "2024-06-01T10:00:00"
}
```
Error (403) when trying to delete `is_system=true` entry:
```json
{"error": {"code": "INSUFFICIENT_PERMISSION", "message": "Config entry <uuid> is a system entry and cannot be deleted."}}
```

---

## Admin Taxonomy — `POST /api/v1/admin/taxonomy/categories/`

Request:
```json
{"name": "Science Fiction", "parent_id": null}
```
Response (201):
```json
{
  "category_id": "uuid",
  "name": "Science Fiction",
  "depth": 0,
  "path_slug": "science-fiction",
  "parent_id": null,
  "is_active": true
}
```
Child category (depth=1):
```json
{"name": "Hard SF", "parent_id": "<parent_uuid>"}
```
Response (201):
```json
{
  "category_id": "uuid",
  "name": "Hard SF",
  "depth": 1,
  "path_slug": "science-fiction/hard-sf",
  "parent_id": "<parent_uuid>",
  "is_active": true
}
```

---

## Integration Client — `POST /api/v1/integrations/`

Request:
```json
{"name": "ERP Sync", "description": "Financial system integration"}
```
Response (201):
```json
{
  "client": {
    "client_id": "uuid",
    "name": "ERP Sync",
    "description": "Financial system integration",
    "is_active": true,
    "created_at": "2024-06-01T10:00:00"
  },
  "initial_key": {
    "key_id": "uuid",
    "key_value": "64-char-hex-string",
    "expires_at": "2024-09-01T10:00:00",
    "is_active": true
  }
}
```

## Key Rotation — `POST /api/v1/integrations/{client_id}/rotate-key`

Response (200):
```json
{
  "key_id": "uuid",
  "key_value": "next-64-char-hex",
  "is_active": false,
  "is_next": true,
  "expires_at": "2024-09-01T10:00:00"
}
```
Then `POST /api/v1/integrations/{client_id}/commit-rotation` → promotes next→active.

---

## Update Package — `POST /api/v1/admin/updates/import`

Multipart upload (Content-Type: multipart/form-data):
- `file`: ZIP archive containing `manifest.json`

Response (201):
```json
{
  "package_id": "uuid",
  "version": "1.2.3",
  "status": "PENDING",
  "file_hash": "sha256hex",
  "imported_at": "2024-06-01T10:00:00",
  "can_rollback": false
}
```
Error (422) for invalid manifest:
```json
{"detail": "Invalid manifest: required fields missing: ['checksums']"}
```

## Apply Package — `POST /api/v1/admin/updates/{id}/apply`

Response (200):
```json
{"package_id": "uuid", "version": "1.2.3", "status": "APPLIED", ...}
```

## Rollback Package — `POST /api/v1/admin/updates/{id}/rollback`

Response (200) — returns the restored prior version:
```json
{"package_id": "uuid", "version": "1.1.0", "status": "APPLIED", ...}
```
Error (409) if package is not APPLIED or has no prior version:
```json
{"detail": "Package <uuid> cannot be rolled back."}
```

---

## Audit Events — `GET /api/v1/admin/audit/events/`

Query parameters: `entity_type`, `entity_id`, `actor_id`, `action`, `date_from` (ISO), `date_to` (ISO), `offset`, `limit`

Response (200):
```json
{
  "items": [
    {
      "event_id": "uuid",
      "entity_type": "resource",
      "entity_id": "uuid",
      "action": "PUBLISHED",
      "actor_id": "uuid",
      "timestamp": "2024-06-01T10:00:00",
      "metadata": {"reviewer_notes": "Approved for library"}
    }
  ],
  "total": 1,
  "offset": 0,
  "limit": 50
}
```

Security events — `GET /api/v1/admin/audit/events/security/` — filters for actions: `LOGIN`, `LOGIN_FAILED`, `ACCOUNT_LOCKED`, `LOGOUT`, `KEY_ROTATION`.

Checkpoints — `GET /api/v1/admin/audit/checkpoints/` — returns `ACTIVE`, `FAILED`, `ABANDONED` records:
```json
[
  {
    "checkpoint_id": "uuid",
    "job_type": "approval",
    "job_id": "session-uuid",
    "status": "ACTIVE",
    "created_at": "2024-06-01T10:00:00",
    "updated_at": "2024-06-01T10:30:00",
    "state_json": "{\"session_id\": \"...\"}"
  }
]
```

---

## Integration Boundaries

The local REST API is the **only** supported integration surface. There are no:
- External HTTP webhooks received from outside the machine
- Database connection sharing with external processes
- Shared-memory IPC mechanisms
- Email or internet-based notification delivery

Outbound events are delivered by writing JSON files to a configurable LAN-shared folder path (`DC_LAN_EVENTS_PATH`). Consuming systems poll that folder. The event delivery mechanism is one-way and fire-and-forget with a retry queue for failed writes.
