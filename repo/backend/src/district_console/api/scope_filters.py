"""
Helpers for deriving SCHOOL-scoped warehouse/location authorization sets.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.domain.entities.user import ScopeAssignment
from district_console.domain.enums import ScopeType
from district_console.infrastructure.orm import ClassORM, DepartmentORM, IndividualORM
from district_console.infrastructure.repositories import InventoryRepository


async def resolve_scoped_school_ids(
    session: AsyncSession,
    scopes: list[ScopeAssignment],
) -> set[uuid.UUID]:
    """
    Resolve effective SCHOOL IDs from all scope assignment types.

    Mapping:
      - SCHOOL     -> schools.id
      - DEPARTMENT -> departments.school_id
      - CLASS      -> classes.department_id -> departments.school_id
      - INDIVIDUAL -> individuals.class_id -> classes.department_id -> departments.school_id
    """
    school_ids = {
        scope.scope_ref_id
        for scope in scopes
        if scope.scope_type == ScopeType.SCHOOL
    }

    department_ids = [
        str(scope.scope_ref_id)
        for scope in scopes
        if scope.scope_type == ScopeType.DEPARTMENT
    ]
    class_ids = [
        str(scope.scope_ref_id)
        for scope in scopes
        if scope.scope_type == ScopeType.CLASS
    ]
    individual_ids = [
        str(scope.scope_ref_id)
        for scope in scopes
        if scope.scope_type == ScopeType.INDIVIDUAL
    ]

    if department_ids:
        dept_school_result = await session.execute(
            select(DepartmentORM.school_id).where(DepartmentORM.id.in_(department_ids))
        )
        school_ids.update(uuid.UUID(value) for value in dept_school_result.scalars().all())

    if class_ids:
        class_school_result = await session.execute(
            select(DepartmentORM.school_id)
            .select_from(ClassORM)
            .join(DepartmentORM, DepartmentORM.id == ClassORM.department_id)
            .where(ClassORM.id.in_(class_ids))
        )
        school_ids.update(uuid.UUID(value) for value in class_school_result.scalars().all())

    if individual_ids:
        individual_school_result = await session.execute(
            select(DepartmentORM.school_id)
            .select_from(IndividualORM)
            .join(ClassORM, ClassORM.id == IndividualORM.class_id)
            .join(DepartmentORM, DepartmentORM.id == ClassORM.department_id)
            .where(IndividualORM.id.in_(individual_ids))
        )
        school_ids.update(
            uuid.UUID(value) for value in individual_school_result.scalars().all()
        )

    return school_ids


async def resolve_school_scoped_warehouse_ids(
    session: AsyncSession,
    scopes: list[ScopeAssignment],
) -> set[uuid.UUID]:
    """Resolve warehouse IDs accessible from SCHOOL scope assignments."""
    school_ids = await resolve_scoped_school_ids(session, scopes)
    if not school_ids:
        return set()

    warehouses = await InventoryRepository.list_warehouses(
        session,
        school_ids=list(school_ids),
    )
    return {warehouse.id for warehouse in warehouses}


async def resolve_school_scoped_location_ids(
    session: AsyncSession,
    scopes: list[ScopeAssignment],
) -> set[uuid.UUID]:
    """Resolve location IDs accessible from SCHOOL scope assignments."""
    warehouse_ids = await resolve_school_scoped_warehouse_ids(session, scopes)
    if not warehouse_ids:
        return set()

    locations = await InventoryRepository.list_locations(
        session,
        warehouse_ids=list(warehouse_ids),
    )
    return {location.id for location in locations}
