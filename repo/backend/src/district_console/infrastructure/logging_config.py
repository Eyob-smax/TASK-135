"""
Structured logging configuration with secret sanitization.

All log records pass through SanitizingFilter before emission. The filter
redacts any value whose key appears in SENSITIVE_KEYS, preventing passwords,
HMAC keys, session tokens, and other secrets from leaking into log files.

Usage:
    from district_console.infrastructure.logging_config import configure_logging
    configure_logging("INFO")
    logger = logging.getLogger("district_console.auth")
    logger.info("Login attempt", extra={"username": user.username})
    # username is preserved; any "password" key would be redacted
"""
from __future__ import annotations

import logging
import re
from typing import Any

REDACTED: str = "[REDACTED]"

#: Keys whose values are always redacted, case-insensitive.
SENSITIVE_KEYS: frozenset[str] = frozenset({
    "password",
    "password_hash",
    "key",
    "key_encrypted",
    "secret",
    "token",
    "hmac",
    "signature",
    "authorization",
    "hash",
    "credential",
    "api_key",
    "private_key",
})

# Pattern matches "key=value" or "key: value" in string messages
_KEY_VALUE_PATTERN = re.compile(
    r'(?i)\b(' + '|'.join(re.escape(k) for k in SENSITIVE_KEYS) + r')\s*[=:]\s*\S+'
)


def _is_sensitive_key(key: str) -> bool:
    return key.lower() in {k.lower() for k in SENSITIVE_KEYS}


def _sanitize_value(value: Any) -> Any:
    """Recursively redact sensitive values in dicts; leave other values alone."""
    if isinstance(value, dict):
        return {
            k: REDACTED if _is_sensitive_key(k) else _sanitize_value(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        sanitized = [_sanitize_value(item) for item in value]
        return type(value)(sanitized)
    return value


def _sanitize_message(msg: str) -> str:
    """Redact key=value patterns in string log messages."""
    return _KEY_VALUE_PATTERN.sub(
        lambda m: m.group(0).split(m.group(1))[0] + m.group(1) + "=[REDACTED]",
        msg,
    )


class SanitizingFilter(logging.Filter):
    """
    Logging filter that redacts sensitive fields from log records.

    Handles:
    - record.args when it is a dict (keyword-style logging)
    - record.args when it is a tuple (positional-style logging)
    - record.msg when it is a string (inline key=value patterns)
    - record.__dict__ 'extra' fields added via logging.info(..., extra={...})
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        # Sanitize positional / keyword args
        if isinstance(record.args, dict):
            record.args = _sanitize_value(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(_sanitize_value(a) for a in record.args)

        # Sanitize string message patterns (e.g. "password=abc123")
        if isinstance(record.msg, str):
            record.msg = _sanitize_message(record.msg)

        # Sanitize extra fields attached directly to the record
        for key in list(vars(record).keys()):
            if _is_sensitive_key(key):
                setattr(record, key, REDACTED)

        return True  # Always emit the record (filter only redacts, never drops)


def configure_logging(log_level: str = "INFO") -> None:
    """
    Configure the root logger with structured format and sanitization.

    Should be called once during application bootstrap. Subsequent calls
    are safe (idempotent — won't duplicate handlers if the root logger
    already has handlers).

    Args:
        log_level: Python logging level name, e.g. "INFO", "DEBUG", "WARNING".
    """
    root_logger = logging.getLogger()

    # Idempotency: don't add duplicate handlers
    if root_logger.handlers:
        # Still ensure our filter is present
        _ensure_filter(root_logger)
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    handler.addFilter(SanitizingFilter())

    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Suppress noisy third-party loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def _ensure_filter(logger: logging.Logger) -> None:
    """Add SanitizingFilter to all handlers if not already present."""
    for handler in logger.handlers:
        has_filter = any(isinstance(f, SanitizingFilter) for f in handler.filters)
        if not has_filter:
            handler.addFilter(SanitizingFilter())
