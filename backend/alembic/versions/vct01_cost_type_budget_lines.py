# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Budget lines per cost type; purchase-order items and subcontracts pick one

* ``oe_procurement_po_item.budget_line_id`` and
  ``oe_subcontractors_agreement.budget_line_id``: the budget line (cost code x
  cost type) the commitment rolls into. Nullable, indexed, additive, so the
  boot heal and ``alembic upgrade`` agree.
* A bill position now becomes one budget line per cost type, so the partial
  unique index on ``(project_id, boq_position_id)`` from
  ``v3107_costmodel_idempotency`` would refuse the second line of a position.
  It is replaced by the same index over ``(project_id, boq_position_id,
  category)``. The index only exists where revisions were run (``create_all``
  never built it), so on a heal-built schema there is nothing to drop.

Revision ID: vct01_cost_type_budget_lines
Revises: vdoc01_ncr_linked_documents
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vct01_cost_type_budget_lines"
down_revision: str | Sequence[str] | None = "vdoc01_ncr_linked_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GUID = sa.String(36)
_COLUMN = "budget_line_id"
_LINK_TABLES = ("oe_procurement_po_item", "oe_subcontractors_agreement")

_BUDGET = "oe_costmodel_budget_line"
_OLD_UNIQUE = "uq_oe_costmodel_budget_line_project_position"
_NEW_UNIQUE = "uq_oe_costmodel_budget_line_project_position_category"


def _indexes(inspector: sa.engine.reflection.Inspector, table: str) -> set[str]:
    return {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table in _LINK_TABLES:
        if table not in tables:
            continue
        if _COLUMN not in {c["name"] for c in inspector.get_columns(table)}:
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column(_COLUMN, _GUID, nullable=True))
        index = f"ix_{table}_{_COLUMN}"
        if index not in _indexes(sa.inspect(op.get_bind()), table):
            op.create_index(index, table, [_COLUMN])

    if _BUDGET not in tables:
        return
    existing = _indexes(inspector, _BUDGET)
    if _OLD_UNIQUE in existing:
        op.drop_index(_OLD_UNIQUE, table_name=_BUDGET)
    if _NEW_UNIQUE not in existing:
        op.create_index(
            _NEW_UNIQUE,
            _BUDGET,
            ["project_id", "boq_position_id", "category"],
            unique=True,
            sqlite_where=sa.text("boq_position_id IS NOT NULL"),
            postgresql_where=sa.text("boq_position_id IS NOT NULL"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    # The per-position index is not restored: positions already split over cost types would violate it.
    if _BUDGET in tables and _NEW_UNIQUE in _indexes(inspector, _BUDGET):
        op.drop_index(_NEW_UNIQUE, table_name=_BUDGET)
    for table in _LINK_TABLES:
        if table not in tables:
            continue
        index = f"ix_{table}_{_COLUMN}"
        if index in _indexes(inspector, table):
            op.drop_index(index, table_name=table)
        if _COLUMN in {c["name"] for c in inspector.get_columns(table)}:
            with op.batch_alter_table(table) as batch:
                batch.drop_column(_COLUMN)
