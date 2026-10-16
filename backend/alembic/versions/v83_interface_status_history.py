# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""interface_management - status history of each interface.

One new table, ``oe_interface_mgmt_history``: one row per thing that happened to
an interface's status - created, moved by a person, approval requested,
approved, rejected or cancelled on its approval route - with who, when, the
from and to status, the comment and a soft link to the approval instance. The
row cascades with its interface and with its project.

Both foreign keys are named explicitly (``fk_interface_mgmt_history_project``,
``fk_interface_mgmt_history_interface``): the platform naming convention would
spell them out at 65 and 69 characters, past PostgreSQL's 63-character
identifier limit. Every name here matches the model. Every step is
inspector-guarded, so a database whose table ``create_all`` already built
reaches this revision and does nothing. Additive only, no data is moved: the
interfaces that exist before this revision simply start their history at the
first change made after it.

Revision ID: v83_interface_status_history
Revises: v82_requisition_item_sources
Create Date: 2026-10-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v83_interface_status_history"
down_revision: str | Sequence[str] | None = "v82_requisition_item_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_interface_mgmt_history"
_INDEXES: list[tuple[str, list[str]]] = [
    ("ix_interface_mgmt_history_project", ["project_id"]),
    ("ix_interface_mgmt_history_interface", ["interface_id", "changed_at"]),
]


def upgrade() -> None:
    """Create the history table and its indexes, each only when missing."""
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():
        op.create_table(
            _TABLE,
            sa.Column("id", GUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column(
                "project_id",
                GUID(),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE", name="fk_interface_mgmt_history_project"),
                nullable=False,
            ),
            sa.Column(
                "interface_id",
                GUID(),
                sa.ForeignKey(
                    "oe_interface_mgmt_interface.id",
                    ondelete="CASCADE",
                    name="fk_interface_mgmt_history_interface",
                ),
                nullable=False,
            ),
            sa.Column("event", sa.String(length=30), nullable=False),
            sa.Column("from_status", sa.String(length=30), nullable=True),
            sa.Column("to_status", sa.String(length=30), nullable=True),
            sa.Column("actor_id", GUID(), nullable=True),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("approval_instance_id", GUID(), nullable=True),
            sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_oe_interface_mgmt_history"),
        )
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes(_TABLE)}
    for name, cols in _INDEXES:
        if name not in existing:
            op.create_index(name, _TABLE, cols)


def downgrade() -> None:
    """Drop the history table (its indexes go with it)."""
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)
