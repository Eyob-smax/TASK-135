"""
Scaffold tests — verify the district_console package tree is importable.

These tests confirm that the package structure is correctly wired before any
application logic is implemented. They catch broken __init__.py files, missing
packages, or bad relative imports early in the build pipeline.
"""
import importlib


def _assert_importable(module_path: str) -> None:
    mod = importlib.import_module(module_path)
    assert mod is not None, f"Module {module_path!r} imported as None"


class TestPackageImportable:
    def test_root_package(self) -> None:
        """Root package imports and has a non-empty docstring."""
        import district_console
        assert district_console.__doc__, "district_console must have a module docstring"

    def test_ui_package(self) -> None:
        _assert_importable("district_console.ui")

    def test_application_package(self) -> None:
        _assert_importable("district_console.application")

    def test_domain_package(self) -> None:
        _assert_importable("district_console.domain")

    def test_domain_entities_package(self) -> None:
        _assert_importable("district_console.domain.entities")

    def test_infrastructure_package(self) -> None:
        _assert_importable("district_console.infrastructure")

    def test_api_package(self) -> None:
        _assert_importable("district_console.api")

    def test_bootstrap_package(self) -> None:
        _assert_importable("district_console.bootstrap")

    def test_packaging_package(self) -> None:
        _assert_importable("district_console.packaging")


class TestBootstrapConfig:
    def test_appconfig_defaults(self, monkeypatch) -> None:
        """AppConfig can be constructed from env and returns sane defaults."""
        monkeypatch.delenv("DC_API_PORT", raising=False)
        monkeypatch.delenv("DC_API_HOST", raising=False)
        monkeypatch.delenv("DC_LOG_LEVEL", raising=False)
        monkeypatch.delenv("DC_LAN_EVENTS_PATH", raising=False)
        from district_console.bootstrap.config import AppConfig
        cfg = AppConfig.from_env()
        assert cfg.api_port == 8765
        assert cfg.api_host == "127.0.0.1"
        assert cfg.log_level == "INFO"
        assert cfg.lan_events_path == ""

    def test_appconfig_api_url(self) -> None:
        from district_console.bootstrap.config import AppConfig
        cfg = AppConfig.from_env()
        assert cfg.api_url() == "http://127.0.0.1:8765"

    def test_appconfig_env_override(self, monkeypatch) -> None:
        """Environment variables correctly override defaults."""
        monkeypatch.setenv("DC_API_PORT", "9000")
        monkeypatch.setenv("DC_API_HOST", "localhost")
        monkeypatch.setenv("DC_LOG_LEVEL", "DEBUG")
        from district_console.bootstrap import config as cfg_module
        import importlib
        importlib.reload(cfg_module)
        cfg = cfg_module.AppConfig.from_env()
        assert cfg.api_port == 9000
        assert cfg.api_host == "localhost"
        assert cfg.log_level == "DEBUG"
