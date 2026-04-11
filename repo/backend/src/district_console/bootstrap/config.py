"""
Application configuration loaded from environment variables.

All settings have safe defaults suitable for development. Production
deployments must override DC_DB_PATH and DC_LAN_EVENTS_PATH at minimum.
No secrets are stored in this module; API keys and HMAC keys are stored
in the database and never in environment variables or config files.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

_ALLOWED_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


@dataclass
class AppConfig:
    """
    Immutable application configuration resolved from environment variables.

    Environment variables (all prefixed DC_):
        DC_DB_PATH          Absolute path to the SQLite database file.
                            Default: <cwd>/data/district.db
        DC_API_HOST         Interface the local REST service binds to.
                            Default: 127.0.0.1 (loopback only)
        DC_API_PORT         TCP port for the embedded FastAPI service.
                            Default: 8765
        DC_LOG_LEVEL        Python logging level name.
                            Default: INFO
        DC_LAN_EVENTS_PATH  Path to LAN-shared folder for outbound webhook
                            event files. Empty string disables outbound events.
                            Default: "" (disabled)
    """

    db_path: str = field(default_factory=lambda: os.environ.get(
        "DC_DB_PATH", os.path.join(os.getcwd(), "data", "district.db")
    ))
    api_host: str = field(default_factory=lambda: os.environ.get(
        "DC_API_HOST", "127.0.0.1"
    ))
    api_port: int = field(default_factory=lambda: int(
        os.environ.get("DC_API_PORT", "8765")
    ))
    log_level: str = field(default_factory=lambda: os.environ.get(
        "DC_LOG_LEVEL", "INFO"
    ))
    lan_events_path: str = field(default_factory=lambda: os.environ.get(
        "DC_LAN_EVENTS_PATH", ""
    ))
    key_encryption_key: str = field(default_factory=lambda: os.environ.get(
        "DC_KEY_ENCRYPTION_KEY", ""
    ))

    def __post_init__(self) -> None:
        if self.api_host not in _ALLOWED_LOOPBACK_HOSTS:
            raise ValueError(
                f"DC_API_HOST must be a loopback address "
                f"({', '.join(sorted(_ALLOWED_LOOPBACK_HOSTS))}); "
                f"got '{self.api_host}'. Non-loopback binding is not permitted."
            )

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Construct config from the current process environment."""
        return cls()

    def api_url(self) -> str:
        """Base URL for the embedded local REST service."""
        return f"http://{self.api_host}:{self.api_port}"
