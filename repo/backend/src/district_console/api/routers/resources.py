"""
Resource library REST endpoints.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.api.dependencies import (
    get_current_user,
    get_current_user_with_scope,
    get_db_session,
    require_permission,
)
from district_console.api.schemas import (
    ClassifyRequest,
    CountLineResponse,
    ImportCsvResponse,
    ImportFileResponse,
    PaginatedResponse,
    PublishRequest,
    ResourceCreate,
    ResourceMetadataResponse,
    ResourceResponse,
    ResourceRevisionResponse,
    ResourceUpdate,
    ReviewSubmitRequest,
)
from district_console.application.resource_service import ResourceService
from district_console.domain.entities.role import Role
from district_console.domain.enums import CountMode, ResourceType
from district_console.domain.exceptions import (
    DomainValidationError,
    DuplicateResourceError,
    ResourceNotFoundError,
    ScopeViolationError,
)

router = APIRouter()


def _get_resource_service(request: Request) -> ResourceService:
    return request.app.state.container.resource_service


def _resource_to_schema(resource, metadata=None) -> ResourceResponse:
    meta_resp = None
    if metadata is not None:
        meta_resp = ResourceMetadataResponse(
            min_age=metadata.age_range_min,
            max_age=metadata.age_range_max,
            timeliness_type=metadata.timeliness.value if metadata.timeliness else None,
        )
    return ResourceResponse(
        resource_id=str(resource.id),
        title=resource.title,
        resource_type=resource.resource_type.value,
        status=resource.status.value,
        file_fingerprint=resource.file_fingerprint,
        isbn=resource.isbn,
        dedup_key=resource.dedup_key,
        created_by=str(resource.created_by),
        created_at=resource.created_at.isoformat(),
        updated_at=resource.updated_at.isoformat(),
        metadata=meta_resp,
        owner_scope_type=resource.owner_scope_type,
        owner_scope_ref_id=resource.owner_scope_ref_id,
    )


def _revision_to_schema(revision) -> ResourceRevisionResponse:
    return ResourceRevisionResponse(
        revision_id=str(revision.id),
        resource_id=str(revision.resource_id),
        revision_number=revision.revision_number,
        file_hash=revision.file_hash,
        file_size=revision.file_size,
        imported_by=str(revision.imported_by),
        created_at=revision.created_at.isoformat(),
    )


@router.get("/", response_model=PaginatedResponse[ResourceResponse])
async def list_resources(
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
    status: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    created_by: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[ResourceResponse]:
    from district_console.application.rbac_service import RbacService
    _, roles, scopes = user_with_scope
    rbac = RbacService()
    rbac.check_permission(roles, "resources.view")
    svc: ResourceService = _get_resource_service(request)
    filters = {}
    if not rbac.is_administrator(roles):
        allowed_pairs = [(s.scope_type.value, str(s.scope_ref_id)) for s in scopes]
        if not allowed_pairs:
            raise ScopeViolationError("resources", "all")
        # Non-admin users see district-wide resources (owner_scope_ref_id IS NULL)
        # plus resources explicitly scoped to a matching (scope_type, scope_ref_id) pair.
        filters["allowed_scope_pairs"] = allowed_pairs
    if status:
        filters["status"] = status
    if resource_type:
        filters["resource_type"] = resource_type
    if keyword:
        filters["keyword"] = keyword
    if created_by:
        filters["created_by"] = created_by

    items, total = await svc.list_resources(session, filters, offset, limit)
    result = []
    for r in items:
        meta = await svc.get_resource_metadata(session, r.id)
        result.append(_resource_to_schema(r, meta))
    return PaginatedResponse(
        items=result,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/",
    status_code=201,
    response_model=ResourceResponse,
    dependencies=[Depends(require_permission("resources.create"))],
)
async def create_resource(
    body: ResourceCreate,
    current_user: Annotated[tuple[uuid.UUID, list[Role]], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> ResourceResponse:
    actor_id, _ = current_user
    svc: ResourceService = _get_resource_service(request)
    now = datetime.utcnow()
    resource_type = ResourceType(body.resource_type)
    content = body.title.encode()
    try:
        resource, _ = await svc.import_file(
            session, content, resource_type, body.title, body.isbn, None, actor_id, now
        )
    except DuplicateResourceError as exc:
        raise HTTPException(status_code=409, detail={"code": "DUPLICATE_RESOURCE", "message": exc.message})
    if body.owner_scope_type or body.owner_scope_ref_id:
        resource.owner_scope_type = body.owner_scope_type
        resource.owner_scope_ref_id = body.owner_scope_ref_id
        repo = request.app.state.container.resource_service._resource_repo
        await repo.save(session, resource)
    return _resource_to_schema(resource)


@router.get("/{resource_id}", response_model=ResourceResponse)
async def get_resource(
    resource_id: uuid.UUID,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> ResourceResponse:
    from district_console.application.rbac_service import RbacService
    _, roles, scopes = user_with_scope
    rbac = RbacService()
    rbac.check_permission(roles, "resources.view")
    allowed_pairs: set[tuple[str, str]] | None = None
    if not rbac.is_administrator(roles):
        allowed_pairs = {(s.scope_type.value, str(s.scope_ref_id)) for s in scopes}
        if not allowed_pairs:
            raise ScopeViolationError("resources", str(resource_id))

    svc: ResourceService = _get_resource_service(request)
    try:
        resource = await svc.get_resource(session, resource_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Resource not found."})

    # Object-level scope check: if the resource has an explicit scope owner, verify
    # the caller's scope assignments include that (type, ref_id) pair.
    if allowed_pairs is not None and resource.owner_scope_ref_id is not None:
        if (resource.owner_scope_type, resource.owner_scope_ref_id) not in allowed_pairs:
            raise ScopeViolationError("resources", str(resource_id))

    meta = await svc.get_resource_metadata(session, resource_id)
    return _resource_to_schema(resource, meta)


@router.put(
    "/{resource_id}",
    response_model=ResourceResponse,
    dependencies=[Depends(require_permission("resources.edit"))],
)
async def update_resource(
    resource_id: uuid.UUID,
    body: ResourceUpdate,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> ResourceResponse:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    rbac = RbacService()
    allowed_pairs: set[tuple[str, str]] | None = None
    if not rbac.is_administrator(roles):
        allowed_pairs = {(s.scope_type.value, str(s.scope_ref_id)) for s in scopes}
        if not allowed_pairs:
            raise ScopeViolationError("resources", str(resource_id))
    svc: ResourceService = _get_resource_service(request)
    try:
        resource = await svc.get_resource(session, resource_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Resource not found."})

    if allowed_pairs is not None and resource.owner_scope_ref_id is not None:
        if (resource.owner_scope_type, resource.owner_scope_ref_id) not in allowed_pairs:
            raise ScopeViolationError("resources", str(resource_id))

    from district_console.domain.enums import ResourceStatus
    if resource.status != ResourceStatus.DRAFT:
        raise HTTPException(status_code=409, detail={"code": "INVALID_STATE_TRANSITION", "message": "Only DRAFT resources can be updated."})

    repo = request.app.state.container.resource_service._resource_repo
    if body.title is not None:
        resource.title = body.title
    if body.isbn is not None:
        resource.isbn = body.isbn
    resource.updated_at = datetime.utcnow()
    await repo.save(session, resource)
    return _resource_to_schema(resource)


@router.post(
    "/import/file",
    status_code=201,
    response_model=ImportFileResponse,
    dependencies=[Depends(require_permission("resources.import"))],
)
async def import_file(
    current_user: Annotated[tuple[uuid.UUID, list[Role]], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
    file: UploadFile = File(...),
    resource_type: str = Form("BOOK"),
    title: str = Form(...),
    isbn: Optional[str] = Form(None),
) -> ImportFileResponse:
    actor_id, _ = current_user
    svc: ResourceService = _get_resource_service(request)
    content = await file.read()
    now = datetime.utcnow()
    try:
        resource, revision = await svc.import_file(
            session, content, ResourceType(resource_type), title, isbn, None, actor_id, now
        )
        return ImportFileResponse(
            resource_id=str(resource.id),
            revision_id=str(revision.id),
            is_duplicate=False,
            checkpoint_id=str(resource.id),
        )
    except DuplicateResourceError as exc:
        raise HTTPException(status_code=409, detail={"code": "DUPLICATE_RESOURCE", "message": exc.message, "details": {"existing_id": exc.existing_id}})


@router.post(
    "/import/csv",
    status_code=201,
    response_model=ImportCsvResponse,
    dependencies=[Depends(require_permission("resources.import"))],
)
async def import_csv(
    current_user: Annotated[tuple[uuid.UUID, list[Role]], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
    file: UploadFile = File(...),
) -> ImportCsvResponse:
    actor_id, _ = current_user
    svc: ResourceService = _get_resource_service(request)
    content = await file.read()
    csv_text = content.decode("utf-8")
    now = datetime.utcnow()
    job_id = str(uuid.uuid4())
    result = await svc.import_csv(session, csv_text, actor_id, job_id, now)
    return ImportCsvResponse(**result)


@router.get("/{resource_id}/revisions", response_model=list[ResourceRevisionResponse])
async def list_revisions(
    resource_id: uuid.UUID,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> list[ResourceRevisionResponse]:
    from district_console.application.rbac_service import RbacService
    _, roles, scopes = user_with_scope
    rbac = RbacService()
    rbac.check_permission(roles, "resources.view")
    if not rbac.is_administrator(roles) and not scopes:
        raise ScopeViolationError("resources", str(resource_id))

    svc: ResourceService = _get_resource_service(request)
    try:
        revisions = await svc.list_revisions(session, resource_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Resource not found."})
    return [_revision_to_schema(r) for r in revisions]


@router.post(
    "/{resource_id}/submit-review",
    response_model=ResourceResponse,
    dependencies=[Depends(require_permission("resources.submit_review"))],
)
async def submit_for_review(
    resource_id: uuid.UUID,
    body: ReviewSubmitRequest,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> ResourceResponse:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    rbac = RbacService()
    svc: ResourceService = _get_resource_service(request)
    now = datetime.utcnow()
    try:
        resource = await svc.get_resource(session, resource_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Resource not found."})
    if not rbac.is_administrator(roles) and resource.owner_scope_ref_id is not None:
        allowed_pairs = {(s.scope_type.value, str(s.scope_ref_id)) for s in scopes}
        if (resource.owner_scope_type, resource.owner_scope_ref_id) not in allowed_pairs:
            raise ScopeViolationError("resources", str(resource_id))
    try:
        resource = await svc.submit_for_review(
            session, resource_id, uuid.UUID(body.reviewer_id), actor_id, roles, now
        )
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Resource not found."})
    return _resource_to_schema(resource)


@router.post(
    "/{resource_id}/publish",
    response_model=ResourceResponse,
    dependencies=[Depends(require_permission("resources.publish"))],
)
async def publish_resource(
    resource_id: uuid.UUID,
    body: PublishRequest,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> ResourceResponse:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    rbac = RbacService()
    svc: ResourceService = _get_resource_service(request)
    now = datetime.utcnow()
    try:
        resource = await svc.get_resource(session, resource_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Resource not found."})
    if not rbac.is_administrator(roles) and resource.owner_scope_ref_id is not None:
        allowed_pairs = {(s.scope_type.value, str(s.scope_ref_id)) for s in scopes}
        if (resource.owner_scope_type, resource.owner_scope_ref_id) not in allowed_pairs:
            raise ScopeViolationError("resources", str(resource_id))
    try:
        resource = await svc.publish_resource(session, resource_id, body.reviewer_notes, actor_id, roles, now)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Resource not found."})
    return _resource_to_schema(resource)


@router.post(
    "/{resource_id}/unpublish",
    response_model=ResourceResponse,
    dependencies=[Depends(require_permission("resources.publish"))],
)
async def unpublish_resource(
    resource_id: uuid.UUID,
    body: PublishRequest,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> ResourceResponse:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    rbac = RbacService()
    svc: ResourceService = _get_resource_service(request)
    now = datetime.utcnow()
    try:
        resource = await svc.get_resource(session, resource_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Resource not found."})
    if not rbac.is_administrator(roles) and resource.owner_scope_ref_id is not None:
        allowed_pairs = {(s.scope_type.value, str(s.scope_ref_id)) for s in scopes}
        if (resource.owner_scope_type, resource.owner_scope_ref_id) not in allowed_pairs:
            raise ScopeViolationError("resources", str(resource_id))
    try:
        resource = await svc.unpublish_resource(session, resource_id, body.reviewer_notes, actor_id, roles, now)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Resource not found."})
    return _resource_to_schema(resource)


@router.post(
    "/{resource_id}/classify",
    status_code=204,
    dependencies=[Depends(require_permission("resources.classify"))],
)
async def classify_resource(
    resource_id: uuid.UUID,
    body: ClassifyRequest,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> None:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    rbac = RbacService()
    svc: ResourceService = _get_resource_service(request)
    now = datetime.utcnow()
    try:
        resource = await svc.get_resource(session, resource_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Resource not found."})
    if not rbac.is_administrator(roles) and resource.owner_scope_ref_id is not None:
        allowed_pairs = {(s.scope_type.value, str(s.scope_ref_id)) for s in scopes}
        if (resource.owner_scope_type, resource.owner_scope_ref_id) not in allowed_pairs:
            raise ScopeViolationError("resources", str(resource_id))
    try:
        await svc.classify_resource(
            session, resource_id, body.min_age, body.max_age,
            body.timeliness_type, actor_id, now,
        )
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Resource not found."})
    except DomainValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": "VALIDATION_ERROR", "message": exc.message})


@router.post(
    "/{resource_id}/request-allocation",
    status_code=204,
    dependencies=[Depends(require_permission("resources.view"))],
)
async def request_allocation(
    resource_id: uuid.UUID,
    user_with_scope: Annotated[tuple, Depends(get_current_user_with_scope)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> None:
    from district_console.application.rbac_service import RbacService
    actor_id, roles, scopes = user_with_scope
    rbac = RbacService()
    svc: ResourceService = _get_resource_service(request)
    try:
        resource = await svc.get_resource(session, resource_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Resource not found."})
    if not rbac.is_administrator(roles) and resource.owner_scope_ref_id is not None:
        allowed_pairs = {(s.scope_type.value, str(s.scope_ref_id)) for s in scopes}
        if (resource.owner_scope_type, resource.owner_scope_ref_id) not in allowed_pairs:
            raise ScopeViolationError("resources", str(resource_id))
    try:
        await svc.request_allocation(session, resource_id, actor_id, datetime.utcnow())
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Resource not found."})
