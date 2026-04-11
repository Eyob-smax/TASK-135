"""
Offline update package import and rollback service.

Update packages are ZIP archives containing a manifest.json. The service
validates the manifest, tracks version history, and supports one-step
rollback to the prior applied version.

Manifest schema (required fields):
    version:    semantic version string (e.g. "1.2.3")
    build_id:   build identifier string
    file_list:  list of file path strings
    checksums:  dict mapping file path -> SHA-256 hex string
"""
from __future__ import annotations

import hashlib
import io
import json
import pathlib
import shutil
import uuid
import zipfile
from datetime import datetime
from typing import Optional

from district_console.domain.entities.update import UpdatePackage
from district_console.domain.enums import UpdateStatus
from district_console.domain.exceptions import DomainValidationError

_REQUIRED_MANIFEST_FIELDS = {"version", "build_id", "file_list", "checksums"}


class ManifestValidationError(Exception):
    """Raised when a package manifest fails structural or integrity checks."""
    def __init__(self, reason: str) -> None:
        super().__init__(f"Invalid manifest: {reason}")
        self.reason = reason


class RollbackError(Exception):
    """Raised when rollback pre-conditions are not met."""


class UpdateService:
    """
    Application service for offline update package lifecycle.

    Import flow:
        import_package() → PENDING  (ZIP saved to staging_path)
        apply_package()  → APPLIED  (ZIP extracted to staging_path/applied/{version}/,
                                     then swapped into install_path/)

    Rollback flow:
        rollback_package(applied_id) → current APPLIED → ROLLED_BACK
                                     → prior_version_ref → re-APPLIED
                                     → prior staging dir re-copied to install_path/
    """

    def __init__(
        self,
        update_repo,
        audit_writer,
        staging_path: str = "data/updates",
        install_path: str = "data/install",
    ) -> None:
        self._repo = update_repo
        self._audit_writer = audit_writer
        self._staging_path = pathlib.Path(staging_path)
        self._install_path = pathlib.Path(install_path)

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    async def import_package(
        self,
        session,
        file_content: bytes,
        file_name: str,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> UpdatePackage:
        """
        Validate and record an offline update package.

        Raises:
            ManifestValidationError: ZIP is invalid or manifest is missing/malformed.
            DomainValidationError: Version already imported.
        """
        # Compute file hash
        file_hash = hashlib.sha256(file_content).hexdigest()

        # Extract and validate manifest
        manifest = self._extract_manifest(file_content)
        self._validate_manifest(manifest)

        version = manifest["version"]
        # Prevent duplicate imports of the same version
        existing = await self._repo.get_by_version(session, version)
        if existing is not None:
            raise DomainValidationError("version", version, "already imported")

        # Persist ZIP to staging directory for later extraction
        self._staging_path.mkdir(parents=True, exist_ok=True)
        zip_dest = self._staging_path / f"{file_hash}.zip"
        zip_dest.write_bytes(file_content)

        # Link to current APPLIED package for rollback chain
        current_applied = await self._repo.get_applied(session)

        package = UpdatePackage(
            id=uuid.uuid4(),
            version=version,
            manifest_json=json.dumps(manifest),
            file_path=file_name,
            file_hash=file_hash,
            imported_at=now,
            imported_by=actor_id,
            status=UpdateStatus.PENDING,
            prior_version_ref=current_applied.id if current_applied else None,
        )
        package = await self._repo.save(session, package)
        await self._audit_writer.write(
            session,
            entity_type="update_package",
            entity_id=package.id,
            action="UPDATE_IMPORTED",
            actor_id=actor_id,
            metadata={"version": version, "file_hash": file_hash},
        )
        return package

    def _extract_manifest(self, file_content: bytes) -> dict:
        try:
            with zipfile.ZipFile(io.BytesIO(file_content)) as zf:
                names = zf.namelist()
                if "manifest.json" not in names:
                    raise ManifestValidationError("manifest.json not found in archive")
                raw = zf.read("manifest.json")
                return json.loads(raw)
        except zipfile.BadZipFile as exc:
            raise ManifestValidationError(f"not a valid ZIP archive: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ManifestValidationError(f"manifest.json is not valid JSON: {exc}") from exc

    def _validate_manifest(self, manifest: dict) -> None:
        missing = _REQUIRED_MANIFEST_FIELDS - set(manifest.keys())
        if missing:
            raise ManifestValidationError(f"required fields missing: {sorted(missing)}")
        version = manifest.get("version", "")
        if not isinstance(version, str) or not version.strip():
            raise ManifestValidationError("version must be a non-empty string")
        if not isinstance(manifest.get("file_list"), list):
            raise ManifestValidationError("file_list must be a list")
        if not isinstance(manifest.get("checksums"), dict):
            raise ManifestValidationError("checksums must be a dict")
        file_list_set = set(manifest["file_list"])
        checksum_keys = set(manifest["checksums"].keys())
        if file_list_set != checksum_keys:
            missing_checksums = file_list_set - checksum_keys
            extra_checksums = checksum_keys - file_list_set
            raise ManifestValidationError(
                f"file_list and checksums must match exactly; "
                f"missing checksums: {sorted(missing_checksums)}; "
                f"extra checksums: {sorted(extra_checksums)}"
            )

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    async def apply_package(
        self,
        session,
        package_id: uuid.UUID,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> UpdatePackage:
        """
        Mark a PENDING package as APPLIED, extract its contents, and swap
        the active install target.

        Steps:
          1. Extract the package ZIP to ``staging_path/applied/{version}/``.
          2. Copy extracted files to ``install_path/``, replacing the current
             active installation (atomic overwrite via temp-dir swap).

        Raises DomainValidationError if the stored ZIP is corrupt.
        """
        package = await self._repo.get_by_id(session, package_id)
        if package is None:
            raise DomainValidationError("package_id", str(package_id), "not found")
        if package.status != UpdateStatus.PENDING:
            raise DomainValidationError(
                "status", package.status.value, "only PENDING packages can be applied"
            )
        applied = UpdatePackage(
            id=package.id,
            version=package.version,
            manifest_json=package.manifest_json,
            file_path=package.file_path,
            file_hash=package.file_hash,
            imported_at=package.imported_at,
            imported_by=package.imported_by,
            status=UpdateStatus.APPLIED,
            prior_version_ref=package.prior_version_ref,
        )
        applied = await self._repo.save(session, applied)

        # Step 1: Extract package files to versioned staging directory
        apply_dir = self._staging_path / "applied" / applied.version
        apply_dir.mkdir(parents=True, exist_ok=True)
        zip_src = self._staging_path / f"{applied.file_hash}.zip"
        if zip_src.exists():
            try:
                with zipfile.ZipFile(zip_src) as zf:
                    manifest_data = json.loads(zf.read("manifest.json"))
                    checksums = manifest_data.get("checksums", {})

                    declared_files = set(manifest_data.get("file_list", []))
                    archive_files = {m.filename for m in zf.infolist() if m.filename != "manifest.json"}
                    extra_files = archive_files - declared_files
                    if extra_files:
                        raise DomainValidationError(
                            "file_list",
                            str(sorted(extra_files)),
                            "archive contains files not declared in manifest file_list",
                        )

                    for member in zf.infolist():
                        # PATH TRAVERSAL GUARD
                        member_path = pathlib.Path(member.filename)
                        if member_path.is_absolute():
                            raise DomainValidationError(
                                "file_path", member.filename,
                                "absolute paths not allowed in update package"
                            )
                        resolved = (apply_dir / member_path).resolve()
                        if not str(resolved).startswith(str(apply_dir.resolve())):
                            raise DomainValidationError(
                                "file_path", member.filename,
                                "path traversal detected in update package"
                            )
                        zf.extract(member, apply_dir)

                    # CHECKSUM VERIFICATION against manifest
                    for file_path, expected_hash in checksums.items():
                        extracted = apply_dir / file_path
                        if not extracted.exists():
                            raise DomainValidationError(
                                "file_path", file_path,
                                "file listed in checksums but not found after extraction"
                            )
                        actual_hash = hashlib.sha256(extracted.read_bytes()).hexdigest()
                        if actual_hash != expected_hash:
                            raise DomainValidationError(
                                "checksum", file_path,
                                f"SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
                            )
            except zipfile.BadZipFile as exc:
                raise DomainValidationError(
                    "file_hash", applied.file_hash, f"stored ZIP is corrupt: {exc}"
                ) from exc

            # Step 2: Swap active install target — copy staging → install_path via temp dir
            # Using a temp-side rename to keep the swap as close to atomic as possible.
            tmp_install = self._install_path.parent / (self._install_path.name + ".tmp")
            shutil.copytree(apply_dir, tmp_install, dirs_exist_ok=True)
            if self._install_path.exists():
                shutil.rmtree(self._install_path)
            tmp_install.rename(self._install_path)

        await self._audit_writer.write(
            session,
            entity_type="update_package",
            entity_id=package_id,
            action="UPDATE_APPLIED",
            actor_id=actor_id,
            metadata={"version": package.version},
        )
        return applied

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    async def rollback_package(
        self,
        session,
        package_id: uuid.UUID,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> UpdatePackage:
        """
        Roll back the APPLIED package to its prior version.

        Steps:
          1. Set current package → ROLLED_BACK; set prior_version_ref → APPLIED.
          2. Restore the prior version from its staging directory to ``install_path/``.
          3. Remove the rolled-back version's extracted staging directory.
        """
        package = await self._repo.get_by_id(session, package_id)
        if package is None:
            raise DomainValidationError("package_id", str(package_id), "not found")
        if not package.can_rollback():
            raise RollbackError(
                f"Package {package_id} (status={package.status.value}) cannot be rolled back. "
                "Must be APPLIED and have a prior version."
            )

        # Mark current as ROLLED_BACK
        rolled_back = UpdatePackage(
            id=package.id,
            version=package.version,
            manifest_json=package.manifest_json,
            file_path=package.file_path,
            file_hash=package.file_hash,
            imported_at=package.imported_at,
            imported_by=package.imported_by,
            status=UpdateStatus.ROLLED_BACK,
            prior_version_ref=package.prior_version_ref,
        )
        await self._repo.save(session, rolled_back)

        # Re-activate the prior version
        prior = await self._repo.get_by_id(session, package.prior_version_ref)
        if prior is None:
            raise RollbackError(f"Prior version record {package.prior_version_ref} not found.")
        restored = UpdatePackage(
            id=prior.id,
            version=prior.version,
            manifest_json=prior.manifest_json,
            file_path=prior.file_path,
            file_hash=prior.file_hash,
            imported_at=prior.imported_at,
            imported_by=prior.imported_by,
            status=UpdateStatus.APPLIED,
            prior_version_ref=prior.prior_version_ref,
        )
        restored = await self._repo.save(session, restored)

        # Restore prior version to install target from its staging directory
        prior_staging = self._staging_path / "applied" / prior.version
        if prior_staging.exists():
            tmp_install = self._install_path.parent / (self._install_path.name + ".tmp")
            shutil.copytree(prior_staging, tmp_install, dirs_exist_ok=True)
            if self._install_path.exists():
                shutil.rmtree(self._install_path)
            tmp_install.rename(self._install_path)

        # Remove the rolled-back version's extracted staging directory (non-fatal cleanup)
        rolled_dir = self._staging_path / "applied" / package.version
        try:
            shutil.rmtree(rolled_dir, ignore_errors=True)
        except Exception:  # pragma: no cover — filesystem cleanup is best-effort
            pass

        await self._audit_writer.write(
            session,
            entity_type="update_package",
            entity_id=package_id,
            action="UPDATE_ROLLED_BACK",
            actor_id=actor_id,
            metadata={"from_version": package.version, "to_version": prior.version},
        )
        return restored

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def list_packages(
        self, session, offset: int = 0, limit: int = 20
    ) -> tuple[list[UpdatePackage], int]:
        return await self._repo.list(session, offset=offset, limit=limit)

    async def get_package(
        self, session, package_id: uuid.UUID
    ) -> Optional[UpdatePackage]:
        return await self._repo.get_by_id(session, package_id)
