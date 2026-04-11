"""
Unit tests for HmacSigner: signing, verification, key generation.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from district_console.infrastructure.hmac_signer import HMAC_SIGN_MAX_AGE_SECONDS, HmacSigner


class TestHmacSigning:
    def test_sign_and_verify_roundtrip(self) -> None:
        signer = HmacSigner()
        key = HmacSigner.generate_key()
        ts = "1712345678"
        now = datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(tzinfo=None)
        sig = signer.sign(key, "POST", "/api/v1/events", ts, b'{"event":"test"}')
        assert signer.verify(key, "POST", "/api/v1/events", ts, b'{"event":"test"}', sig, now)

    def test_verify_wrong_key_returns_false(self) -> None:
        signer = HmacSigner()
        key1 = HmacSigner.generate_key()
        key2 = HmacSigner.generate_key()
        ts = "1712345678"
        now = datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(tzinfo=None)
        sig = signer.sign(key1, "POST", "/api/v1/events", ts, b"body")
        assert not signer.verify(key2, "POST", "/api/v1/events", ts, b"body", sig, now)

    def test_verify_tampered_body_returns_false(self) -> None:
        signer = HmacSigner()
        key = HmacSigner.generate_key()
        ts = "1712345678"
        now = datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(tzinfo=None)
        sig = signer.sign(key, "POST", "/api/v1/events", ts, b"original body")
        assert not signer.verify(key, "POST", "/api/v1/events", ts, b"tampered body", sig, now)

    def test_verify_old_timestamp_returns_false(self) -> None:
        """Timestamps older than HMAC_SIGN_MAX_AGE_SECONDS are rejected."""
        signer = HmacSigner()
        key = HmacSigner.generate_key()
        old_ts = "1000000000"  # Year 2001 — very old
        now = datetime.utcnow()
        sig = signer.sign(key, "GET", "/api/v1/resources", old_ts, b"")
        assert not signer.verify(key, "GET", "/api/v1/resources", old_ts, b"", sig, now)

    def test_verify_future_timestamp_outside_window_returns_false(self) -> None:
        """Timestamps far in the future are also rejected."""
        signer = HmacSigner()
        key = HmacSigner.generate_key()
        now = datetime.utcnow()
        far_future_ts = str(int(now.timestamp()) + HMAC_SIGN_MAX_AGE_SECONDS + 60)
        sig = signer.sign(key, "GET", "/", far_future_ts, b"")
        assert not signer.verify(key, "GET", "/", far_future_ts, b"", sig, now)

    def test_generate_key_is_32_bytes(self) -> None:
        key = HmacSigner.generate_key()
        assert isinstance(key, bytes)
        assert len(key) == 32

    def test_signature_is_hex_string(self) -> None:
        signer = HmacSigner()
        key = HmacSigner.generate_key()
        sig = signer.sign(key, "GET", "/", "1712345678", b"")
        assert isinstance(sig, str)
        # SHA-256 hex = 64 characters
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_different_methods_produce_different_signatures(self) -> None:
        signer = HmacSigner()
        key = HmacSigner.generate_key()
        ts = "1712345678"
        sig_get = signer.sign(key, "GET", "/api/v1/resources", ts, b"")
        sig_post = signer.sign(key, "POST", "/api/v1/resources", ts, b"")
        assert sig_get != sig_post

    def test_key_hex_roundtrip(self) -> None:
        key = HmacSigner.generate_key()
        hex_str = HmacSigner.key_to_hex(key)
        restored = HmacSigner.key_from_hex(hex_str)
        assert restored == key
