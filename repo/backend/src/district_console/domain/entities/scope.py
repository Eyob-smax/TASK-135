"""
Organisational scope hierarchy: School → Department → Class → Individual.

These entities define the data-scope boundaries used in RBAC. A user's
ScopeAssignment references one of these entities to limit the records they
can read or modify to a specific branch of the hierarchy.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass
class School:
    id: uuid.UUID
    name: str
    district_code: str
    is_active: bool = True


@dataclass
class Department:
    id: uuid.UUID
    school_id: uuid.UUID
    name: str
    is_active: bool = True


@dataclass
class Class:
    """
    A class/section within a department, optionally assigned a primary teacher.
    teacher_id references users.id and may be None for unassigned classes.
    """
    id: uuid.UUID
    department_id: uuid.UUID
    name: str
    teacher_id: Optional[uuid.UUID] = None
    is_active: bool = True


@dataclass
class Individual:
    """
    A student or staff member associated with a specific class.
    user_id may be None for individuals without a system account.
    """
    id: uuid.UUID
    class_id: uuid.UUID
    display_name: str
    user_id: Optional[uuid.UUID] = None
