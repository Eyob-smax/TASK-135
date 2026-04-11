"""
Resource metadata taxonomy entities.

ResourceMetadata holds all descriptive fields for a resource record.
Category forms a multi-level tree. TaxonomyValidationRule defines
field-level constraints stored in the database and enforced at import time.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from district_console.domain.enums import TimelinesType


@dataclass
class Category:
    """
    A node in the multi-level category tree.

    parent_id is None for top-level categories.
    depth is 0-based (0 = root, 1 = child, 2 = grandchild, etc.).
    path_slug is a slash-delimited ancestry path, e.g. "science/biology/genetics".
    """
    id: uuid.UUID
    name: str
    depth: int
    path_slug: str
    parent_id: Optional[uuid.UUID] = None
    is_active: bool = True


@dataclass
class ResourceMetadata:
    """
    Descriptive metadata for a resource record.

    Validation is enforced by the validate() method, which raises
    DomainValidationError for any constraint violation. This method
    must be called before persisting new or updated metadata.
    """
    resource_id: uuid.UUID
    category_ids: list[uuid.UUID] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    timeliness: Optional[TimelinesType] = None
    source: Optional[str] = None
    copyright: Optional[str] = None
    theme: Optional[str] = None
    difficulty_level: Optional[str] = None
    age_range_min: Optional[int] = None
    age_range_max: Optional[int] = None

    def validate(self) -> None:
        """
        Raise DomainValidationError if any metadata constraint is violated.

        Constraints:
        - age_range_min and age_range_max must both be set or both absent
        - If set, age_range must satisfy policies.age_range_valid()
        - timeliness must be a valid TimelinesType value
        """
        from district_console.domain.exceptions import DomainValidationError
        from district_console.domain.policies import age_range_valid, timeliness_valid

        # Age range consistency
        if (self.age_range_min is None) != (self.age_range_max is None):
            raise DomainValidationError(
                field="age_range",
                value=(self.age_range_min, self.age_range_max),
                constraint="age_range_min and age_range_max must both be set or both absent.",
            )

        if self.age_range_min is not None and self.age_range_max is not None:
            if not age_range_valid(self.age_range_min, self.age_range_max):
                raise DomainValidationError(
                    field="age_range",
                    value=(self.age_range_min, self.age_range_max),
                    constraint="Age range must be between 0 and 18 with min <= max.",
                )

        if self.timeliness is not None:
            if not timeliness_valid(self.timeliness.value if isinstance(self.timeliness, TimelinesType) else self.timeliness):
                raise DomainValidationError(
                    field="timeliness",
                    value=self.timeliness,
                    constraint="timeliness must be one of EVERGREEN, CURRENT, or ARCHIVED.",
                )


@dataclass(frozen=True)
class TaxonomyValidationRule:
    """
    A configurable field-level validation rule stored in the database.

    rule_type examples: "enum", "range", "regex", "required"
    rule_value is the constraint specification (enum values list, range bounds, regex pattern).
    """
    id: uuid.UUID
    field: str
    rule_type: str
    rule_value: Any
    is_active: bool = True
    description: Optional[str] = None
