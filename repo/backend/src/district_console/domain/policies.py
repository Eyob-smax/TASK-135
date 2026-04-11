"""
Domain policies — business rule constants and pure predicate functions.

All symbols in this module are either named constants or pure functions with
no I/O and no framework dependencies. They can be imported and tested in
complete isolation from the database, UI, or API layers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal


# ---------------------------------------------------------------------------
# Policy constants
# ---------------------------------------------------------------------------

#: Maximum number of revisions retained per resource (oldest pruned on overflow)
MAX_RESOURCE_REVISIONS: int = 10

#: Minimum acceptable password length (characters)
MIN_PASSWORD_LENGTH: int = 12

#: Number of consecutive failed login attempts that trigger a lockout
MAX_FAILED_ATTEMPTS: int = 5

#: Duration of account lockout after MAX_FAILED_ATTEMPTS
LOCKOUT_DURATION_MINUTES: int = 15

#: Dollar-value threshold above which count variance requires supervisor approval
COUNT_VARIANCE_DOLLAR_THRESHOLD: Decimal = Decimal("250.00")

#: Percentage threshold above which count variance requires supervisor approval
#: Expressed as a decimal fraction (0.02 == 2%)
COUNT_VARIANCE_PCT_THRESHOLD: Decimal = Decimal("0.02")

#: Hours of inactivity after which a count session is automatically expired
COUNT_SESSION_INACTIVITY_HOURS: int = 8

#: Number of days before an HMAC key must be rotated
HMAC_KEY_ROTATION_DAYS: int = 90

#: Maximum REST requests per minute per integration client
RATE_LIMIT_RPM: int = 60

#: Application startup performance target (seconds)
STARTUP_TARGET_SECONDS: int = 5

#: Maximum allowed memory growth over 30-day run (megabytes)
MEMORY_STEADY_STATE_MB: int = 200

#: Minimum age value for resource metadata age range
AGE_RANGE_MIN_VALUE: int = 0

#: Maximum age value for resource metadata age range
AGE_RANGE_MAX_VALUE: int = 18


# ---------------------------------------------------------------------------
# Pure predicate functions
# ---------------------------------------------------------------------------

def requires_supervisor_approval(
    variance_dollar: Decimal,
    variance_pct: Decimal,
) -> bool:
    """
    Return True if a count session line's variance triggers the supervisor
    approval workflow.

    Approval is required when the absolute dollar variance exceeds
    COUNT_VARIANCE_DOLLAR_THRESHOLD OR the absolute percentage variance
    exceeds COUNT_VARIANCE_PCT_THRESHOLD.

    Args:
        variance_dollar: Absolute dollar value of the variance (non-negative).
        variance_pct:    Absolute percentage of the variance as a decimal
                         fraction (e.g. 0.03 == 3%).
    """
    return (
        variance_dollar > COUNT_VARIANCE_DOLLAR_THRESHOLD
        or variance_pct > COUNT_VARIANCE_PCT_THRESHOLD
    )


def is_count_session_expired(last_activity_at: datetime, now: datetime) -> bool:
    """
    Return True if the count session has been inactive longer than
    COUNT_SESSION_INACTIVITY_HOURS.

    Both datetimes should be UTC-aware or both naive; do not mix.
    """
    threshold = timedelta(hours=COUNT_SESSION_INACTIVITY_HOURS)
    return (now - last_activity_at) >= threshold


def age_range_valid(min_age: int, max_age: int) -> bool:
    """
    Return True if the age range is within the valid bounds (0–18 inclusive)
    and min_age does not exceed max_age.
    """
    return (
        AGE_RANGE_MIN_VALUE <= min_age
        and max_age <= AGE_RANGE_MAX_VALUE
        and min_age <= max_age
    )


def timeliness_valid(value: str) -> bool:
    """
    Return True if value is a valid TimelinesType member (case-sensitive).
    """
    from district_console.domain.enums import TimelinesType
    return value in {t.value for t in TimelinesType}


def password_length_valid(password: str) -> bool:
    """Return True if the password meets the minimum length requirement."""
    return len(password) >= MIN_PASSWORD_LENGTH


def is_locked_out(
    failed_attempts: int,
    locked_until: datetime | None,
    now: datetime,
) -> bool:
    """
    Return True if the user account is currently locked out.

    A lockout is active when:
    - failed_attempts >= MAX_FAILED_ATTEMPTS, AND
    - locked_until is set and has not yet passed.
    """
    if failed_attempts < MAX_FAILED_ATTEMPTS:
        return False
    if locked_until is None:
        return False
    return now < locked_until


def revisions_over_limit(count: int) -> bool:
    """Return True if the revision count exceeds the maximum allowed."""
    return count >= MAX_RESOURCE_REVISIONS


def hmac_key_needs_rotation(created_at: datetime, now: datetime) -> bool:
    """Return True if the HMAC key has reached or exceeded its rotation age."""
    threshold = timedelta(days=HMAC_KEY_ROTATION_DAYS)
    return (now - created_at) >= threshold
