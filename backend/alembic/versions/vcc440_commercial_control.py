# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""commercial control - approval amount bands and CVR budget / committed columns.

Additive columns only:

* ``oe_approval_routes_step.amount_min`` / ``amount_max``: the amount band a step
  applies to (``amount_min <= amount < amount_max``), both nullable.
* ``oe_approval_routes_instance.amount`` / ``amount_currency``: the amount the
  workflow was routed on, for the audit trail.
* ``oe_cvr_line.budget_cost`` / ``committed_cost``: filled from the cost spine,
  ``0`` for existing lines.

Every add is inspector-guarded, so a running install whose boot heal already
added a column, or a re-run, changes nothing.

Revision ID: vcc440_commercial_control
Revises: vsch01_activity_assignee_text
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "vcc440_commercial_control"
down_revision: Union[str, Sequence[str], None] = "vsch01_activity_assignee_text"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS: tuple[tuple[str, sa.Column], ...] = (
    ("oe_approval_routes_step", sa.Column("amount_min", sa.Numeric(18, 2), nullable=True)),
    ("oe_approval_routes_step", sa.Column("amount_max", sa.Numeric(18, 2), nullable=True)),
    ("oe_approval_routes_instance", sa.Column("amount", sa.Numeric(18, 2), nullable=True)),
    ("oe_approval_routes_instance", sa.Column("amount_currency", sa.String(3), nullable=True)),
    ("oe_cvr_line", sa.Column("budget_cost", sa.Numeric(18, 4), nullable=False, server_default="0")),
    ("oe_cvr_line", sa.Column("committed_cost", sa.Numeric(18, 4), nullable=False, server_default="0")),
)


def _columns(inspector: sa.Inspector, table: str) -> set[str] | None:
    if table not in inspector.get_table_names():
        return None
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    """Add the six columns where they are missing."""
    inspector = sa.inspect(op.get_bind())
    for table, column in _COLUMNS:
        existing = _columns(inspector, table)
        if existing is not None and column.name not in existing:
            op.add_column(table, column.copy())


def downgrade() -> None:
    """Drop the six columns where they exist."""
    inspector = sa.inspect(op.get_bind())
    for table, column in reversed(_COLUMNS):
        existing = _columns(inspector, table)
        if existing is not None and column.name in existing:
            with op.batch_alter_table(table) as batch:
                batch.drop_column(column.name)
