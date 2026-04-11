"""
Infrastructure layer.

Contains all framework-dependent implementations:
- SQLite repositories (SQLAlchemy 2.x ORM models and session management)
- Alembic migration helpers
- File fingerprinting and import utilities
- HMAC-SHA256 request signing and key rotation
- Outbox writer for LAN-shared folder webhook events
- Record-level lock manager (DB-backed, timeout/release)
- Checkpoint store for crash-safe job recovery
- APScheduler job wiring
- Structured logging configuration
- Offline update package handler
"""
