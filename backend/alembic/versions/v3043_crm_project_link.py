# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CRM deal → delivery Project link — oe_crm_opportunity.project_id column.

Adds a single nullable ``project_id`` column to ``oe_crm_opportunity`` so a
deal can reference the delivery/estimate Project it relates to (a won deal
references the project it spawned; an open deal can be pre-linked to a
tender/estimate project). Mirrors the existing ``primary_contact_id``
pattern: a plain ``String(36)`` GUID column with NO database-level foreign
key, so unit fixtures that never load the Projects module don't trip
``NoReferencedTableError``. The CRM never duplicates Project or Contact
data — it only stores the reference.

Idempotent: guarded by an inspector so re-running after SQLite's
``Base.metadata.create_all`` / ``sqlite_auto_migrate`` (dev) is a no-op;
Postgres prod gets the DDL. ``project_id`` is ``String(36)`` to match the
platform's ``GUID`` TypeDecorator on SQLite + PostgreSQL.

Revision ID: v3043_crm_project_link
Revises: v3042_clash_selection_sets
Created: 2026-05-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3043_crm_project_link"
down_revision: Union[str, Sequence[str], None] = "v3042_clash_selection_sets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_crm_opportunity"
_COLUMN = "project_id"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(inspector: sa.engine.reflection.Inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    """Add oe_crm_opportunity.project_id (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        # CRM tables not created yet (fresh DB) — create_all / the
        # v3016_crm migration will declare the column from the ORM model.
        return
    if _has_column(inspector, _TABLE, _COLUMN):
        return

    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    """Drop oe_crm_opportunity.project_id."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, _TABLE) and _has_column(inspector, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
