"""
Structured validation result model for use-case services.

Provides a ValidationResult accumulator that collects multiple field errors
before raising, enabling callers to report all invalid fields in a single
response rather than failing on the first violation.

Usage:
    result = ValidationResult()
    if not age_range_valid(metadata.age_range_min, metadata.age_range_max):
        result.add_error("age_range", "Invalid age range", "0 <= min <= max <= 18")
    if not timeliness_valid(metadata.timeliness):
        result.add_error("timeliness", "Invalid timeliness value", "EVERGREEN | CURRENT | ARCHIVED")
    result.raise_if_invalid()  # Raises DomainValidationError for the first error

For API responses, use to_dict() to convert errors to a list of dicts
suitable for the ErrorEnvelope.details field.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from district_console.domain.exceptions import DomainValidationError


@dataclass(frozen=True)
class FieldError:
    """An individual field constraint violation."""
    field: str
    message: str
    constraint: str


@dataclass
class ValidationResult:
    """
    Accumulates field-level validation errors before raising.

    Example::
        result = ValidationResult()
        if not ok:
            result.add_error("field", "Human-readable message", "constraint rule")
        result.raise_if_invalid()
    """
    valid: bool = True
    errors: list[FieldError] = field(default_factory=list)

    def add_error(
        self,
        field_name: str,
        message: str,
        constraint: str,
    ) -> None:
        """
        Record a validation failure for a field.

        Also sets valid=False so raise_if_invalid() knows to raise.
        """
        self.valid = False
        self.errors.append(
            FieldError(field=field_name, message=message, constraint=constraint)
        )

    def raise_if_invalid(self) -> None:
        """
        Raise DomainValidationError for the first accumulated error.

        If valid is True (no errors added), this is a no-op.
        """
        if self.valid:
            return
        first = self.errors[0]
        raise DomainValidationError(
            field=first.field,
            value=None,
            constraint=first.constraint,
        )

    def to_dict(self) -> list[dict[str, Any]]:
        """
        Serialise all errors to a list of dicts for API error details.

        Suitable for use as ErrorEnvelope.error.details in responses.
        """
        return [
            {
                "field": err.field,
                "message": err.message,
                "constraint": err.constraint,
            }
            for err in self.errors
        ]
