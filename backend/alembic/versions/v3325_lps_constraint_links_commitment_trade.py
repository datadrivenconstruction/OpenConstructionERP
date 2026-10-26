# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""schedule_advanced: constraint links, commitment trade and target progress

Adds to ``oe_schedule_advanced_constraint`` the record that clears it
(``linked_type``, ``linked_id``, ``link_resolved_at``), and to
``oe_schedule_advanced_commitment`` the subcontractor that promised the work
(``subcontractor_id``) and the progress the schedule activity reaches when the
commitment is completed (``target_progress_pct``). All nullable, no backfill.

Inspector-guarded: the boot path runs ``create_all`` before migrations, so the
columns may already exist.

Revision ID: v3325_lps_constraint_links_commitment_trade
Revises: v200_supplier_pricelists_discounts
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v3325_lps_constraint_links_commitment_trade"
down_revision: str | Sequence[str] | None = "v200_supplier_pricelists_discounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "oe_schedule_advanced_constraint"
_COMMITMENT = "oe_schedule_advanced_commitment"

_COLUMNS: dict[str, list[sa.Column]] = {
    _CONSTRAINT: [
        sa.Column("linked_type", sa.String(32), nullable=True),
        sa.Column("linked_id", sa.String(36), nullable=True),
        sa.Column("link_resolved_at", sa.DateTime(timezone=True), nullable=True),
    ],
    _COMMITMENT: [
        sa.Column("subcontractor_id", sa.String(36), nullable=True),
        sa.Column("target_progress_pct", sa.Numeric(5, 2), nullable=True),
    ],
}
_INDEXES = {
    "ix_oe_schedule_advanced_constraint_linked_id": (_CONSTRAINT, "linked_id"),
    "ix_oe_schedule_advanced_commitment_subcontractor_id": (_COMMITMENT, "subcontractor_id"),
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table, cols in _COLUMNS.items():
        if table not in tables:
            continue
        have = {c["name"] for c in inspector.get_columns(table)}
        for col in cols:
            if col.name not in have:
                op.add_column(table, col.copy())
    for name, (table, col) in _INDEXES.items():
        if table in tables and name not in {i["name"] for i in inspector.get_indexes(table)}:
            op.create_index(name, table, [col])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for name, (table, _col) in _INDEXES.items():
        if table in tables and name in {i["name"] for i in inspector.get_indexes(table)}:
            op.drop_index(name, table_name=table)
    for table, cols in _COLUMNS.items():
        if table not in tables:
            continue
        have = {c["name"] for c in inspector.get_columns(table)}
        for col in cols:
            if col.name in have:
                op.drop_column(table, col.name)
