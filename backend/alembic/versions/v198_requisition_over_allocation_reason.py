# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""procurement - the reason a requisition line goes over the BOQ demand.

One additive nullable column, no data rewrite:

* ``oe_procurement_req_item.over_allocation_reason``: free text a requester gives when a line, added to
  what other submitted requisitions already hold, exceeds what the BOQ needs.

The column is nullable, so the boot heal adds it on an install that never runs ``alembic upgrade``.
The step is inspector-guarded, so a database whose table ``create_all`` already built reaches this
revision and does nothing.

Revision ID: v198_requisition_over_allocation_reason
Revises: v197_sa_zatca_egs_units
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v198_requisition_over_allocation_reason"
down_revision: str | Sequence[str] | None = "v197_sa_zatca_egs_units"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_procurement_req_item"
_COLUMN = "over_allocation_reason"


def upgrade() -> None:
    """Add the column when the table exists and lacks it."""
    bind = op.get_bind()
    if _TABLE not in set(sa.inspect(bind).get_table_names()):
        return
    if _COLUMN not in {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the column when present."""
    bind = op.get_bind()
    if _TABLE not in set(sa.inspect(bind).get_table_names()):
        return
    if _COLUMN in {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COLUMN)
