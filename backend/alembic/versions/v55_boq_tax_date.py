# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""boq - a tax date of its own, apart from the price base.

One column on ``oe_boq_boq``: ``tax_date``, nullable free text in the same
shapes as ``base_date`` (a day, a month, a quarter or a year). ``base_date``
used to answer two questions, the price level the unit rates are current at
and the day the bill's VAT is resolved on, so a bill priced at 2025 rates for
works carried out in 2026 was taxed at 2025's rate (Russia: 20 instead of 22).
The tax lookup now reads ``tax_date`` when it is stated and ``base_date``
otherwise.

Nothing is backfilled, on purpose: NULL means "same as the base date", which is
exactly what every existing bill meant, so no existing bill is taxed
differently after this revision. Copying ``base_date`` into the column would
also have frozen it, so a later edit to the price base would stop moving the
tax date on bills that never chose one.

This one does NOT need running by hand. The boot schema heal
(``postgres_auto_migrate``) adds a missing nullable column with ``ADD COLUMN IF
NOT EXISTS``, so a running install that boots the new code gets the column
without an upgrade, and a stamped install is not left without it.
Inspector-guarded, so an install whose schema came from ``create_all`` plus the
heal reaches this revision and adds nothing.

Revision ID: v55_boq_tax_date
Revises: v54_contracts_payment_plan
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v55_boq_tax_date"
down_revision: Union[str, Sequence[str], None] = "v54_contracts_payment_plan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_boq_boq"
_COLUMN = "tax_date"


def upgrade() -> None:
    """Add ``oe_boq_boq.tax_date`` (nullable ``VARCHAR(40)``) if it is missing."""
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _COLUMN not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(40), nullable=True))


def downgrade() -> None:
    """Drop the column. Bills that stated a tax date go back to their base date."""
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COLUMN)
