"""
Update package management REST endpoints.

Prefix: /api/v1/admin/updates
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.api.dependencies import (
    get_current_user,
    get_db_session,
    get_update_service,
    require_permission,
)
from district_console.api.schemas import PaginatedResponse, UpdatePackageResponse
from district_console.application.update_service import ManifestValidationError, RollbackError

router = APIRouter()


@router.get(
    "/",
    response_model=PaginatedResponse[UpdatePackageResponse],
    dependencies=[Depends(require_permission("updates.manage"))],
)
async def list_packages(
    offset: int = 0,
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_update_service),
):
    items, total = await svc.list_packages(session, offset=offset, limit=limit)
    return PaginatedResponse(
        items=[_pkg_resp(p) for p in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/import",
    response_model=UpdatePackageResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("updates.manage"))],
)
async def import_package(
    file: UploadFile,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_update_service),
):
    content = await file.read()
    try:
        package = await svc.import_package(
            session, content, file.filename or "package.zip", current_user[0], datetime.utcnow()
        )
    except ManifestValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_MANIFEST", "message": str(exc)},
        )
    return _pkg_resp(package)


@router.post(
    "/{package_id}/apply",
    response_model=UpdatePackageResponse,
    dependencies=[Depends(require_permission("updates.manage"))],
)
async def apply_package(
    package_id: str,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_update_service),
):
    package = await svc.apply_package(
        session, uuid.UUID(package_id), current_user[0], datetime.utcnow()
    )
    return _pkg_resp(package)


@router.post(
    "/{package_id}/rollback",
    response_model=UpdatePackageResponse,
    dependencies=[Depends(require_permission("updates.manage"))],
)
async def rollback_package(
    package_id: str,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_update_service),
):
    try:
        package = await svc.rollback_package(
            session, uuid.UUID(package_id), current_user[0], datetime.utcnow()
        )
    except RollbackError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ROLLBACK_NOT_POSSIBLE", "message": str(exc)},
        )
    return _pkg_resp(package)


def _pkg_resp(p) -> UpdatePackageResponse:
    return UpdatePackageResponse(
        package_id=str(p.id),
        version=p.version,
        file_path=p.file_path,
        file_hash=p.file_hash,
        status=p.status.value if hasattr(p.status, "value") else p.status,
        imported_at=p.imported_at.isoformat(),
        imported_by=str(p.imported_by),
        prior_version_ref=str(p.prior_version_ref) if p.prior_version_ref else None,
        can_rollback=p.can_rollback(),
    )
