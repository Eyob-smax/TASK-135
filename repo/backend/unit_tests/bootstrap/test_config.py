"""
Unit tests for AppConfig environment-variable loading.

Verifies that each environment variable is read correctly, that defaults
are safe and expected, and that the OutboxWriter-facing lan_events_path
empty-string convention behaves as documented.
"""
from __future__ import annotations

import pytest

from district_console.bootstrap.config import AppConfig


class TestAppConfig:
    def test_defaults_without_env(self, monkeypatch):
        """All defaults are present and correct when no env vars are set."""
        for key in (
            "DC_DB_PATH",
            "DC_API_HOST",
            "DC_API_PORT",
            "DC_LOG_LEVEL",
            "DC_LAN_EVENTS_PATH",
        ):
            monkeypatch.delenv(key, raising=False)
        cfg = AppConfig()
        assert cfg.api_host == "127.0.0.1"
        assert cfg.api_port == 8765
        assert cfg.log_level == "INFO"
        assert cfg.lan_events_path == ""

    def test_db_path_default_contains_data_district(self, monkeypatch):
        """Default db_path points to data/district.db relative to cwd."""
        monkeypatch.delenv("DC_DB_PATH", raising=False)
        cfg = AppConfig()
        assert "data" in cfg.db_path
        assert cfg.db_path.endswith("district.db")

    def test_api_host_non_loopback_raises_value_error(self, monkeypatch):
        """DC_API_HOST set to a non-loopback address must raise ValueError at construction."""
        monkeypatch.setenv("DC_API_HOST", "0.0.0.0")
        with pytest.raises(ValueError, match="Non-loopback binding is not permitted"):
            AppConfig()

    def test_api_host_ipv6_loopback_accepted(self, monkeypatch):
        """DC_API_HOST set to the IPv6 loopback (::1) must be accepted."""
        monkeypatch.setenv("DC_API_HOST", "::1")
        cfg = AppConfig()
        assert cfg.api_host == "::1"

    def test_api_host_localhost_accepted(self, monkeypatch):
        """DC_API_HOST set to 'localhost' must be accepted."""
        monkeypatch.setenv("DC_API_HOST", "localhost")
        cfg = AppConfig()
        assert cfg.api_host == "localhost"

    def test_api_port_override(self, monkeypatch):
        """DC_API_PORT is parsed to int."""
        monkeypatch.setenv("DC_API_PORT", "9000")
        cfg = AppConfig()
        assert cfg.api_port == 9000

    def test_log_level_override(self, monkeypatch):
        """DC_LOG_LEVEL is passed through as-is."""
        monkeypatch.setenv("DC_LOG_LEVEL", "DEBUG")
        cfg = AppConfig()
        assert cfg.log_level == "DEBUG"

    def test_lan_events_path_override(self, monkeypatch):
        """DC_LAN_EVENTS_PATH stores the configured directory path."""
        monkeypatch.setenv("DC_LAN_EVENTS_PATH", "/mnt/share/events")
        cfg = AppConfig()
        assert cfg.lan_events_path == "/mnt/share/events"

    def test_lan_events_path_empty_string_is_falsy(self, monkeypatch):
        """
        Empty string must be falsy so OutboxWriter.is_enabled returns False.

        OutboxWriter checks: bool(self._path) — an empty string correctly
        disables outbound event writing without requiring None.
        """
        monkeypatch.setenv("DC_LAN_EVENTS_PATH", "")
        cfg = AppConfig()
        assert cfg.lan_events_path == ""
        assert not cfg.lan_events_path  # bool("") == False

    def test_api_url_combines_host_and_port(self, monkeypatch):
        """api_url() produces the correct base URL for the local REST service."""
        monkeypatch.setenv("DC_API_HOST", "127.0.0.1")
        monkeypatch.setenv("DC_API_PORT", "8765")
        cfg = AppConfig()
        assert cfg.api_url() == "http://127.0.0.1:8765"
