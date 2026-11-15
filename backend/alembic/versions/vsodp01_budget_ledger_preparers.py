# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""budget ledger: record who last edited and who submitted an entry

Adds ``last_edited_by`` and ``submitted_by`` to budget transfers and modifications so segregation of
duties can refuse an approver who prepared the entry, not only the one who created it. Nullable
column adds, safe on existing rows.

Revision ID: vsodp01_budget_ledger_preparers
Revises: vsbfk01_spec_import_document_fk
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsodp01_budget_ledger_preparers"
down_revision: str | Sequence[str] | None = "vsbfk01_spec_import_document_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("oe_costmodel_budget_transfer", "oe_costmodel_budget_modification")
_COLS = ("last_edited_by", "submitted_by")


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for table in _TABLES:
        if table not in tables:
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        for col in _COLS:
            if col not in have:
                op.add_column(table, sa.Column(col, sa.String(36), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for table in _TABLES:
        if table not in tables:
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        for col in _COLS:
            if col in have:
                op.drop_column(table, col)
