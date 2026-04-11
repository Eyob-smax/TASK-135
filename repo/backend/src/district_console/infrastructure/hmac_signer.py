"""
HMAC-SHA256 request signing and verification for integration clients.

Signing protocol:
  Message = "{METHOD}\\n{path}\\n{timestamp}\\n{sha256_hex(body)}"
  Signature = HMAC-SHA256(key, message).hexdigest()

Headers sent with each signed request:
  X-DC-Signature: hmac-sha256 {hex_signature}
  X-DC-Timestamp: {unix_epoch_int}

Key storage:
  Keys are stored as hex strings in hmac_keys.key_encrypted. Actual at-rest
  encryption is deferred to Prompt 7 — the column name reflects intent.
  Key bytes are NEVER written to logs (logging_config.SENSITIVE_KEYS covers
  "key", "key_encrypted", and "hmac").

Replay protection:
  Requests older than HMAC_SIGN_MAX_AGE_SECONDS (300s / 5 min) are rejected.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime

from cryptography.fernet import Fernet

def _get_fernet(master_key_hex: str) -> Fernet:
    """
    Return a Fernet instance for encrypting/decrypting HMAC key material.

    master_key_hex must be a 64-character hex string (32 bytes).
    """
    if not master_key_hex:
        raise ValueError("DC_KEY_ENCRYPTION_KEY is required and must be 64 hex characters.")

    try:
        raw = bytes.fromhex(master_key_hex)
    except ValueError as exc:
        raise ValueError("DC_KEY_ENCRYPTION_KEY must be a valid hex string.") from exc

    if len(raw) != 32:
        raise ValueError("DC_KEY_ENCRYPTION_KEY must decode to exactly 32 bytes.")

    fernet_key = base64.urlsafe_b64encode(raw)
    return Fernet(fernet_key)


def encrypt_hmac_key(raw_key_hex: str, master_key_hex: str) -> str:
    """Encrypt a hex HMAC key using Fernet. Returns a base64-encoded ciphertext string."""
    return _get_fernet(master_key_hex).encrypt(raw_key_hex.encode()).decode()


def decrypt_hmac_key(ciphertext: str, master_key_hex: str) -> str:
    """Decrypt a Fernet-encrypted HMAC key ciphertext. Returns the original hex key string."""
    return _get_fernet(master_key_hex).decrypt(ciphertext.encode()).decode()


HMAC_SIGN_MAX_AGE_SECONDS: int = 300  # 5-minute replay window


class HmacSigner:
    """
    Signs and verifies HMAC-SHA256 request signatures.

    Thread-safe and stateless — a single instance can be shared across
    workers without synchronisation.
    """

    def sign(
        self,
        key: bytes,
        method: str,
        path: str,
        timestamp: str,
        body: bytes,
    ) -> str:
        """
        Produce a hex-encoded HMAC-SHA256 signature.

        Args:
            key:       Raw key bytes (32 bytes recommended).
            method:    HTTP verb in uppercase, e.g. "POST".
            path:      Request path including query string, e.g. "/api/v1/events".
            timestamp: Unix epoch integer as a string, e.g. "1712345678".
            body:      Raw request body bytes (b"" for empty bodies).

        Returns:
            Lowercase hex string of the HMAC digest.
        """
        message = self._build_message(method, path, timestamp, body)
        return hmac.new(key, message, hashlib.sha256).hexdigest()

    def verify(
        self,
        key: bytes,
        method: str,
        path: str,
        timestamp: str,
        body: bytes,
        signature: str,
        now: datetime,
        max_age_seconds: int = HMAC_SIGN_MAX_AGE_SECONDS,
    ) -> bool:
        """
        Verify a request signature and reject stale timestamps.

        Returns False (never raises) on any mismatch or replay condition,
        so callers can safely treat False as "reject the request".
        """
        # Replay protection: reject if timestamp is too old or too far in future
        try:
            ts_int = int(timestamp)
        except (ValueError, TypeError):
            return False

        now_ts = int(now.timestamp())
        if abs(now_ts - ts_int) > max_age_seconds:
            return False

        # Constant-time comparison to prevent timing attacks
        expected = self.sign(key, method, path, timestamp, body)
        return hmac.compare_digest(expected, signature.lower())

    @staticmethod
    def generate_key() -> bytes:
        """Generate a cryptographically secure 32-byte key."""
        return secrets.token_bytes(32)

    @staticmethod
    def key_to_hex(key: bytes) -> str:
        """Encode key bytes as a hex string for storage in hmac_keys.key_encrypted."""
        return key.hex()

    @staticmethod
    def key_from_hex(hex_str: str) -> bytes:
        """Decode a hex string back to key bytes."""
        return bytes.fromhex(hex_str)

    @staticmethod
    def _build_message(
        method: str, path: str, timestamp: str, body: bytes
    ) -> bytes:
        body_hash = hashlib.sha256(body).hexdigest()
        message_str = f"{method.upper()}\n{path}\n{timestamp}\n{body_hash}"
        return message_str.encode("utf-8")
