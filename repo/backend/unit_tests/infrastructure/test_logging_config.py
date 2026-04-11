"""
Unit tests for logging_config: secret sanitization filter.
"""
from __future__ import annotations

import logging

import pytest

from district_console.infrastructure.logging_config import (
    REDACTED,
    SENSITIVE_KEYS,
    SanitizingFilter,
    configure_logging,
)


def make_record(msg: str = "test", **extra) -> logging.LogRecord:
    """Create a LogRecord with optional extra attributes."""
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestSanitizingFilter:
    def test_password_dict_arg_is_redacted(self) -> None:
        f = SanitizingFilter()
        record = make_record("Login attempt")
        record.args = {"username": "alice", "password": "super_secret"}
        f.filter(record)
        assert record.args["password"] == REDACTED
        assert record.args["username"] == "alice"

    def test_token_dict_arg_is_redacted(self) -> None:
        f = SanitizingFilter()
        record = make_record("Request received")
        record.args = {"token": "abc123bearer", "path": "/api/v1/resources"}
        f.filter(record)
        assert record.args["token"] == REDACTED
        assert record.args["path"] == "/api/v1/resources"

    def test_key_encrypted_dict_arg_is_redacted(self) -> None:
        f = SanitizingFilter()
        record = make_record("Key loaded")
        record.args = {"client_id": "client1", "key_encrypted": "deadbeef" * 4}
        f.filter(record)
        assert record.args["key_encrypted"] == REDACTED
        assert record.args["client_id"] == "client1"

    def test_non_sensitive_fields_are_preserved(self) -> None:
        f = SanitizingFilter()
        record = make_record("User action")
        record.args = {"username": "bob", "action": "view_resource", "resource_id": "abc"}
        f.filter(record)
        assert record.args["username"] == "bob"
        assert record.args["action"] == "view_resource"
        assert record.args["resource_id"] == "abc"

    def test_string_message_password_pattern_redacted(self) -> None:
        f = SanitizingFilter()
        record = make_record("password=supersecret123 user=alice")
        f.filter(record)
        assert "supersecret123" not in record.msg
        assert "alice" in record.msg

    def test_extra_sensitive_attribute_on_record_redacted(self) -> None:
        f = SanitizingFilter()
        record = make_record("Signing")
        record.signature = "abc123"  # type: ignore[attr-defined]
        f.filter(record)
        assert getattr(record, "signature") == REDACTED

    def test_filter_always_returns_true(self) -> None:
        """Filter must not drop records — only redact values."""
        f = SanitizingFilter()
        record = make_record("some message")
        assert f.filter(record) is True

    def test_nested_dict_values_are_redacted(self) -> None:
        f = SanitizingFilter()
        record = make_record("Nested")
        record.args = {"data": {"password": "nested_secret", "name": "test"}}
        f.filter(record)
        assert record.args["data"]["password"] == REDACTED
        assert record.args["data"]["name"] == "test"


class TestConfigureLogging:
    def test_configure_logging_does_not_raise(self) -> None:
        """configure_logging should be callable without errors."""
        configure_logging("WARNING")

    def test_configure_logging_idempotent(self) -> None:
        """Calling configure_logging multiple times should not duplicate handlers."""
        root = logging.getLogger()
        initial_handler_count = len(root.handlers)
        configure_logging("INFO")
        configure_logging("INFO")
        # May have added 1 handler on first call, but not duplicated on second
        assert len(root.handlers) <= initial_handler_count + 1
