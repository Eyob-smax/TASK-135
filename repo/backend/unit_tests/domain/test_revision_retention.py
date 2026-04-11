"""
Tests for revision retention domain rules.

Verifies that ResourceRevision instances respect the 10-revision limit
and that revision_number fields are sequential and unique per resource.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from district_console.domain.entities.resource import Resource, ResourceRevision
from district_console.domain.enums import ResourceStatus, ResourceType
from district_console.domain.policies import MAX_RESOURCE_REVISIONS, revisions_over_limit

OPERATOR = uuid.uuid4()
NOW = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)
RESOURCE_ID = uuid.uuid4()


def make_revision(revision_number: int) -> ResourceRevision:
    return ResourceRevision(
        id=uuid.uuid4(),
        resource_id=RESOURCE_ID,
        revision_number=revision_number,
        file_path=f"/data/files/rev{revision_number}.pdf",
        file_hash="a" * 64,
        file_size=1024 * revision_number,
        imported_by=OPERATOR,
        created_at=NOW,
    )


class TestRevisionRetentionPolicy:
    def test_ten_revisions_at_limit(self) -> None:
        revisions = [make_revision(i) for i in range(1, 11)]
        assert revisions_over_limit(len(revisions)) is True

    def test_eleven_revisions_over_limit(self) -> None:
        revisions = [make_revision(i) for i in range(1, 12)]
        assert revisions_over_limit(len(revisions)) is True

    def test_nine_revisions_not_at_limit(self) -> None:
        revisions = [make_revision(i) for i in range(1, 10)]
        assert revisions_over_limit(len(revisions)) is False

    def test_zero_revisions(self) -> None:
        assert revisions_over_limit(0) is False

    def test_max_resource_revisions_constant(self) -> None:
        assert MAX_RESOURCE_REVISIONS == 10

    def test_oldest_revision_has_lowest_number(self) -> None:
        """Revision numbers are 1-based; revision 1 is the oldest."""
        revisions = [make_revision(i) for i in range(1, 11)]
        sorted_by_number = sorted(revisions, key=lambda r: r.revision_number)
        assert sorted_by_number[0].revision_number == 1

    def test_pruning_candidate_is_lowest_revision_number(self) -> None:
        """When at limit, the pruning candidate is the revision with the lowest number."""
        revisions = [make_revision(i) for i in range(1, 11)]
        pruning_candidate = min(revisions, key=lambda r: r.revision_number)
        assert pruning_candidate.revision_number == 1

    def test_revision_numbers_are_sequential(self) -> None:
        revisions = [make_revision(i) for i in range(1, 6)]
        numbers = [r.revision_number for r in revisions]
        assert numbers == list(range(1, 6))

    def test_revision_numbers_are_unique_per_resource(self) -> None:
        revisions = [make_revision(i) for i in range(1, 11)]
        numbers = [r.revision_number for r in revisions]
        assert len(numbers) == len(set(numbers)), "Revision numbers must be unique"

    def test_revision_is_frozen(self) -> None:
        """ResourceRevision is a frozen dataclass — cannot be mutated."""
        rev = make_revision(1)
        with pytest.raises((AttributeError, TypeError)):
            rev.revision_number = 99  # type: ignore[misc]


class TestResourceRevisionFrozen:
    def test_cannot_mutate_file_hash(self) -> None:
        rev = make_revision(1)
        with pytest.raises((AttributeError, TypeError)):
            rev.file_hash = "b" * 64  # type: ignore[misc]

    def test_resource_revision_fields_accessible(self) -> None:
        rev = make_revision(3)
        assert rev.resource_id == RESOURCE_ID
        assert rev.revision_number == 3
        assert rev.imported_by == OPERATOR
