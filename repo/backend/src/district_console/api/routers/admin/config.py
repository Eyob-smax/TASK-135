"""
Configuration center REST endpoints.

All routes require admin.manage_config permission except GET routes
which require any authenticated user.

Prefix: /api/v1/admin/config

ROUTE ORDERING NOTE: The general PUT /{category}/{key} is registered LAST so
that the more specific PUT /templates/{name} and PUT /descriptors/{key} routes
are matched first by FastAPI's path router.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.api.dependencies import (
    get_config_service,
    get_current_user,
    get_db_session,
    require_permission,
)
from district_console.api.schemas import (
    ConfigDictionaryResponse,
    ConfigUpsertRequest,
    DistrictDescriptorResponse,
    DistrictDescriptorUpsert,
    NotificationTemplateResponse,
    NotificationTemplateUpsert,
    PaginatedResponse,
    WorkflowNodeCreate,
    WorkflowNodeResponse,
)
from district_console.domain.entities.role import Role

router = APIRouter()


# ---------------------------------------------------------------------------
# ConfigDictionary — list and delete
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=PaginatedResponse[ConfigDictionaryResponse],
    dependencies=[Depends(get_current_user)],
)
async def list_config(
    category: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_config_service),
):
    items, total = await svc.list_config(session, category=category, offset=offset, limit=limit)
    return PaginatedResponse(
        items=[_config_resp(c) for c in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.delete(
    "/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("admin.manage_config"))],
)
async def delete_config(
    entry_id: str,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_config_service),
):
    from district_console.application.config_service import SystemEntryProtectedError
    try:
        await svc.delete_config(session, uuid.UUID(entry_id), current_user[0], datetime.utcnow())
    except SystemEntryProtectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "INSUFFICIENT_PERMISSION", "message": str(exc)},
        )


# ---------------------------------------------------------------------------
# WorkflowNode
# ---------------------------------------------------------------------------

@router.get(
    "/workflow-nodes/",
    response_model=List[WorkflowNodeResponse],
    dependencies=[Depends(get_current_user)],
)
async def list_workflow_nodes(
    workflow_name: Optional[str] = None,
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_config_service),
):
    nodes = await svc.list_workflow_nodes(session, workflow_name=workflow_name)
    return [_node_resp(n) for n in nodes]


@router.post(
    "/workflow-nodes/",
    response_model=WorkflowNodeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("admin.manage_config"))],
)
async def create_workflow_node(
    body: WorkflowNodeCreate,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_config_service),
):
    node = await svc.save_workflow_node(
        session,
        body.workflow_name,
        body.from_state,
        body.to_state,
        body.required_role,
        body.condition_json,
        current_user[0],
        datetime.utcnow(),
    )
    return _node_resp(node)


@router.delete(
    "/workflow-nodes/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("admin.manage_config"))],
)
async def delete_workflow_node(
    node_id: str,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_config_service),
):
    await svc.delete_workflow_node(session, uuid.UUID(node_id), current_user[0], datetime.utcnow())


# ---------------------------------------------------------------------------
# NotificationTemplate — registered before general PUT /{category}/{key}
# ---------------------------------------------------------------------------

@router.get(
    "/templates/",
    response_model=List[NotificationTemplateResponse],
    dependencies=[Depends(get_current_user)],
)
async def list_templates(
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_config_service),
):
    return [_template_resp(t) for t in await svc.list_templates(session)]


@router.put(
    "/templates/{name}",
    response_model=NotificationTemplateResponse,
    dependencies=[Depends(require_permission("admin.manage_config"))],
)
async def upsert_template(
    name: str,
    body: NotificationTemplateUpsert,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_config_service),
):
    template = await svc.save_template(
        session,
        body.name,
        body.event_type,
        body.subject_template,
        body.body_template,
        body.is_active,
        current_user[0],
        datetime.utcnow(),
    )
    return _template_resp(template)


# ---------------------------------------------------------------------------
# DistrictDescriptor — registered before general PUT /{category}/{key}
# ---------------------------------------------------------------------------

@router.get(
    "/descriptors/",
    response_model=List[DistrictDescriptorResponse],
    dependencies=[Depends(get_current_user)],
)
async def list_descriptors(
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_config_service),
):
    return [_descriptor_resp(d) for d in await svc.list_descriptors(session)]


@router.put(
    "/descriptors/{key}",
    response_model=DistrictDescriptorResponse,
    dependencies=[Depends(require_permission("admin.manage_config"))],
)
async def upsert_descriptor(
    key: str,
    body: DistrictDescriptorUpsert,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_config_service),
):
    desc = await svc.save_descriptor(
        session, key, body.value, body.description, body.region, current_user[0], datetime.utcnow()
    )
    return _descriptor_resp(desc)


# ---------------------------------------------------------------------------
# ConfigDictionary — general PUT registered last to avoid shadowing specific routes above
# ---------------------------------------------------------------------------

@router.put(
    "/{category}/{key}",
    response_model=ConfigDictionaryResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("admin.manage_config"))],
)
async def upsert_config(
    category: str,
    key: str,
    body: ConfigUpsertRequest,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_config_service),
):
    actor_id, _ = current_user
    entry = await svc.upsert_config(
        session, category, key, body.value, body.description, actor_id, datetime.utcnow()
    )
    return _config_resp(entry)


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _config_resp(c) -> ConfigDictionaryResponse:
    return ConfigDictionaryResponse(
        entry_id=str(c.id),
        category=c.category,
        key=c.key,
        value=c.value,
        description=c.description,
        is_system=c.is_system,
        updated_by=str(c.updated_by) if c.updated_by else None,
        updated_at=c.updated_at.isoformat() if c.updated_at else None,
    )


def _node_resp(n) -> WorkflowNodeResponse:
    return WorkflowNodeResponse(
        node_id=str(n.id),
        workflow_name=n.workflow_name,
        from_state=n.from_state,
        to_state=n.to_state,
        required_role=n.required_role.value if hasattr(n.required_role, "value") else n.required_role,
        condition_json=n.condition_json,
    )


def _template_resp(t) -> NotificationTemplateResponse:
    return NotificationTemplateResponse(
        template_id=str(t.id),
        name=t.name,
        event_type=t.event_type,
        subject_template=t.subject_template,
        body_template=t.body_template,
        is_active=t.is_active,
    )


def _descriptor_resp(d) -> DistrictDescriptorResponse:
    return DistrictDescriptorResponse(
        descriptor_id=str(d.id),
        key=d.key,
        value=d.value,
        description=d.description,
        region=d.region,
    )
