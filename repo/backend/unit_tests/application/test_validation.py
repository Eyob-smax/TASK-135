"""
Unit tests for ValidationResult — the multi-field validation accumulator
in application/validation.py.

Covers:
  - Initial valid state and noop raise_if_invalid
  - add_error marks invalid and accumulates FieldError objects
  - raise_if_invalid raises DomainValidationError with first error's fields
  - to_dict serialises all accumulated errors
  - FieldError is frozen (immutable dataclass)
"""
from __future__ import annotations

import pytest

from district_console.application.validation import FieldError, ValidationResult
from district_console.domain.exceptions import DomainValidationError


# ---------------------------------------------------------------------------
# Valid (no-error) result
# ---------------------------------------------------------------------------

class TestValidationResultValid:
    def test_new_result_is_valid(self):
        result = ValidationResult()
        assert result.valid is True

    def test_no_errors_initially(self):
        result = ValidationResult()
        assert result.errors == []

    def test_raise_if_valid_is_noop(self):
        """raise_if_invalid() on a clean result must not raise."""
        result = ValidationResult()
        result.raise_if_invalid()  # Should not raise

    def test_to_dict_empty_when_valid(self):
        result = ValidationResult()
        assert result.to_dict() == []


# ---------------------------------------------------------------------------
# Result with errors
# ---------------------------------------------------------------------------

class TestValidationResultErrors:
    def test_add_error_marks_invalid(self):
        result = ValidationResult()
        result.add_error("field1", "Cannot be empty", "required")
        assert result.valid is False

    def test_add_error_appends_field_error(self):
        result = ValidationResult()
        result.add_error("age_min", "Must be non-negative", "0 <= age_min <= 18")
        assert len(result.errors) == 1
        assert result.errors[0].field == "age_min"
        assert result.errors[0].constraint == "0 <= age_min <= 18"

    def test_add_multiple_errors_accumulates_all(self):
        result = ValidationResult()
        result.add_error("age_min", "Out of range", "0 <= age_min")
        result.add_error("age_max", "Must exceed age_min", "age_min <= age_max")
        assert len(result.errors) == 2

    def test_raise_if_invalid_raises_domain_validation_error(self):
        result = ValidationResult()
        result.add_error("myfield", "Is invalid", "must be positive")
        with pytest.raises(DomainValidationError) as exc_info:
            result.raise_if_invalid()
        assert exc_info.value.code == "VALIDATION_ERROR"

    def test_raise_if_invalid_uses_first_error_constraint(self):
        """When multiple errors exist, raise uses the *first* accumulated error."""
        result = ValidationResult()
        result.add_error("first_field", "First error", "constraint-1")
        result.add_error("second_field", "Second error", "constraint-2")
        with pytest.raises(DomainValidationError) as exc_info:
            result.raise_if_invalid()
        # First error's constraint is embedded in the raised exception message
        assert "constraint-1" in exc_info.value.message

    def test_to_dict_returns_all_errors_in_order(self):
        result = ValidationResult()
        result.add_error("f1", "Msg1", "c1")
        result.add_error("f2", "Msg2", "c2")
        errors = result.to_dict()
        assert len(errors) == 2
        assert errors[0]["field"] == "f1"
        assert errors[0]["message"] == "Msg1"
        assert errors[0]["constraint"] == "c1"
        assert errors[1]["field"] == "f2"

    def test_to_dict_keys_match_expected_schema(self):
        result = ValidationResult()
        result.add_error("x", "y", "z")
        error_dict = result.to_dict()[0]
        assert set(error_dict.keys()) == {"field", "message", "constraint"}


# ---------------------------------------------------------------------------
# FieldError
# ---------------------------------------------------------------------------

class TestFieldError:
    def test_field_error_is_frozen(self):
        """FieldError is a frozen dataclass — mutation must raise."""
        err = FieldError(field="x", message="y", constraint="z")
        with pytest.raises((AttributeError, TypeError)):
            err.field = "new_value"  # type: ignore[misc]

    def test_field_error_stores_all_fields(self):
        err = FieldError(field="target_field", message="error msg", constraint="rule")
        assert err.field == "target_field"
        assert err.message == "error msg"
        assert err.constraint == "rule"
