"""
Configuration center domain entities.

ConfigDictionary holds key-value pairs organised by category.
WorkflowNode defines allowed state transitions and their required roles.
NotificationTemplate holds local-only notification content.
DistrictDescriptor holds regional/district-level reporting metadata.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from district_console.domain.enums import RoleType


@dataclass
class ConfigDictionary:
    """
    A typed key-value entry in the centralised configuration dictionary.

    is_system=True entries are seeded by the application and cannot be
    deleted via the admin UI (they can be updated if mutable=True).
    category groups related entries (e.g. "reason_codes", "timeliness_options").
    """
    id: uuid.UUID
    category: str
    key: str
    value: str
    description: str
    is_system: bool = False
    updated_by: Optional[uuid.UUID] = None
    updated_at: Optional[datetime] = None


@dataclass
class WorkflowNode:
    """
    A permitted state transition in a named workflow.

    workflow_name identifies the workflow (e.g. "resource_review", "count_approval").
    required_role is the minimum role needed to trigger this transition.
    condition_json stores optional rule conditions as serialised JSON.
    """
    id: uuid.UUID
    workflow_name: str
    from_state: str
    to_state: str
    required_role: RoleType
    condition_json: Optional[str] = None   # JSON string; None = no additional conditions


@dataclass
class NotificationTemplate:
    """
    A local-only notification template used for desktop alert messages.

    Templates are rendered by the application layer and displayed as
    system tray notifications or modal dialogs — no email or internet.
    subject_template and body_template use a simple {variable} substitution.
    """
    id: uuid.UUID
    name: str
    event_type: str         # e.g. "count_session_expired", "key_rotation_due"
    subject_template: str
    body_template: str
    is_active: bool = True


@dataclass
class DistrictDescriptor:
    """
    A district or regional descriptor used in reports and exports.

    Examples: district_name, region_code, fiscal_year, reporting_currency.
    """
    id: uuid.UUID
    key: str
    value: str
    description: str
    region: Optional[str] = None    # None = applies to all regions
