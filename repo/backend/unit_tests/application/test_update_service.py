"""
Unit tests for UpdateService — import, apply, and rollback of update packages.
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
from district_console.infrastructure.repositories import AuditRepository, UpdatePackageRepository


def _make_service(staging_path=None, install_path=None):
    kwargs = {}
    if staging_path is not None:
        kwargs["staging_path"] = str(staging_path)
    if install_path is not None:
        kwargs["install_path"] = str(install_path)
    return UpdateService(UpdatePackageRepository(), AuditWriter(AuditRepository()), **kwargs)


def _make_zip(
    version="1.0.0",
    extra_fields=None,
    *,
    path_override: str = "data/config.json",
    checksum_override: str | None = None,
) -> bytes:
    """Build a minimal valid update package ZIP."""
    config_payload = b'{"key": "value"}'
    checksum = checksum_override or hashlib.sha256(config_payload).hexdigest()
    manifest = {
        "version": version,
        "build_id": "build-001",
        "file_list": [path_override],
        "checksums": {path_override: checksum},
    }
    if extra_fields:
        manifest.update(extra_fields)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr(path_override, config_payload)
    return buf.getvalue()


NOW = datetime(2024, 6, 1, 10, 0, 0)
ACTOR = uuid.uuid4()


async def test_import_package_creates_pending_record(db_session: AsyncSession, seeded_user_orm):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    pkg = await svc.import_package(db_session, _make_zip(), "v1.0.0.zip", actor, NOW)
    assert pkg.version == "1.0.0"
    from district_console.domain.enums import UpdateStatus
    assert pkg.status == UpdateStatus.PENDING


async def test_import_package_invalid_zip_raises(db_session: AsyncSession, seeded_user_orm):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    with pytest.raises(ManifestValidationError) as exc_info:
        await svc.import_package(db_session, b"not a zip", "bad.zip", actor, NOW)
    assert "valid ZIP" in exc_info.value.reason


async def test_import_package_missing_manifest_raises(db_session: AsyncSession, seeded_user_orm):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "no manifest here")
    with pytest.raises(ManifestValidationError) as exc_info:
        await svc.import_package(db_session, buf.getvalue(), "no_manifest.zip", actor, NOW)
    assert "manifest.json" in exc_info.value.reason


async def test_apply_package_transitions_to_applied(db_session: AsyncSession, seeded_user_orm):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    pkg = await svc.import_package(db_session, _make_zip("2.0.0"), "v2.zip", actor, NOW)
    applied = await svc.apply_package(db_session, pkg.id, actor, NOW)
    from district_console.domain.enums import UpdateStatus
    assert applied.status == UpdateStatus.APPLIED


async def test_rollback_package_restores_prior(db_session: AsyncSession, seeded_user_orm):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    # Import and apply v1
    v1 = await svc.import_package(db_session, _make_zip("1.0.0"), "v1.zip", actor, NOW)
    await svc.apply_package(db_session, v1.id, actor, NOW)
    # Import v2 (links prior_version_ref → v1)
    v2 = await svc.import_package(db_session, _make_zip("2.0.0"), "v2.zip", actor, NOW)
    applied_v2 = await svc.apply_package(db_session, v2.id, actor, NOW)
    # Rollback v2 → v1
    restored = await svc.rollback_package(db_session, applied_v2.id, actor, NOW)
    assert restored.version == "1.0.0"
    from district_console.domain.enums import UpdateStatus
    assert restored.status == UpdateStatus.APPLIED


async def test_rollback_package_without_prior_raises(db_session: AsyncSession, seeded_user_orm):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    pkg = await svc.import_package(db_session, _make_zip("1.0.0"), "v1.zip", actor, NOW)
    applied = await svc.apply_package(db_session, pkg.id, actor, NOW)
    # v1 has no prior_version_ref → rollback should fail
    with pytest.raises(RollbackError):
        await svc.rollback_package(db_session, applied.id, actor, NOW)


async def test_apply_package_extracts_zip_contents(
    db_session: AsyncSession, seeded_user_orm, tmp_path
):
    """apply_package must extract all ZIP members to staging_path/applied/{version}/."""
    install_dir = tmp_path / "install"
    svc = _make_service(staging_path=tmp_path / "staging", install_path=install_dir)
    actor = uuid.UUID(seeded_user_orm.id)
    pkg = await svc.import_package(db_session, _make_zip("3.0.0"), "v3.zip", actor, NOW)
    await svc.apply_package(db_session, pkg.id, actor, NOW)

    apply_dir = tmp_path / "staging" / "applied" / "3.0.0"
    assert apply_dir.exists(), "Apply directory was not created"
    assert (apply_dir / "manifest.json").exists(), "manifest.json not extracted"
    assert (apply_dir / "data" / "config.json").exists(), "data/config.json not extracted"
    config_text = (apply_dir / "data" / "config.json").read_text()
    assert config_text == '{"key": "value"}'

    # Install-target swap: files must also be present in install_path
    assert install_dir.exists(), "Install target directory was not created"
    assert (install_dir / "data" / "config.json").exists(), "config.json missing from install target"


async def test_rollback_package_removes_applied_directory(
    db_session: AsyncSession, seeded_user_orm, tmp_path
):
    """rollback_package must remove the rolled-back version's staging dir and restore prior to install."""
    install_dir = tmp_path / "install"
    svc = _make_service(staging_path=tmp_path / "staging", install_path=install_dir)
    actor = uuid.UUID(seeded_user_orm.id)

    v1 = await svc.import_package(db_session, _make_zip("1.1.0"), "v1.1.zip", actor, NOW)
    await svc.apply_package(db_session, v1.id, actor, NOW)

    v2 = await svc.import_package(db_session, _make_zip("2.1.0"), "v2.1.zip", actor, NOW)
    applied_v2 = await svc.apply_package(db_session, v2.id, actor, NOW)

    # Both staging directories should exist before rollback
    assert (tmp_path / "staging" / "applied" / "1.1.0").exists()
    assert (tmp_path / "staging" / "applied" / "2.1.0").exists()

    await svc.rollback_package(db_session, applied_v2.id, actor, NOW)

    # v2.1.0 staging directory removed; v1.1.0 staging directory untouched
    assert not (tmp_path / "staging" / "applied" / "2.1.0").exists(), \
        "Rolled-back staging directory was not removed"
    assert (tmp_path / "staging" / "applied" / "1.1.0").exists(), \
        "Prior version staging directory should be kept"

    # Install target must have been restored to v1.1.0 content
    assert install_dir.exists(), "Install target directory should exist after rollback"
    assert (install_dir / "data" / "config.json").exists(), \
        "Prior version content missing from install target after rollback"


async def test_apply_package_checksum_mismatch_raises_validation_error(
    db_session: AsyncSession, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    pkg = await svc.import_package(
        db_session,
        _make_zip("4.0.0", checksum_override="0" * 64),
        "v4.zip",
        actor,
        NOW,
    )

    with pytest.raises(DomainValidationError) as exc_info:
        await svc.apply_package(db_session, pkg.id, actor, NOW)
    assert exc_info.value.field == "checksum"


async def test_apply_package_path_traversal_raises_validation_error(
    db_session: AsyncSession, seeded_user_orm
):
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    pkg = await svc.import_package(
        db_session,
        _make_zip("4.1.0", path_override="../escape.txt"),
        "v4_1.zip",
        actor,
        NOW,
    )

    with pytest.raises(DomainValidationError) as exc_info:
        await svc.apply_package(db_session, pkg.id, actor, NOW)
    assert exc_info.value.field == "file_path"


async def test_import_package_file_list_checksum_mismatch_raises(db_session: AsyncSession, seeded_user_orm):
    """Import must reject a manifest where file_list and checksums keys do not match exactly."""
    svc = _make_service()
    actor = uuid.UUID(seeded_user_orm.id)
    # Build a ZIP whose manifest has file_list=["a.txt"] but checksums={"b.txt": "..."}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        manifest = {
            "version": "5.0.0",
            "build_id": "build-mismatch",
            "file_list": ["a.txt"],
            "checksums": {"b.txt": "a" * 64},
        }
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("a.txt", b"content a")
        zf.writestr("b.txt", b"content b")
    from district_console.application.update_service import ManifestValidationError
    with pytest.raises(ManifestValidationError) as exc_info:
        await svc.import_package(db_session, buf.getvalue(), "mismatch.zip", actor, NOW)
    assert "match exactly" in exc_info.value.reason


async def test_apply_package_extra_unlisted_member_raises(db_session: AsyncSession, seeded_user_orm, tmp_path):
    """apply_package must reject a ZIP that contains files not declared in file_list."""
    svc = _make_service(staging_path=tmp_path / "staging", install_path=tmp_path / "install")
    actor = uuid.UUID(seeded_user_orm.id)
    # Build a valid manifest but sneak an extra file into the ZIP
    payload = b'{"legit": true}'
    checksum = hashlib.sha256(payload).hexdigest()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        manifest = {
            "version": "5.1.0",
            "build_id": "build-extra",
            "file_list": ["data/legit.json"],
            "checksums": {"data/legit.json": checksum},
        }
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("data/legit.json", payload)
        zf.writestr("extra/unlisted.py", b"malicious()")  # not in file_list
    pkg = await svc.import_package(db_session, buf.getvalue(), "extra.zip", actor, NOW)
    with pytest.raises(DomainValidationError) as exc_info:
        await svc.apply_package(db_session, pkg.id, actor, NOW)
    assert exc_info.value.field == "file_list"
