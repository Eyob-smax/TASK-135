"""
Tests for domain policy constants and predicate functions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from district_console.domain.policies import (
    COUNT_SESSION_INACTIVITY_HOURS,
    COUNT_VARIANCE_DOLLAR_THRESHOLD,
    COUNT_VARIANCE_PCT_THRESHOLD,
    HMAC_KEY_ROTATION_DAYS,
    LOCKOUT_DURATION_MINUTES,
    MAX_FAILED_ATTEMPTS,
    MAX_RESOURCE_REVISIONS,
    MIN_PASSWORD_LENGTH,
    RATE_LIMIT_RPM,
    age_range_valid,
    hmac_key_needs_rotation,
    is_count_session_expired,
    is_locked_out,
    password_length_valid,
    requires_supervisor_approval,
    revisions_over_limit,
    timeliness_valid,
)

NOW = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)


class TestPolicyConstants:
    def test_variance_dollar_threshold(self) -> None:
        assert COUNT_VARIANCE_DOLLAR_THRESHOLD == Decimal("250.00")

    def test_variance_pct_threshold(self) -> None:
        assert COUNT_VARIANCE_PCT_THRESHOLD == Decimal("0.02")

    def test_count_session_inactivity_hours(self) -> None:
        assert COUNT_SESSION_INACTIVITY_HOURS == 8

    def test_max_failed_attempts(self) -> None:
        assert MAX_FAILED_ATTEMPTS == 5

    def test_lockout_duration(self) -> None:
        assert LOCKOUT_DURATION_MINUTES == 15

    def test_min_password_length(self) -> None:
        assert MIN_PASSWORD_LENGTH == 12

    def test_max_resource_revisions(self) -> None:
        assert MAX_RESOURCE_REVISIONS == 10

    def test_hmac_rotation_days(self) -> None:
        assert HMAC_KEY_ROTATION_DAYS == 90

    def test_rate_limit_rpm(self) -> None:
        assert RATE_LIMIT_RPM == 60


class TestRequiresSupervisorApproval:
    def test_dollar_threshold_exceeded(self) -> None:
        """$250.01 exceeds $250.00 threshold."""
        assert requires_supervisor_approval(Decimal("250.01"), Decimal("0.00")) is True

    def test_dollar_threshold_exact_not_exceeded(self) -> None:
        """$250.00 exactly does NOT exceed the threshold (> not >=)."""
        assert requires_supervisor_approval(Decimal("250.00"), Decimal("0.00")) is False

    def test_pct_threshold_exceeded(self) -> None:
        """2.1% exceeds 2% threshold."""
        assert requires_supervisor_approval(Decimal("0.00"), Decimal("0.021")) is True

    def test_pct_threshold_exact_not_exceeded(self) -> None:
        """2.00% exactly does NOT exceed."""
        assert requires_supervisor_approval(Decimal("0.00"), Decimal("0.02")) is False

    def test_both_below_threshold(self) -> None:
        assert requires_supervisor_approval(Decimal("249.99"), Decimal("0.019")) is False

    def test_both_above_threshold(self) -> None:
        assert requires_supervisor_approval(Decimal("300.00"), Decimal("0.05")) is True

    def test_zero_variance(self) -> None:
        assert requires_supervisor_approval(Decimal("0.00"), Decimal("0.00")) is False


class TestIsCountSessionExpired:
    def test_expired_after_9_hours(self) -> None:
        last_activity = NOW - timedelta(hours=9)
        assert is_count_session_expired(last_activity, NOW) is True

    def test_not_expired_after_7_hours(self) -> None:
        last_activity = NOW - timedelta(hours=7)
        assert is_count_session_expired(last_activity, NOW) is False

    def test_expired_exactly_at_threshold(self) -> None:
        """Exactly 8 hours is expired (>= threshold)."""
        last_activity = NOW - timedelta(hours=8)
        assert is_count_session_expired(last_activity, NOW) is True

    def test_not_expired_just_under_threshold(self) -> None:
        last_activity = NOW - timedelta(hours=7, minutes=59, seconds=59)
        assert is_count_session_expired(last_activity, NOW) is False


class TestAgeRangeValid:
    def test_valid_full_range(self) -> None:
        assert age_range_valid(0, 18) is True

    def test_valid_narrow_range(self) -> None:
        assert age_range_valid(5, 10) is True

    def test_valid_same_value(self) -> None:
        assert age_range_valid(8, 8) is True

    def test_invalid_min_below_zero(self) -> None:
        assert age_range_valid(-1, 18) is False

    def test_invalid_max_above_18(self) -> None:
        assert age_range_valid(0, 19) is False

    def test_invalid_min_greater_than_max(self) -> None:
        assert age_range_valid(10, 5) is False

    def test_invalid_both_out_of_range(self) -> None:
        assert age_range_valid(-1, 25) is False

    def test_boundary_min_zero(self) -> None:
        assert age_range_valid(0, 0) is True

    def test_boundary_max_18(self) -> None:
        assert age_range_valid(18, 18) is True


class TestTimelinesValid:
    def test_evergreen_valid(self) -> None:
        assert timeliness_valid("EVERGREEN") is True

    def test_current_valid(self) -> None:
        assert timeliness_valid("CURRENT") is True

    def test_archived_valid(self) -> None:
        assert timeliness_valid("ARCHIVED") is True

    def test_lowercase_invalid(self) -> None:
        """Validation is case-sensitive."""
        assert timeliness_valid("evergreen") is False

    def test_mixed_case_invalid(self) -> None:
        assert timeliness_valid("Evergreen") is False

    def test_unknown_value_invalid(self) -> None:
        assert timeliness_valid("EXPIRED") is False

    def test_empty_string_invalid(self) -> None:
        assert timeliness_valid("") is False


class TestPasswordLengthValid:
    def test_too_short(self) -> None:
        assert password_length_valid("short") is False

    def test_exactly_11_chars_too_short(self) -> None:
        assert password_length_valid("a" * 11) is False

    def test_exactly_12_chars_valid(self) -> None:
        assert password_length_valid("a" * 12) is True

    def test_longer_password_valid(self) -> None:
        assert password_length_valid("longpassword1") is True

    def test_empty_password_invalid(self) -> None:
        assert password_length_valid("") is False


class TestIsLockedOut:
    def test_locked_out_with_future_locked_until(self) -> None:
        locked_until = NOW + timedelta(minutes=5)
        assert is_locked_out(5, locked_until, NOW) is True

    def test_not_locked_out_below_attempt_threshold(self) -> None:
        locked_until = NOW + timedelta(minutes=5)
        assert is_locked_out(3, locked_until, NOW) is False

    def test_not_locked_out_locked_until_is_none(self) -> None:
        assert is_locked_out(5, None, NOW) is False

    def test_not_locked_out_locked_until_in_past(self) -> None:
        locked_until = NOW - timedelta(minutes=1)
        assert is_locked_out(5, locked_until, NOW) is False

    def test_boundary_exactly_at_threshold(self) -> None:
        """Exactly at locked_until means no longer locked (now < locked_until is False)."""
        assert is_locked_out(5, NOW, NOW) is False


class TestRevisionsOverLimit:
    def test_10_revisions_not_over_limit(self) -> None:
        assert revisions_over_limit(10) is True

    def test_11_revisions_over_limit(self) -> None:
        assert revisions_over_limit(11) is True

    def test_zero_revisions_not_over_limit(self) -> None:
        assert revisions_over_limit(0) is False

    def test_one_revision_not_over_limit(self) -> None:
        assert revisions_over_limit(1) is False


class TestHmacKeyNeedsRotation:
    def test_key_at_90_days_needs_rotation(self) -> None:
        created_at = NOW - timedelta(days=90)
        assert hmac_key_needs_rotation(created_at, NOW) is True

    def test_key_at_89_days_does_not_need_rotation(self) -> None:
        created_at = NOW - timedelta(days=89)
        assert hmac_key_needs_rotation(created_at, NOW) is False

    def test_key_beyond_90_days_needs_rotation(self) -> None:
        created_at = NOW - timedelta(days=100)
        assert hmac_key_needs_rotation(created_at, NOW) is True
