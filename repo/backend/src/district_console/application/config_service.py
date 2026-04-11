"""
Configuration center application service.

Manages ConfigDictionary, WorkflowNode, NotificationTemplate, and
DistrictDescriptor records. All mutation methods write an AuditEvent.
System config entries (is_system=True) cannot be deleted.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from district_console.domain.entities.config import (
    ConfigDictionary,
    DistrictDescriptor,
    NotificationTemplate,
    WorkflowNode,
)
from district_console.domain.enums import RoleType
from district_console.domain.exceptions import DomainValidationError


class SystemEntryProtectedError(Exception):
    """Raised when attempting to delete an is_system=True config entry."""
    def __init__(self, entry_id: uuid.UUID) -> None:
        super().__init__(f"Config entry {entry_id} is a system entry and cannot be deleted.")
        self.entry_id = entry_id


class ConfigService:
    """
    Application service for the configuration center.

    All write operations require actor_id for audit trail.
    """

    def __init__(
        self,
        config_repo,
        workflow_repo,
        template_repo,
        descriptor_repo,
        audit_writer,
    ) -> None:
        self._config_repo = config_repo
        self._workflow_repo = workflow_repo
        self._template_repo = template_repo
        self._descriptor_repo = descriptor_repo
        self._audit_writer = audit_writer

    # ------------------------------------------------------------------
    # ConfigDictionary
    # ------------------------------------------------------------------

    async def list_config(
        self,
        session,
        category: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ConfigDictionary], int]:
        return await self._config_repo.list_all(session, category=category, offset=offset, limit=limit)

    async def get_config(
        self, session, category: str, key: str
    ) -> Optional[ConfigDictionary]:
        return await self._config_repo.get(session, category, key)

    async def upsert_config(
        self,
        session,
        category: str,
        key: str,
        value: str,
        description: str,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> ConfigDictionary:
        if not category.strip():
            raise DomainValidationError("category", category, "must not be empty")
        if not key.strip():
            raise DomainValidationError("key", key, "must not be empty")
        if not value.strip():
            raise DomainValidationError("value", value, "must not be empty")

        existing = await self._config_repo.get(session, category, key)
        if existing is not None:
            entry = ConfigDictionary(
                id=existing.id,
                category=category,
                key=key,
                value=value,
                description=description,
                is_system=existing.is_system,
                updated_by=actor_id,
                updated_at=now,
            )
            action = "CONFIG_UPDATED"
        else:
            entry = ConfigDictionary(
                id=uuid.uuid4(),
                category=category,
                key=key,
                value=value,
                description=description,
                is_system=False,
                updated_by=actor_id,
                updated_at=now,
            )
            action = "CONFIG_CREATED"

        entry = await self._config_repo.save(session, entry)
        await self._audit_writer.write(
            session,
            entity_type="config_dictionary",
            entity_id=entry.id,
            action=action,
            actor_id=actor_id,
            metadata={"category": category, "key": key},
        )
        return entry

    async def delete_config(
        self,
        session,
        entry_id: uuid.UUID,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> None:
        entry = await self._config_repo.get_by_id(session, entry_id)
        if entry is None:
            return
        if entry.is_system:
            raise SystemEntryProtectedError(entry_id)
        await self._config_repo.delete(session, entry_id)
        await self._audit_writer.write(
            session,
            entity_type="config_dictionary",
            entity_id=entry_id,
            action="CONFIG_DELETED",
            actor_id=actor_id,
            metadata={"category": entry.category, "key": entry.key},
        )

    # ------------------------------------------------------------------
    # WorkflowNode
    # ------------------------------------------------------------------

    async def list_workflow_nodes(
        self, session, workflow_name: Optional[str] = None
    ) -> list[WorkflowNode]:
        return await self._workflow_repo.list_by_workflow(session, workflow_name=workflow_name)

    async def save_workflow_node(
        self,
        session,
        workflow_name: str,
        from_state: str,
        to_state: str,
        required_role: str,
        condition_json: Optional[str],
        actor_id: uuid.UUID,
        now: datetime,
        node_id: Optional[uuid.UUID] = None,
    ) -> WorkflowNode:
        role = RoleType(required_role)
        if node_id is not None:
            existing = await self._workflow_repo.get_by_id(session, node_id)
        else:
            existing = None

        node = WorkflowNode(
            id=existing.id if existing else uuid.uuid4(),
            workflow_name=workflow_name,
            from_state=from_state,
            to_state=to_state,
            required_role=role,
            condition_json=condition_json,
        )
        node = await self._workflow_repo.save(session, node)
        await self._audit_writer.write(
            session,
            entity_type="workflow_node",
            entity_id=node.id,
            action="WORKFLOW_NODE_SAVED",
            actor_id=actor_id,
            metadata={"workflow_name": workflow_name, "transition": f"{from_state}->{to_state}"},
        )
        return node

    async def delete_workflow_node(
        self, session, node_id: uuid.UUID, actor_id: uuid.UUID, now: datetime
    ) -> None:
        await self._workflow_repo.delete(session, node_id)
        await self._audit_writer.write(
            session,
            entity_type="workflow_node",
            entity_id=node_id,
            action="WORKFLOW_NODE_DELETED",
            actor_id=actor_id,
        )

    # ------------------------------------------------------------------
    # NotificationTemplate
    # ------------------------------------------------------------------

    async def list_templates(self, session) -> list[NotificationTemplate]:
        return await self._template_repo.list_all(session)

    async def save_template(
        self,
        session,
        name: str,
        event_type: str,
        subject_template: str,
        body_template: str,
        is_active: bool,
        actor_id: uuid.UUID,
        now: datetime,
        template_id: Optional[uuid.UUID] = None,
    ) -> NotificationTemplate:
        if template_id is not None:
            existing = await self._template_repo.get_by_id(session, template_id)
        else:
            existing = None

        template = NotificationTemplate(
            id=existing.id if existing else uuid.uuid4(),
            name=name,
            event_type=event_type,
            subject_template=subject_template,
            body_template=body_template,
            is_active=is_active,
        )
        template = await self._template_repo.save(session, template)
        await self._audit_writer.write(
            session,
            entity_type="notification_template",
            entity_id=template.id,
            action="TEMPLATE_SAVED",
            actor_id=actor_id,
            metadata={"name": name, "event_type": event_type},
        )
        return template

    # ------------------------------------------------------------------
    # DistrictDescriptor
    # ------------------------------------------------------------------

    async def list_descriptors(self, session) -> list[DistrictDescriptor]:
        return await self._descriptor_repo.list_all(session)

    async def save_descriptor(
        self,
        session,
        key: str,
        value: str,
        description: str,
        region: Optional[str],
        actor_id: uuid.UUID,
        now: datetime,
    ) -> DistrictDescriptor:
        if not key.strip():
            raise DomainValidationError("key", key, "must not be empty")

        existing = await self._descriptor_repo.get_by_key(session, key)
        desc = DistrictDescriptor(
            id=existing.id if existing else uuid.uuid4(),
            key=key,
            value=value,
            description=description,
            region=region,
        )
        desc = await self._descriptor_repo.save(session, desc)
        await self._audit_writer.write(
            session,
            entity_type="district_descriptor",
            entity_id=desc.id,
            action="DESCRIPTOR_SAVED",
            actor_id=actor_id,
            metadata={"key": key},
        )
        return desc
