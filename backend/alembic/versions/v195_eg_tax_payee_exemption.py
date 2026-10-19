# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""eg_tax_payee_exemption - the payee's withholding exemption on a document's statutory taxes.

One column on an existing table, no data rewrite:

* ``oe_tax_withholding_statutory_calc.payee_exemption_code``: an exemption
  scheme the payee holds on file, by the code the country's rate rows name
  (Egypt's small-business regime of Law No. 6 of 2025 is the first). Empty for
  every existing row, which is what those rows meant: no exemption recorded.

The step is inspector-guarded, so a database whose column was already added on
boot reaches this revision without error.

Revision ID: v195_eg_tax_payee_exemption
Revises: v98_site_logistics_link_keys
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v195_eg_tax_payee_exemption"
down_revision: str | Sequence[str] | None = "v98_site_logistics_link_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_tax_withholding_statutory_calc"
_COLUMN = "payee_exemption_code"


def _has_column(bind: sa.engine.Connection) -> bool | None:
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return None
    return any(column["name"] == _COLUMN for column in inspector.get_columns(_TABLE))


def upgrade() -> None:
    present = _has_column(op.get_bind())
    if present is None or present:
        # No table yet (create_all builds it with the column), or the column
        # is already there.
        return
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.String(length=64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    if _has_column(op.get_bind()):
        op.drop_column(_TABLE, _COLUMN)
