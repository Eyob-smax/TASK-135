"""
Additional tests for UpdateService covering manifest validation branches,
apply/rollback not-found paths, corrupt archive handling at apply time,
and the absolute-path traversal guard.
"""
from __future__ import annotations

import hashlib
import io
import json
import uuid
import zipfile
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.application.update_service import (
    ManifestValidationError,
    RollbackError,
    UpdateService,
)
from district_console.domain.exceptions import DomainValidationError
from district_console.infrastructure.audit_writer import AuditWriter
from district_console.infrastructure.repositories import (
    AuditRepository,
    UpdatePackageRepository,
)


def _make_service(staging_path=None, install_path=None) -> UpdateService:
    kwargs = {}
    if staging_path is not None:
        kwargs["staging_path"] = str(staging_path)
    if install_path is not None:
        kwargs["install_path"] = str(install_path)
    return UpdateService(
        UpdatePackageRepository(),
        AuditWriter(AuditRepository()),
        **kwargs,
    )


def _make_zip(manifest_override: dict | None = None, include_manifest: bool = True, extra_members: dict | None = None) -> bytes:
    config_payload = b'{"key": "value"}'
    checksum = hashlib.sha256(config_payload).hexdigest()
    manifest = {
        "version": "1.0.0",
        "build_id": "b-1",
        "file_list": ["data/config.json"],
        "checksums": {"data/config.json": checksum},
    }
    if manifest_override is not None:
        manifest = manifest_override
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if include_manifest:
            zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("data/config.json", config_payload)
        for name, data in (extra_members or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


NOW = datetime(2024, 6, 1, 10, 0, 0)


# ---------------------------------------------------------------------------
# Manifest validation branches
# ---------------------------------------------------------------------------

async def test_import_package_duplicate_version_raises(
    db_session: AsyncSession, seeded_user_orm, tmp_path
):
    svc = _make_service(staging_path=tmp_path / "staging")
    actor = uuid.UUID(seeded_user_orm.id)

    await svc.import_package(db_session, _make_zip(), "v1.zip", actor, NOW)
    with pytest.raises(DomainValidationError) as exc:
        await svc.import_package(db_session, _make_zip(), "v1-again.zip", actor, NOW)
    assert exc.value.field == "version"


async def test_import_package_manifest_not_valid_json_raises(
    db_session: AsyncSession, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", "not-valid-json{")
    with pytest.raises(ManifestValidationError) as exc:
        await svc.import_package(db_session, buf.getvalue(), "bad.zip", actor, NOW)
    assert "valid JSON" in exc.value.reason


async def test_import_package_missing_required_field_raises(
    db_session: AsyncSession, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    manifest = {
        "build_id": "b-1",
        "file_list": ["a.txt"],
        "checksums": {"a.txt": "a" * 64},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("a.txt", b"a")
    with pytest.raises(ManifestValidationError) as exc:
        await svc.import_package(db_session, buf.getvalue(), "bad.zip", actor, NOW)
    assert "required fields missing" in exc.value.reason


async def test_import_package_blank_version_raises(
    db_session: AsyncSession, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    manifest = {
        "version": "   ",
        "build_id": "b-1",
        "file_list": ["a.txt"],
        "checksums": {"a.txt": "a" * 64},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("a.txt", b"a")
    with pytest.raises(ManifestValidationError) as exc:
        await svc.import_package(db_session, buf.getvalue(), "bad.zip", actor, NOW)
    assert "non-empty" in exc.value.reason


async def test_import_package_file_list_not_a_list_raises(
    db_session: AsyncSession, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    manifest = {
        "version": "1.0.0",
        "build_id": "b-1",
        "file_list": "not-a-list",
        "checksums": {},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
    with pytest.raises(ManifestValidationError) as exc:
        await svc.import_package(db_session, buf.getvalue(), "bad.zip", actor, NOW)
    assert "file_list" in exc.value.reason


async def test_import_package_checksums_not_a_dict_raises(
    db_session: AsyncSession, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    manifest = {
        "version": "1.0.0",
        "build_id": "b-1",
        "file_list": [],
        "checksums": ["not-a-dict"],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
    with pytest.raises(ManifestValidationError) as exc:
        await svc.import_package(db_session, buf.getvalue(), "bad.zip", actor, NOW)
    assert "checksums" in exc.value.reason


# ---------------------------------------------------------------------------
# Apply / rollback not-found paths
# ---------------------------------------------------------------------------

async def test_apply_package_not_found_raises(
    db_session: AsyncSession, seeded_user_orm, tmp_path
):
    svc = _make_service(staging_path=tmp_path / "staging", install_path=tmp_path / "install")
    actor = uuid.UUID(seeded_user_orm.id)
    with pytest.raises(DomainValidationError) as exc:
        await svc.apply_package(db_session, uuid.uuid4(), actor, NOW)
    assert exc.value.field == "package_id"


async def test_apply_package_not_pending_raises(
    db_session: AsyncSession, seeded_user_orm, tmp_path
):
    svc = _make_service(staging_path=tmp_path / "staging", install_path=tmp_path / "install")
    actor = uuid.UUID(seeded_user_orm.id)

    pkg = await svc.import_package(db_session, _make_zip(), "v1.zip", actor, NOW)
    await svc.apply_package(db_session, pkg.id, actor, NOW)

    with pytest.raises(DomainValidationError) as exc:
        await svc.apply_package(db_session, pkg.id, actor, NOW)
    assert exc.value.field == "status"


async def test_rollback_package_not_found_raises(
    db_session: AsyncSession, seeded_user_orm, tmp_path
):
    svc = _make_service(staging_path=tmp_path / "staging", install_path=tmp_path / "install")
    actor = uuid.UUID(seeded_user_orm.id)
    with pytest.raises(DomainValidationError) as exc:
        await svc.rollback_package(db_session, uuid.uuid4(), actor, NOW)
    assert exc.value.field == "package_id"


# ---------------------------------------------------------------------------
# Apply-time archive integrity: absolute path / corrupt zip
# ---------------------------------------------------------------------------

async def test_apply_package_absolute_path_raises(
    db_session: AsyncSession, seeded_user_orm, tmp_path
):
    """A ZIP member with an absolute path must be rejected during apply."""
    svc = _make_service(staging_path=tmp_path / "staging", install_path=tmp_path / "install")
    actor = uuid.UUID(seeded_user_orm.id)
    payload = b"x"
    checksum = hashlib.sha256(payload).hexdigest()
    manifest = {
        "version": "9.0.0",
        "build_id": "b-9",
        "file_list": ["/etc/evil.txt"],
        "checksums": {"/etc/evil.txt": checksum},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("/etc/evil.txt", payload)
    pkg = await svc.import_package(db_session, buf.getvalue(), "abs.zip", actor, NOW)

    with pytest.raises(DomainValidationError) as exc:
        await svc.apply_package(db_session, pkg.id, actor, NOW)
    assert exc.value.field == "file_path"


async def test_apply_package_corrupt_zip_raises(
    db_session: AsyncSession, seeded_user_orm, tmp_path, monkeypatch
):
    """If the staged ZIP becomes corrupt between import and apply, apply must raise DomainValidationError."""
    svc = _make_service(staging_path=tmp_path / "staging", install_path=tmp_path / "install")
    actor = uuid.UUID(seeded_user_orm.id)

    pkg = await svc.import_package(db_session, _make_zip(), "v1.zip", actor, NOW)
    # Overwrite the staged ZIP with garbage so zipfile raises BadZipFile
    staged = tmp_path / "staging" / f"{pkg.file_hash}.zip"
    staged.write_bytes(b"not a zip at all")

    with pytest.raises(DomainValidationError) as exc:
        await svc.apply_package(db_session, pkg.id, actor, NOW)
    assert exc.value.field == "file_hash"


# ---------------------------------------------------------------------------
# Query helper
# ---------------------------------------------------------------------------

async def test_get_package_and_list_packages(
    db_session: AsyncSession, seeded_user_orm, tmp_path
):
    svc = _make_service(staging_path=tmp_path / "staging")
    actor = uuid.UUID(seeded_user_orm.id)
    pkg = await svc.import_package(db_session, _make_zip(), "v1.zip", actor, NOW)

    fetched = await svc.get_package(db_session, pkg.id)
    assert fetched is not None
    assert fetched.id == pkg.id

    packages, total = await svc.list_packages(db_session)
    assert total >= 1
    assert any(p.id == pkg.id for p in packages)
