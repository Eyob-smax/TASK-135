"""
Taxonomy administration application service.

Manages the multi-level category tree and taxonomy validation rules used for
resource metadata (timeliness, source, copyright, keywords, categories).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Optional

from district_console.domain.entities.resource_metadata import Category, TaxonomyValidationRule
from district_console.domain.exceptions import DomainValidationError

_SLUG_SAFE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    """Convert a display name to a URL/path-safe slug component."""
    return _SLUG_SAFE.sub("-", text.lower().strip()).strip("-")


class TaxonomyService:
    """
    Application service for taxonomy (category tree + validation rules).

    Categories form a tree: depth=0 are root nodes, depth=1 are children,
    etc. path_slug is the ancestor chain joined by '/'.
    """

    def __init__(self, taxonomy_repo, audit_writer) -> None:
        self._taxonomy_repo = taxonomy_repo
        self._audit_writer = audit_writer

    # ------------------------------------------------------------------
    # Category tree
    # ------------------------------------------------------------------

    async def list_categories(
        self, session, parent_id: Optional[uuid.UUID] = None
    ) -> list[Category]:
        """List direct children of parent_id, or root categories if None."""
        return await self._taxonomy_repo.list_categories(session, parent_id=parent_id)

    async def list_all_categories(self, session) -> list[Category]:
        return await self._taxonomy_repo.list_all_categories(session)

    async def get_category(
        self, session, category_id: uuid.UUID
    ) -> Optional[Category]:
        return await self._taxonomy_repo.get_category(session, category_id)

    async def create_category(
        self,
        session,
        name: str,
        actor_id: uuid.UUID,
        now: datetime,
        parent_id: Optional[uuid.UUID] = None,
    ) -> Category:
        if not name.strip():
            raise DomainValidationError("name", name, "must not be empty")

        depth = 0
        parent_slug = ""
        if parent_id is not None:
            parent = await self._taxonomy_repo.get_category(session, parent_id)
            if parent is None:
                raise DomainValidationError("parent_id", str(parent_id), "parent category not found")
            if not parent.is_active:
                raise DomainValidationError("parent_id", str(parent_id), "parent category is inactive")
            depth = parent.depth + 1
            parent_slug = parent.path_slug + "/"

        slug_component = _slugify(name)
        path_slug = parent_slug + slug_component
        # Ensure uniqueness — append uuid suffix if collision
        existing = await self._taxonomy_repo.get_category_by_slug(session, path_slug)
        if existing is not None:
            path_slug = f"{path_slug}-{str(uuid.uuid4())[:8]}"

        category = Category(
            id=uuid.uuid4(),
            name=name,
            depth=depth,
            path_slug=path_slug,
            parent_id=parent_id,
            is_active=True,
        )
        category = await self._taxonomy_repo.save_category(session, category)
        await self._audit_writer.write(
            session,
            entity_type="category",
            entity_id=category.id,
            action="CATEGORY_CREATED",
            actor_id=actor_id,
            metadata={"name": name, "depth": depth, "path_slug": path_slug},
        )
        return category

    async def update_category(
        self,
        session,
        category_id: uuid.UUID,
        name: str,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> Category:
        if not name.strip():
            raise DomainValidationError("name", name, "must not be empty")
        category = await self._taxonomy_repo.get_category(session, category_id)
        if category is None:
            raise DomainValidationError("category_id", str(category_id), "not found")

        # Recompute slug preserving depth/parent prefix
        parent_prefix = "/".join(category.path_slug.split("/")[:-1])
        slug_component = _slugify(name)
        path_slug = (parent_prefix + "/" + slug_component).lstrip("/")

        updated = Category(
            id=category.id,
            name=name,
            depth=category.depth,
            path_slug=path_slug,
            parent_id=category.parent_id,
            is_active=category.is_active,
        )
        updated = await self._taxonomy_repo.save_category(session, updated)
        await self._audit_writer.write(
            session,
            entity_type="category",
            entity_id=category_id,
            action="CATEGORY_UPDATED",
            actor_id=actor_id,
            metadata={"name": name},
        )
        return updated

    async def deactivate_category(
        self,
        session,
        category_id: uuid.UUID,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> None:
        category = await self._taxonomy_repo.get_category(session, category_id)
        if category is None:
            return
        deactivated = Category(
            id=category.id,
            name=category.name,
            depth=category.depth,
            path_slug=category.path_slug,
            parent_id=category.parent_id,
            is_active=False,
        )
        await self._taxonomy_repo.save_category(session, deactivated)
        await self._audit_writer.write(
            session,
            entity_type="category",
            entity_id=category_id,
            action="CATEGORY_DEACTIVATED",
            actor_id=actor_id,
        )

    # ------------------------------------------------------------------
    # Validation rules
    # ------------------------------------------------------------------

    async def list_validation_rules(
        self, session, field: Optional[str] = None
    ) -> list[TaxonomyValidationRule]:
        return await self._taxonomy_repo.list_validation_rules(session, field=field)

    async def save_validation_rule(
        self,
        session,
        field: str,
        rule_type: str,
        rule_value: str,
        actor_id: uuid.UUID,
        now: datetime,
        description: Optional[str] = None,
        rule_id: Optional[uuid.UUID] = None,
    ) -> TaxonomyValidationRule:
        if not field.strip():
            raise DomainValidationError("field", field, "must not be empty")
        if not rule_type.strip():
            raise DomainValidationError("rule_type", rule_type, "must not be empty")
        if rule_id is not None:
            existing = await self._taxonomy_repo.get_rule_by_id(session, rule_id)
        else:
            existing = None
        rule = TaxonomyValidationRule(
            id=existing.id if existing else uuid.uuid4(),
            field=field,
            rule_type=rule_type,
            rule_value=rule_value,
            is_active=True,
            description=description,
        )
        rule = await self._taxonomy_repo.save_rule(session, rule)
        await self._audit_writer.write(
            session,
            entity_type="taxonomy_rule",
            entity_id=rule.id,
            action="TAXONOMY_RULE_SAVED",
            actor_id=actor_id,
            metadata={"field": field, "rule_type": rule_type},
        )
        return rule

    async def delete_validation_rule(
        self,
        session,
        rule_id: uuid.UUID,
        actor_id: uuid.UUID,
        now: datetime,
    ) -> None:
        await self._taxonomy_repo.delete_rule(session, rule_id)
        await self._audit_writer.write(
            session,
            entity_type="taxonomy_rule",
            entity_id=rule_id,
            action="TAXONOMY_RULE_DELETED",
            actor_id=actor_id,
        )
