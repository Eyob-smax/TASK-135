"""
Tests for domain enumerations and workflow transition validation.
"""
from __future__ import annotations

import pytest

from district_console.domain.enums import (
    CheckpointStatus,
    CountMode,
    CountSessionStatus,
    DeviceSource,
    LedgerEntryType,
    ResourceStatus,
    ResourceType,
    ReviewDecision,
    RoleType,
    ScopeType,
    StockStatus,
    TimelinesType,
    UpdateStatus,
    VALID_RESOURCE_TRANSITIONS,
    validate_resource_transition,
)
from district_console.domain.exceptions import InvalidStateTransitionError


class TestResourceTypeEnum:
    def test_all_members_present(self) -> None:
        assert ResourceType.BOOK.value == "BOOK"
        assert ResourceType.PICTURE_BOOK.value == "PICTURE_BOOK"
        assert ResourceType.ARTICLE.value == "ARTICLE"
        assert ResourceType.AUDIO.value == "AUDIO"

    def test_member_count(self) -> None:
        assert len(ResourceType) == 4


class TestResourceStatusEnum:
    def test_all_members_present(self) -> None:
        assert ResourceStatus.DRAFT.value == "DRAFT"
        assert ResourceStatus.IN_REVIEW.value == "IN_REVIEW"
        assert ResourceStatus.PUBLISHED.value == "PUBLISHED"
        assert ResourceStatus.UNPUBLISHED.value == "UNPUBLISHED"

    def test_member_count(self) -> None:
        assert len(ResourceStatus) == 4


class TestTimelinesTypeEnum:
    def test_all_members_present(self) -> None:
        assert TimelinesType.EVERGREEN.value == "EVERGREEN"
        assert TimelinesType.CURRENT.value == "CURRENT"
        assert TimelinesType.ARCHIVED.value == "ARCHIVED"

    def test_member_count(self) -> None:
        assert len(TimelinesType) == 3


class TestCountModeEnum:
    def test_all_members_present(self) -> None:
        assert CountMode.OPEN.value == "OPEN"
        assert CountMode.BLIND.value == "BLIND"
        assert CountMode.CYCLE.value == "CYCLE"


class TestLedgerEntryTypeEnum:
    def test_all_members_present(self) -> None:
        assert LedgerEntryType.RECEIPT.value == "RECEIPT"
        assert LedgerEntryType.ADJUSTMENT.value == "ADJUSTMENT"
        assert LedgerEntryType.RELOCATION.value == "RELOCATION"
        assert LedgerEntryType.CORRECTION.value == "CORRECTION"
        assert LedgerEntryType.COUNT_CLOSE.value == "COUNT_CLOSE"

    def test_member_count(self) -> None:
        assert len(LedgerEntryType) == 5


class TestDeviceSourceEnum:
    def test_members(self) -> None:
        assert DeviceSource.MANUAL.value == "MANUAL"
        assert DeviceSource.USB_SCANNER.value == "USB_SCANNER"


class TestRoleTypeEnum:
    def test_all_members_present(self) -> None:
        expected = {"ADMINISTRATOR", "LIBRARIAN", "TEACHER", "COUNSELOR", "REVIEWER"}
        assert {r.value for r in RoleType} == expected


class TestScopeTypeEnum:
    def test_all_members_present(self) -> None:
        expected = {"SCHOOL", "DEPARTMENT", "CLASS", "INDIVIDUAL"}
        assert {s.value for s in ScopeType} == expected


class TestCheckpointStatusEnum:
    def test_all_members_present(self) -> None:
        expected = {"ACTIVE", "COMPLETED", "FAILED", "ABANDONED"}
        assert {s.value for s in CheckpointStatus} == expected


class TestUpdateStatusEnum:
    def test_all_members_present(self) -> None:
        assert UpdateStatus.PENDING.value == "PENDING"
        assert UpdateStatus.APPLIED.value == "APPLIED"
        assert UpdateStatus.ROLLED_BACK.value == "ROLLED_BACK"


class TestReviewDecisionEnum:
    def test_all_members_present(self) -> None:
        expected = {"APPROVED", "REJECTED", "NEEDS_REVISION"}
        assert {d.value for d in ReviewDecision} == expected


class TestStockStatusEnum:
    def test_all_members_present(self) -> None:
        expected = {"AVAILABLE", "RESERVED", "QUARANTINE", "DISPOSED", "FROZEN"}
        assert {s.value for s in StockStatus} == expected


class TestWorkflowTransitions:
    def test_draft_to_in_review_valid(self) -> None:
        """DRAFT → IN_REVIEW is the first mandatory step."""
        assert (ResourceStatus.DRAFT, ResourceStatus.IN_REVIEW) in VALID_RESOURCE_TRANSITIONS

    def test_in_review_to_published_valid(self) -> None:
        assert (ResourceStatus.IN_REVIEW, ResourceStatus.PUBLISHED) in VALID_RESOURCE_TRANSITIONS

    def test_in_review_to_unpublished_valid(self) -> None:
        assert (ResourceStatus.IN_REVIEW, ResourceStatus.UNPUBLISHED) in VALID_RESOURCE_TRANSITIONS

    def test_published_to_unpublished_valid(self) -> None:
        assert (ResourceStatus.PUBLISHED, ResourceStatus.UNPUBLISHED) in VALID_RESOURCE_TRANSITIONS

    def test_draft_to_published_invalid(self) -> None:
        """Cannot skip the review step."""
        assert (ResourceStatus.DRAFT, ResourceStatus.PUBLISHED) not in VALID_RESOURCE_TRANSITIONS

    def test_published_to_draft_invalid(self) -> None:
        assert (ResourceStatus.PUBLISHED, ResourceStatus.DRAFT) not in VALID_RESOURCE_TRANSITIONS

    def test_validate_valid_transition_does_not_raise(self) -> None:
        validate_resource_transition(ResourceStatus.DRAFT, ResourceStatus.IN_REVIEW)

    def test_validate_invalid_transition_raises(self) -> None:
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            validate_resource_transition(ResourceStatus.DRAFT, ResourceStatus.PUBLISHED)
        assert exc_info.value.from_status == "DRAFT"
        assert exc_info.value.to_status == "PUBLISHED"

    def test_error_code_on_invalid_transition(self) -> None:
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            validate_resource_transition(ResourceStatus.PUBLISHED, ResourceStatus.DRAFT)
        assert exc_info.value.code == "INVALID_STATE_TRANSITION"
