"""Add owner_scope_type and owner_scope_ref_id to resources table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resources", sa.Column("owner_scope_type", sa.Text(), nullable=True))
    op.add_column("resources", sa.Column("owner_scope_ref_id", sa.Text(), nullable=True))
    # SQLite does not support ADD CONSTRAINT after table creation; the check is enforced
    # at the application layer via the ORM CheckConstraint on new inserts/updates.


def downgrade() -> None:
    op.drop_column("resources", "owner_scope_ref_id")
    op.drop_column("resources", "owner_scope_type")
