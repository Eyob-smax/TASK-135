"""
Offline update package domain entity.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from district_console.domain.enums import UpdateStatus


@dataclass
class UpdatePackage:
    """
    An offline software update imported via the admin UI.

    Update packages are distributed as ZIP archives containing:
    - A signed manifest.json (version, file list, checksums, signature)
    - The application code/assets to be applied

    The application verifies the manifest integrity before applying any
    changes. The prior build is retained locally (prior_version_ref points
    to the previous UpdatePackage record) to enable one-step rollback.

    Only one package may be in APPLIED status at a time. Rollback sets the
    current package to ROLLED_BACK and re-activates the prior package.

    status transitions:
        PENDING  → APPLIED (after successful installation)
        APPLIED  → ROLLED_BACK (after rollback to prior version)
    """
    id: uuid.UUID
    version: str                     # Semantic version string, e.g. "1.2.3"
    manifest_json: str               # Raw JSON of the validated manifest
    file_path: str                   # Local path to the imported package archive
    file_hash: str                   # SHA-256 hex of the package archive
    imported_at: datetime
    imported_by: uuid.UUID
    status: UpdateStatus
    prior_version_ref: Optional[uuid.UUID] = None   # Points to the previous UpdatePackage

    def can_rollback(self) -> bool:
        """Return True if this package has a prior version to roll back to."""
        return self.status == UpdateStatus.APPLIED and self.prior_version_ref is not None
