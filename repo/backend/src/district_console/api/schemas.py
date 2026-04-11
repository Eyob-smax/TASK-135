"""
Canonical Pydantic request/response schemas for the District Console local REST API.

These are the single source of truth for API contract types. Tests in
api_tests/ validate against these shapes. All models use Pydantic v2.

Schema notes:
  - ErrorEnvelope and ErrorDetail use extra="forbid" for strict validation.
  - LoginRequest uses extra="forbid" to reject unexpected fields.
  - Datetime fields are ISO-8601 strings (not datetime objects) to simplify
    JSON serialisation across the PyQt–FastAPI boundary.
  - PaginatedResponse is a Generic model; use as PaginatedResponse[ResourceSchema].
"""
from __future__ import annotations

from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Error envelope (matches docs/api-spec.md error contract)
# ---------------------------------------------------------------------------

class ErrorDetail(BaseModel):
    """The inner error object within an ErrorEnvelope."""
    model_config = {"extra": "forbid"}

    code: str
    message: str
    details: Optional[Any] = None


class ErrorEnvelope(BaseModel):
    """Standard API error response wrapper: {"error": {"code": ..., "message": ...}}"""
    model_config = {"extra": "forbid"}

    error: ErrorDetail


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    """Credentials for POST /api/v1/auth/login."""
    model_config = {"extra": "forbid"}

    username: str
    password: str


class LoginResponse(BaseModel):
    """Successful login response with session token."""

    user_id: str
    username: str
    roles: List[str]          # List of RoleType string values
    token: str                # Session token — include in Authorization: Bearer header
    expires_at: str           # ISO-8601 UTC expiry timestamp


class WhoAmIResponse(BaseModel):
    """Response for GET /api/v1/auth/whoami."""

    user_id: str
    username: str
    roles: List[str]
    scopes: List[dict]        # Each dict: {scope_type, scope_ref_id}


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class PaginatedResponse(BaseModel, Generic[T]):
    """
    Standard paginated list envelope.

    Usage::
        @router.get("/", response_model=PaginatedResponse[ResourceSchema])
        async def list_resources(...) -> PaginatedResponse[ResourceSchema]:
            ...
    """
    items: List[T]
    total: int
    offset: int
    limit: int


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

class ResourceCreate(BaseModel):
    model_config = {"extra": "forbid"}

    title: str
    resource_type: str
    isbn: Optional[str] = None
    owner_scope_type: Optional[str] = None
    owner_scope_ref_id: Optional[str] = None


class ResourceUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    title: Optional[str] = None
    isbn: Optional[str] = None


class ResourceMetadataResponse(BaseModel):
    min_age: Optional[int] = None
    max_age: Optional[int] = None
    timeliness_type: Optional[str] = None


class ResourceResponse(BaseModel):
    resource_id: str
    title: str
    resource_type: str
    status: str
    file_fingerprint: str
    isbn: Optional[str] = None
    dedup_key: str
    created_by: str
    created_at: str
    updated_at: str
    metadata: Optional[ResourceMetadataResponse] = None
    owner_scope_type: Optional[str] = None
    owner_scope_ref_id: Optional[str] = None


class ResourceRevisionResponse(BaseModel):
    revision_id: str
    resource_id: str
    revision_number: int
    file_hash: str
    file_size: int
    imported_by: str
    created_at: str


class ReviewSubmitRequest(BaseModel):
    model_config = {"extra": "forbid"}

    reviewer_id: str


class PublishRequest(BaseModel):
    model_config = {"extra": "forbid"}

    reviewer_notes: str


class ClassifyRequest(BaseModel):
    model_config = {"extra": "forbid"}

    min_age: int
    max_age: int
    timeliness_type: str


class ImportFileResponse(BaseModel):
    resource_id: str
    revision_id: str
    is_duplicate: bool
    checkpoint_id: str


class ImportCsvResponse(BaseModel):
    created: List[str]
    duplicates: List[str]
    errors: List[str]
    checkpoint_id: str


# ---------------------------------------------------------------------------
# Inventory — Items
# ---------------------------------------------------------------------------

class InventoryItemCreate(BaseModel):
    model_config = {"extra": "forbid"}

    sku: str
    name: str
    description: str = ""
    unit_cost: str  # Decimal as string


class InventoryItemUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    name: Optional[str] = None
    description: Optional[str] = None
    unit_cost: Optional[str] = None


class InventoryItemResponse(BaseModel):
    item_id: str
    sku: str
    name: str
    description: str
    unit_cost: str
    created_at: str


# ---------------------------------------------------------------------------
# Inventory — Warehouses and Locations
# ---------------------------------------------------------------------------

class WarehouseCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    school_id: str
    address: str = ""


class WarehouseResponse(BaseModel):
    warehouse_id: str
    name: str
    school_id: str
    address: str
    is_active: bool


class LocationCreate(BaseModel):
    model_config = {"extra": "forbid"}

    warehouse_id: str
    zone: str
    aisle: str
    bin_label: str


class LocationResponse(BaseModel):
    location_id: str
    warehouse_id: str
    zone: str
    aisle: str
    bin_label: str
    is_active: bool


# ---------------------------------------------------------------------------
# Inventory — Stock and Freeze
# ---------------------------------------------------------------------------

class StockBalanceResponse(BaseModel):
    balance_id: str
    item_id: str
    location_id: str
    status: str
    quantity: int
    is_frozen: bool
    freeze_reason: Optional[str] = None
    batch_id: Optional[str] = None
    serial_id: Optional[str] = None


class FreezeRequest(BaseModel):
    model_config = {"extra": "forbid"}

    reason: str


# ---------------------------------------------------------------------------
# Inventory — Ledger
# ---------------------------------------------------------------------------

class LedgerEntryResponse(BaseModel):
    entry_id: str
    item_id: str
    location_id: str
    entry_type: str
    quantity_delta: int
    quantity_after: int
    operator_id: str
    reason_code: str
    created_at: str
    reference_id: Optional[str] = None
    is_reversed: bool
    reversal_of_id: Optional[str] = None


class AdjustmentRequest(BaseModel):
    model_config = {"extra": "forbid"}

    item_id: str
    location_id: str
    quantity_delta: int
    reason_code: str
    status: Optional[str] = None
    batch_id: Optional[str] = None
    serial_id: Optional[str] = None


class CorrectionRequest(BaseModel):
    model_config = {"extra": "forbid"}

    reason_code: str


# ---------------------------------------------------------------------------
# Count sessions
# ---------------------------------------------------------------------------

class CountSessionCreate(BaseModel):
    model_config = {"extra": "forbid"}

    mode: str
    warehouse_id: str


class CountSessionResponse(BaseModel):
    session_id: str
    mode: str
    status: str
    warehouse_id: str
    created_by: str
    created_at: str
    last_activity_at: str
    closed_at: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    expires_at: str


class CountLineCreate(BaseModel):
    model_config = {"extra": "forbid"}

    item_id: str
    location_id: str
    counted_qty: int
    reason_code: Optional[str] = None


class CountLineUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    counted_qty: int


class CountLineResponse(BaseModel):
    line_id: str
    session_id: str
    item_id: str
    location_id: str
    expected_qty: Optional[int]  # null for BLIND mode
    counted_qty: int
    variance_qty: int
    variance_value: str
    requires_approval: bool
    reason_code: Optional[str] = None


class CountApprovalRequest(BaseModel):
    model_config = {"extra": "forbid"}

    notes: str


class CountSessionDetailResponse(BaseModel):
    session_id: str
    mode: str
    status: str
    warehouse_id: str
    created_by: str
    created_at: str
    last_activity_at: str
    closed_at: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    expires_at: str
    lines: List[CountLineResponse]


# ---------------------------------------------------------------------------
# Relocations
# ---------------------------------------------------------------------------

class RelocationCreate(BaseModel):
    model_config = {"extra": "forbid"}

    item_id: str
    from_location_id: str
    to_location_id: str
    quantity: int
    device_source: str
    status: Optional[str] = None
    batch_id: Optional[str] = None
    serial_id: Optional[str] = None


class RelocationResponse(BaseModel):
    relocation_id: str
    item_id: str
    from_location_id: str
    to_location_id: str
    quantity: int
    operator_id: str
    device_source: str
    created_at: str
    ledger_debit_entry_id: str
    ledger_credit_entry_id: str


# ---------------------------------------------------------------------------
# Configuration center
# ---------------------------------------------------------------------------

class ConfigDictionaryResponse(BaseModel):
    entry_id: str
    category: str
    key: str
    value: str
    description: str
    is_system: bool
    updated_by: Optional[str] = None
    updated_at: Optional[str] = None


class ConfigUpsertRequest(BaseModel):
    model_config = {"extra": "forbid"}

    value: str
    description: str = ""


class WorkflowNodeResponse(BaseModel):
    node_id: str
    workflow_name: str
    from_state: str
    to_state: str
    required_role: str
    condition_json: Optional[str] = None


class WorkflowNodeCreate(BaseModel):
    model_config = {"extra": "forbid"}

    workflow_name: str
    from_state: str
    to_state: str
    required_role: str
    condition_json: Optional[str] = None


class NotificationTemplateResponse(BaseModel):
    template_id: str
    name: str
    event_type: str
    subject_template: str
    body_template: str
    is_active: bool


class NotificationTemplateUpsert(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    event_type: str
    subject_template: str
    body_template: str
    is_active: bool = True


class DistrictDescriptorResponse(BaseModel):
    descriptor_id: str
    key: str
    value: str
    description: str
    region: Optional[str] = None


class DistrictDescriptorUpsert(BaseModel):
    model_config = {"extra": "forbid"}

    value: str
    description: str = ""
    region: Optional[str] = None


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

class CategoryResponse(BaseModel):
    category_id: str
    name: str
    depth: int
    path_slug: str
    parent_id: Optional[str] = None
    is_active: bool


class CategoryCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    parent_id: Optional[str] = None


class CategoryUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str


class TaxonomyRuleResponse(BaseModel):
    rule_id: str
    field: str
    rule_type: str
    rule_value: str
    is_active: bool
    description: Optional[str] = None


class TaxonomyRuleCreate(BaseModel):
    model_config = {"extra": "forbid"}

    field: str
    rule_type: str
    rule_value: str
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------

class IntegrationClientResponse(BaseModel):
    client_id: str
    name: str
    description: str
    is_active: bool
    created_at: str


class IntegrationClientCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    description: str = ""


class HmacKeyResponse(BaseModel):
    key_id: str
    client_id: str
    key_value: Optional[str] = None   # raw key — present only at creation/rotation; None otherwise
    created_at: str
    expires_at: str
    is_active: bool
    is_next: bool


class OutboundEventResponse(BaseModel):
    event_id: str
    client_id: str
    event_type: str
    status: str
    created_at: str
    delivered_at: Optional[str] = None
    retry_count: int
    last_error: Optional[str] = None


class OutboundEventCreate(BaseModel):
    model_config = {"extra": "forbid"}

    event_type: str
    payload: dict


# ---------------------------------------------------------------------------
# Update packages
# ---------------------------------------------------------------------------

class UpdatePackageResponse(BaseModel):
    package_id: str
    version: str
    file_path: str
    file_hash: str
    status: str
    imported_at: str
    imported_by: str
    prior_version_ref: Optional[str] = None
    can_rollback: bool


# ---------------------------------------------------------------------------
# Audit / admin
# ---------------------------------------------------------------------------

class AuditEventResponse(BaseModel):
    event_id: str
    entity_type: str
    entity_id: str
    action: str
    actor_id: str
    timestamp: str
    metadata: dict


class CheckpointStatusResponse(BaseModel):
    checkpoint_id: str
    job_type: str
    job_id: str
    status: str
    created_at: str
    updated_at: str
    state_json: str
