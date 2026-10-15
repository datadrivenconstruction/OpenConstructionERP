# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""po_tax_rate - the VAT rate a purchase order is taxed at.

One nullable column on ``oe_procurement_po``: ``tax_rate_pct``, a decimal-string percentage. When it
is set the order's tax amount is derived from it and the subtotal; when it is null the order keeps the
absolute tax amount it was given, which is how every order written before this revision reads. No
backfill, because inventing a rate for an existing order would be the silent edit issue #515 asks us
not to make.

Inspector-guarded, so a database whose table ``create_all`` already built with the column reaches
this revision and does nothing.

Revision ID: v81_po_tax_rate
Revises: v80_project_handbook
Create Date: 2026-10-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v81_po_tax_rate"
down_revision: str | Sequence[str] | None = "v80_project_handbook"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_procurement_po"
_COLUMN = "tax_rate_pct"


def _has_column(bind: sa.engine.Connection) -> bool:
    return _COLUMN in {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}


def upgrade() -> None:
    """Add the nullable rate column when the table exists and lacks it."""
    bind = op.get_bind()
    if _TABLE in sa.inspect(bind).get_table_names() and not _has_column(bind):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Drop the rate column when it is there."""
    bind = op.get_bind()
    if _TABLE in sa.inspect(bind).get_table_names() and _has_column(bind):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)
