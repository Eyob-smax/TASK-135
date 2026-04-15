"""
Unit tests for domain.entities.scope — School, Department, Class, Individual.

These are plain dataclasses describing the organisational hierarchy used
for RBAC scope assignments. Tests verify construction, defaults, and
equality semantics that dataclass provides.
"""
from __future__ import annotations

import uuid

from district_console.domain.entities.scope import Class, Department, Individual, School


def test_school_requires_id_name_district_code():
    sid = uuid.uuid4()
    school = School(id=sid, name="Lincoln HS", district_code="LHS-01")
    assert school.id == sid
    assert school.name == "Lincoln HS"
    assert school.district_code == "LHS-01"
    assert school.is_active is True  # default


def test_school_can_be_deactivated():
    school = School(
        id=uuid.uuid4(), name="Closed HS", district_code="CHS", is_active=False
    )
    assert school.is_active is False


def test_school_equality_by_values():
    sid = uuid.uuid4()
    a = School(id=sid, name="A", district_code="A-1")
    b = School(id=sid, name="A", district_code="A-1")
    assert a == b


def test_department_defaults_active():
    dept = Department(id=uuid.uuid4(), school_id=uuid.uuid4(), name="Math")
    assert dept.is_active is True
    assert dept.name == "Math"


def test_class_teacher_id_optional_and_defaults_active():
    cls = Class(id=uuid.uuid4(), department_id=uuid.uuid4(), name="Math 101")
    assert cls.teacher_id is None
    assert cls.is_active is True


def test_class_accepts_teacher_id():
    teacher = uuid.uuid4()
    cls = Class(
        id=uuid.uuid4(),
        department_id=uuid.uuid4(),
        name="Math 201",
        teacher_id=teacher,
    )
    assert cls.teacher_id == teacher


def test_individual_user_id_optional():
    ind = Individual(
        id=uuid.uuid4(), class_id=uuid.uuid4(), display_name="Student A"
    )
    assert ind.user_id is None
    assert ind.display_name == "Student A"


def test_individual_accepts_user_id():
    user = uuid.uuid4()
    ind = Individual(
        id=uuid.uuid4(),
        class_id=uuid.uuid4(),
        display_name="Staff B",
        user_id=user,
    )
    assert ind.user_id == user
