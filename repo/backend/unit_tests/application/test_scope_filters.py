"""
Unit tests for api.scope_filters.

resolve_scoped_school_ids maps every ScopeType to its effective SCHOOL id set
using live DB queries.  Tests run against the shared in-memory SQLite fixture
so the SQL is executed for real — no mocking of the DB layer.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.api.scope_filters import (
    resolve_scoped_school_ids,
    resolve_school_scoped_location_ids,
    resolve_school_scoped_warehouse_ids,
)
from district_console.domain.entities.user import ScopeAssignment
from district_console.domain.enums import ScopeType
from district_console.infrastructure.orm import (
    ClassORM,
    DepartmentORM,
    IndividualORM,
    LocationORM,
    SchoolORM,
    WarehouseORM,
)

_DUMMY_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_DUMMY_TS = datetime(2024, 1, 1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scope(scope_type: ScopeType, ref_id: str) -> ScopeAssignment:
    return ScopeAssignment(
        id=_DUMMY_UUID,
        user_id=_DUMMY_UUID,
        scope_type=scope_type,
        scope_ref_id=uuid.UUID(ref_id),
        granted_by=_DUMMY_UUID,
        granted_at=_DUMMY_TS,
    )


async def _seed_school(db_session: AsyncSession, suffix: str = "A") -> SchoolORM:
    school = SchoolORM(
        id=str(uuid.uuid4()),
        name=f"School {suffix}",
        district_code=f"DC-{suffix}",
        is_active=True,
    )
    db_session.add(school)
    await db_session.flush()
    return school


async def _seed_department(db_session: AsyncSession, school_id: str, suffix: str = "A") -> DepartmentORM:
    dept = DepartmentORM(
        id=str(uuid.uuid4()),
        school_id=school_id,
        name=f"Dept {suffix}",
        is_active=True,
    )
    db_session.add(dept)
    await db_session.flush()
    return dept


async def _seed_class(db_session: AsyncSession, dept_id: str, suffix: str = "A") -> ClassORM:
    cls = ClassORM(
        id=str(uuid.uuid4()),
        department_id=dept_id,
        name=f"Class {suffix}",
        teacher_id=None,
        is_active=True,
    )
    db_session.add(cls)
    await db_session.flush()
    return cls


async def _seed_individual(db_session: AsyncSession, class_id: str, suffix: str = "A") -> IndividualORM:
    ind = IndividualORM(
        id=str(uuid.uuid4()),
        class_id=class_id,
        display_name=f"Student {suffix}",
        user_id=None,
    )
    db_session.add(ind)
    await db_session.flush()
    return ind


async def _seed_warehouse(db_session: AsyncSession, school_id: str) -> WarehouseORM:
    wh = WarehouseORM(
        id=str(uuid.uuid4()),
        name="WH-Unit",
        school_id=school_id,
        address="1 Test Ave",
        is_active=True,
    )
    db_session.add(wh)
    await db_session.flush()
    return wh


async def _seed_location(db_session: AsyncSession, warehouse_id: str) -> LocationORM:
    loc = LocationORM(
        id=str(uuid.uuid4()),
        warehouse_id=warehouse_id,
        zone="Z",
        aisle="01",
        bin_label="Z-01-01",
        is_active=True,
    )
    db_session.add(loc)
    await db_session.flush()
    return loc


# ---------------------------------------------------------------------------
# resolve_scoped_school_ids
# ---------------------------------------------------------------------------

async def test_empty_scopes_returns_empty_set(db_session):
    result = await resolve_scoped_school_ids(db_session, [])
    assert result == set()


async def test_school_scope_returns_school_id_directly(db_session):
    school = await _seed_school(db_session, "S1")
    scopes = [_scope(ScopeType.SCHOOL, school.id)]

    result = await resolve_scoped_school_ids(db_session, scopes)
    assert uuid.UUID(school.id) in result


async def test_department_scope_resolves_to_school(db_session):
    school = await _seed_school(db_session, "S2")
    dept = await _seed_department(db_session, school.id, "D2")
    scopes = [_scope(ScopeType.DEPARTMENT, dept.id)]

    result = await resolve_scoped_school_ids(db_session, scopes)
    assert uuid.UUID(school.id) in result
    assert uuid.UUID(dept.id) not in result


async def test_class_scope_resolves_through_department_to_school(db_session):
    school = await _seed_school(db_session, "S3")
    dept = await _seed_department(db_session, school.id, "D3")
    cls = await _seed_class(db_session, dept.id, "C3")
    scopes = [_scope(ScopeType.CLASS, cls.id)]

    result = await resolve_scoped_school_ids(db_session, scopes)
    assert uuid.UUID(school.id) in result


async def test_individual_scope_resolves_through_full_chain(db_session):
    school = await _seed_school(db_session, "S4")
    dept = await _seed_department(db_session, school.id, "D4")
    cls = await _seed_class(db_session, dept.id, "C4")
    ind = await _seed_individual(db_session, cls.id, "I4")
    scopes = [_scope(ScopeType.INDIVIDUAL, ind.id)]

    result = await resolve_scoped_school_ids(db_session, scopes)
    assert uuid.UUID(school.id) in result


async def test_multiple_scope_types_merged(db_session):
    """Multiple assignments (different types) should all resolve to their school."""
    school_a = await _seed_school(db_session, "MA")
    school_b = await _seed_school(db_session, "MB")
    dept = await _seed_department(db_session, school_b.id, "MB-D")

    scopes = [
        _scope(ScopeType.SCHOOL, school_a.id),
        _scope(ScopeType.DEPARTMENT, dept.id),
    ]
    result = await resolve_scoped_school_ids(db_session, scopes)
    assert uuid.UUID(school_a.id) in result
    assert uuid.UUID(school_b.id) in result


async def test_unknown_department_id_returns_no_school(db_session):
    """A scope pointing to a non-existent department produces no school IDs."""
    fake_id = str(uuid.uuid4())
    scopes = [_scope(ScopeType.DEPARTMENT, fake_id)]
    result = await resolve_scoped_school_ids(db_session, scopes)
    assert result == set()


async def test_unknown_class_id_returns_no_school(db_session):
    fake_id = str(uuid.uuid4())
    scopes = [_scope(ScopeType.CLASS, fake_id)]
    result = await resolve_scoped_school_ids(db_session, scopes)
    assert result == set()


async def test_unknown_individual_id_returns_no_school(db_session):
    fake_id = str(uuid.uuid4())
    scopes = [_scope(ScopeType.INDIVIDUAL, fake_id)]
    result = await resolve_scoped_school_ids(db_session, scopes)
    assert result == set()


# ---------------------------------------------------------------------------
# resolve_school_scoped_warehouse_ids
# ---------------------------------------------------------------------------

async def test_warehouse_ids_resolved_from_school_scope(db_session):
    school = await _seed_school(db_session, "W1")
    wh = await _seed_warehouse(db_session, school.id)
    scopes = [_scope(ScopeType.SCHOOL, school.id)]

    result = await resolve_school_scoped_warehouse_ids(db_session, scopes)
    # result is a set of UUID objects; wh.id is a str
    result_strs = {str(r) for r in result}
    assert wh.id in result_strs


async def test_warehouse_ids_empty_when_no_scope(db_session):
    result = await resolve_school_scoped_warehouse_ids(db_session, [])
    assert result == set()


async def test_warehouse_ids_excludes_other_school_warehouses(db_session):
    school_a = await _seed_school(db_session, "WA")
    school_b = await _seed_school(db_session, "WB")
    wh_a = await _seed_warehouse(db_session, school_a.id)
    wh_b = await _seed_warehouse(db_session, school_b.id)
    scopes = [_scope(ScopeType.SCHOOL, school_a.id)]

    result = await resolve_school_scoped_warehouse_ids(db_session, scopes)
    result_strs = {str(r) for r in result}
    assert wh_a.id in result_strs
    assert wh_b.id not in result_strs


# ---------------------------------------------------------------------------
# resolve_school_scoped_location_ids
# ---------------------------------------------------------------------------

async def test_location_ids_resolved_from_school_scope(db_session):
    school = await _seed_school(db_session, "L1")
    wh = await _seed_warehouse(db_session, school.id)
    loc = await _seed_location(db_session, wh.id)
    scopes = [_scope(ScopeType.SCHOOL, school.id)]

    result = await resolve_school_scoped_location_ids(db_session, scopes)
    result_strs = {str(r) for r in result}
    assert loc.id in result_strs


async def test_location_ids_empty_when_no_scope(db_session):
    result = await resolve_school_scoped_location_ids(db_session, [])
    assert result == set()


async def test_location_ids_excludes_other_school_locations(db_session):
    school_a = await _seed_school(db_session, "LA")
    school_b = await _seed_school(db_session, "LB")
    wh_a = await _seed_warehouse(db_session, school_a.id)
    wh_b = await _seed_warehouse(db_session, school_b.id)
    loc_a = await _seed_location(db_session, wh_a.id)
    loc_b = await _seed_location(db_session, wh_b.id)
    scopes = [_scope(ScopeType.SCHOOL, school_a.id)]

    result = await resolve_school_scoped_location_ids(db_session, scopes)
    result_strs = {str(r) for r in result}
    assert loc_a.id in result_strs
    assert loc_b.id not in result_strs
