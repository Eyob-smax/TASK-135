"""
Taxonomy administration REST endpoints.

Prefix: /api/v1/admin/taxonomy
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.api.dependencies import (
    get_current_user,
    get_db_session,
    get_taxonomy_service,
    require_permission,
)
from district_console.api.schemas import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    TaxonomyRuleCreate,
    TaxonomyRuleResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@router.get(
    "/categories/",
    response_model=List[CategoryResponse],
    dependencies=[Depends(get_current_user)],
)
async def list_categories(
    parent_id: Optional[str] = None,
    flat: bool = False,
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_taxonomy_service),
):
    if flat:
        cats = await svc.list_all_categories(session)
    else:
        pid = uuid.UUID(parent_id) if parent_id else None
        cats = await svc.list_categories(session, parent_id=pid)
    return [_cat_resp(c) for c in cats]


@router.post(
    "/categories/",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("admin.manage_config"))],
)
async def create_category(
    body: CategoryCreate,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_taxonomy_service),
):
    parent_id = uuid.UUID(body.parent_id) if body.parent_id else None
    cat = await svc.create_category(
        session, body.name, current_user[0], datetime.utcnow(), parent_id=parent_id
    )
    return _cat_resp(cat)


@router.put(
    "/categories/{category_id}",
    response_model=CategoryResponse,
    dependencies=[Depends(require_permission("admin.manage_config"))],
)
async def update_category(
    category_id: str,
    body: CategoryUpdate,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_taxonomy_service),
):
    cat = await svc.update_category(
        session, uuid.UUID(category_id), body.name, current_user[0], datetime.utcnow()
    )
    return _cat_resp(cat)


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("admin.manage_config"))],
)
async def deactivate_category(
    category_id: str,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_taxonomy_service),
):
    await svc.deactivate_category(
        session, uuid.UUID(category_id), current_user[0], datetime.utcnow()
    )


# ---------------------------------------------------------------------------
# Validation rules
# ---------------------------------------------------------------------------

@router.get(
    "/rules/",
    response_model=List[TaxonomyRuleResponse],
    dependencies=[Depends(get_current_user)],
)
async def list_rules(
    field: Optional[str] = None,
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_taxonomy_service),
):
    rules = await svc.list_validation_rules(session, field=field)
    return [_rule_resp(r) for r in rules]


@router.post(
    "/rules/",
    response_model=TaxonomyRuleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("admin.manage_config"))],
)
async def create_rule(
    body: TaxonomyRuleCreate,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_taxonomy_service),
):
    rule = await svc.save_validation_rule(
        session,
        body.field,
        body.rule_type,
        body.rule_value,
        current_user[0],
        datetime.utcnow(),
        description=body.description,
    )
    return _rule_resp(rule)


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("admin.manage_config"))],
)
async def delete_rule(
    rule_id: str,
    current_user: Annotated[tuple, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db_session),
    svc=Depends(get_taxonomy_service),
):
    await svc.delete_validation_rule(
        session, uuid.UUID(rule_id), current_user[0], datetime.utcnow()
    )


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _cat_resp(c) -> CategoryResponse:
    return CategoryResponse(
        category_id=str(c.id),
        name=c.name,
        depth=c.depth,
        path_slug=c.path_slug,
        parent_id=str(c.parent_id) if c.parent_id else None,
        is_active=c.is_active,
    )


def _rule_resp(r) -> TaxonomyRuleResponse:
    return TaxonomyRuleResponse(
        rule_id=str(r.id),
        field=r.field,
        rule_type=r.rule_type,
        rule_value=str(r.rule_value),
        is_active=r.is_active,
        description=r.description,
    )
