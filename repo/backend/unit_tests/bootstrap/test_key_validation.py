"""
Unit tests for bootstrap._validate_key_encryption_key.

The master key is expected to be 64 hex characters (32 bytes). These
tests verify each rejection branch plus the success path.
"""
from __future__ import annotations

import pytest

import district_console.bootstrap as bootstrap_mod


def test_validate_key_encryption_key_accepts_32_byte_hex():
    """A valid 64-char hex string (32 bytes) must pass validation."""
    valid = "0123456789abcdef" * 4  # 64 hex chars = 32 bytes
    assert bootstrap_mod._validate_key_encryption_key(valid) is None


def test_validate_key_encryption_key_rejects_empty():
    with pytest.raises(ValueError, match="required"):
        bootstrap_mod._validate_key_encryption_key("")


def test_validate_key_encryption_key_rejects_non_hex():
    """Non-hex characters must be rejected with a 'valid hex' message."""
    bad = "z" * 64
    with pytest.raises(ValueError, match="hex"):
        bootstrap_mod._validate_key_encryption_key(bad)


def test_validate_key_encryption_key_rejects_wrong_length():
    """A valid hex string of the wrong length must be rejected."""
    short = "ab" * 16  # only 16 bytes
    with pytest.raises(ValueError, match="32 bytes"):
        bootstrap_mod._validate_key_encryption_key(short)
