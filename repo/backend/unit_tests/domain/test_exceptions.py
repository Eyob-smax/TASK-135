"""
Unit tests for the District Console domain exception hierarchy.

Verifies:
  - Each exception sets .code to the correct error code string
  - Each exception stores domain-specific fields (resource_id, limit, etc.)
  - All concrete exceptions inherit from DistrictConsoleError
  - Exception messages contain the relevant identifiers

These tests catch regressions where exception constructors, field names, or
error codes are accidentally changed — especially important because the API
layer and the UI error-display logic depend on exact code strings.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from district_console.domain.exceptions import (
    AppendOnlyViolationError,
    DistrictConsoleError,
    DomainValidationError,
    DuplicateResourceError,
    InsufficientPermissionError,
    InsufficientStockError,
    IntegrationSigningError,
    InvalidCredentialsError,
    InvalidStateTransitionError,
    LockoutError,
    RateLimitExceededError,
    RecordLockedError,
    ResourceNotFoundError,
    RevisionLimitError,
    ScopeViolationError,
    SessionExpiredError,
    StockFrozenError,
)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class TestDistrictConsoleError:
    def test_all_exceptions_inherit_from_base(self):
        errors = [
            InvalidCredentialsError(),
            SessionExpiredError(),
            InsufficientPermissionError("some.perm"),
            DuplicateResourceError("id-1", "key-1"),
            ResourceNotFoundError("res-1"),
            RevisionLimitError("res-1", 10),
            InvalidStateTransitionError("DRAFT", "PUBLISHED"),
            AppendOnlyViolationError("table", "id-1"),
            InsufficientStockError("i", "l", 0, 1),
            StockFrozenError("bal-1"),
        ]
        for exc in errors:
            assert isinstance(exc, DistrictConsoleError), (
                f"{type(exc).__name__} is not a DistrictConsoleError"
            )

    def test_base_code_defaults_to_class_name(self):
        exc = DistrictConsoleError("some error")
        assert exc.code == "DistrictConsoleError"

    def test_base_custom_code_is_respected(self):
        exc = DistrictConsoleError("msg", code="MY_CODE")
        assert exc.code == "MY_CODE"

    def test_message_attribute_matches_constructor_message(self):
        exc = DistrictConsoleError("hello world")
        assert exc.message == "hello world"


# ---------------------------------------------------------------------------
# Authentication exceptions
# ---------------------------------------------------------------------------

class TestAuthenticationExceptions:
    def test_invalid_credentials_code(self):
        assert InvalidCredentialsError().code == "INVALID_CREDENTIALS"

    def test_invalid_credentials_message_not_empty(self):
        assert InvalidCredentialsError().message != ""

    def test_lockout_error_code(self):
        locked_until = datetime.utcnow() + timedelta(minutes=15)
        assert LockoutError(locked_until).code == "ACCOUNT_LOCKED"

    def test_lockout_error_locked_until_field(self):
        locked_until = datetime.utcnow() + timedelta(minutes=15)
        exc = LockoutError(locked_until)
        assert exc.locked_until == locked_until

    def test_session_expired_code(self):
        assert SessionExpiredError().code == "SESSION_EXPIRED"

    def test_insufficient_permission_code(self):
        exc = InsufficientPermissionError("resources.publish")
        assert exc.code == "INSUFFICIENT_PERMISSION"

    def test_insufficient_permission_stores_required_permission(self):
        exc = InsufficientPermissionError("inventory.freeze")
        assert exc.required_permission == "inventory.freeze"

    def test_insufficient_permission_includes_perm_in_message(self):
        exc = InsufficientPermissionError("resources.publish")
        assert "resources.publish" in exc.message

    def test_scope_violation_code(self):
        exc = ScopeViolationError("Resource", "res-123")
        assert exc.code == "SCOPE_VIOLATION"

    def test_scope_violation_entity_fields(self):
        exc = ScopeViolationError("InventoryItem", "item-999")
        assert exc.entity_type == "InventoryItem"
        assert exc.entity_id == "item-999"

    def test_scope_violation_includes_entity_id_in_message(self):
        exc = ScopeViolationError("Resource", "res-abc")
        assert "res-abc" in exc.message


# ---------------------------------------------------------------------------
# Resource library exceptions
# ---------------------------------------------------------------------------

class TestResourceLibraryExceptions:
    def test_resource_not_found_code(self):
        assert ResourceNotFoundError("res-abc").code == "NOT_FOUND"

    def test_resource_not_found_stores_resource_id(self):
        exc = ResourceNotFoundError("res-xyz")
        assert exc.resource_id == "res-xyz"

    def test_duplicate_resource_code(self):
        assert DuplicateResourceError("id-1", "key-1").code == "DUPLICATE_RESOURCE"

    def test_duplicate_resource_fields(self):
        exc = DuplicateResourceError("existing-id", "dedup-key-xyz")
        assert exc.existing_id == "existing-id"
        assert exc.dedup_key == "dedup-key-xyz"

    def test_revision_limit_code(self):
        assert RevisionLimitError("res-1", 10).code == "REVISION_LIMIT_REACHED"

    def test_revision_limit_fields(self):
        exc = RevisionLimitError("res-uuid", 10)
        assert exc.resource_id == "res-uuid"
        assert exc.limit == 10

    def test_revision_limit_message_contains_limit(self):
        exc = RevisionLimitError("res-1", 10)
        assert "10" in exc.message

    def test_invalid_state_transition_code(self):
        exc = InvalidStateTransitionError("DRAFT", "PUBLISHED", "Resource")
        assert exc.code == "INVALID_STATE_TRANSITION"

    def test_invalid_state_transition_fields(self):
        exc = InvalidStateTransitionError("IN_REVIEW", "DRAFT", "Resource")
        assert exc.from_status == "IN_REVIEW"
        assert exc.to_status == "DRAFT"
        assert exc.entity_type == "Resource"

    def test_invalid_state_transition_default_entity_type(self):
        exc = InvalidStateTransitionError("A", "B")
        assert exc.entity_type == "Entity"

    def test_invalid_state_transition_message_contains_statuses(self):
        exc = InvalidStateTransitionError("DRAFT", "PUBLISHED")
        assert "DRAFT" in exc.message
        assert "PUBLISHED" in exc.message


# ---------------------------------------------------------------------------
# Inventory and ledger exceptions
# ---------------------------------------------------------------------------

class TestInventoryExceptions:
    def test_append_only_violation_code(self):
        assert AppendOnlyViolationError("ledger_entries", "e-1").code == "APPEND_ONLY_VIOLATION"

    def test_append_only_violation_fields(self):
        exc = AppendOnlyViolationError("ledger_entries", "entry-1")
        assert exc.table == "ledger_entries"
        assert exc.record_id == "entry-1"

    def test_insufficient_stock_code(self):
        assert InsufficientStockError("i", "l", 0, 1).code == "INSUFFICIENT_STOCK"

    def test_insufficient_stock_fields(self):
        exc = InsufficientStockError("item-1", "loc-1", available=5, requested=10)
        assert exc.item_id == "item-1"
        assert exc.location_id == "loc-1"
        assert exc.available == 5
        assert exc.requested == 10

    def test_stock_frozen_code(self):
        assert StockFrozenError("bal-1").code == "STOCK_FROZEN"

    def test_stock_frozen_field(self):
        assert StockFrozenError("balance-uuid").stock_balance_id == "balance-uuid"

    def test_domain_validation_error_code(self):
        exc = DomainValidationError("age_min", -1, "0 <= age_min <= 18")
        assert exc.code == "VALIDATION_ERROR"

    def test_domain_validation_error_fields(self):
        exc = DomainValidationError("field_name", "bad", "constraint-rule")
        assert exc.field == "field_name"
        assert exc.value == "bad"
        assert exc.constraint == "constraint-rule"

    def test_record_locked_code(self):
        expires = datetime.utcnow() + timedelta(minutes=5)
        assert RecordLockedError("R", "r-1", "alice", expires).code == "RECORD_LOCKED"

    def test_record_locked_fields(self):
        expires = datetime.utcnow() + timedelta(minutes=5)
        exc = RecordLockedError("Resource", "res-1", "alice", expires)
        assert exc.entity_type == "Resource"
        assert exc.entity_id == "res-1"
        assert exc.lock_holder == "alice"
        assert exc.expires_at == expires


# ---------------------------------------------------------------------------
# Integration exceptions
# ---------------------------------------------------------------------------

class TestIntegrationExceptions:
    def test_integration_signing_error_code(self):
        assert IntegrationSigningError().code == "SIGNATURE_INVALID"

    def test_rate_limit_exceeded_code(self):
        assert RateLimitExceededError("client-1", 60).code == "RATE_LIMIT_EXCEEDED"

    def test_rate_limit_exceeded_fields(self):
        exc = RateLimitExceededError("client-abc", 60)
        assert exc.client_id == "client-abc"
        assert exc.limit == 60

    def test_rate_limit_exceeded_message_contains_client_and_limit(self):
        exc = RateLimitExceededError("client-xyz", 60)
        assert "client-xyz" in exc.message
        assert "60" in exc.message
