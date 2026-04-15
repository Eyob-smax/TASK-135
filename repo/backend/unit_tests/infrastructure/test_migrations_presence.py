"""Static migration presence/import checks for Alembic versions."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _versions_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "database" / "migrations" / "versions"


def test_migration_files_exist_with_expected_baselines() -> None:
    versions_dir = _versions_dir()
    files = sorted(p.name for p in versions_dir.glob("*.py") if p.name != "__init__.py")

    assert files, "No migration files found under database/migrations/versions"
    assert "0001_initial_schema.py" in files
    assert "0002_resource_scope_columns.py" in files


def test_migration_modules_are_importable() -> None:
    versions_dir = _versions_dir()
    modules = [p for p in versions_dir.glob("*.py") if p.name != "__init__.py"]

    for module_path in modules:
        spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Basic Alembic script shape check.
        assert hasattr(module, "revision")
        assert hasattr(module, "down_revision")
        assert hasattr(module, "upgrade")
        assert hasattr(module, "downgrade")
