# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""variations: a traced line says what it does to its source

Adds ``change_kind`` to ``oe_variations_boq_trace``.

Issue #435. The trace table records where a line of a variation's bill came
from - the schedule-of-values line it affects, the estimating position the
scope was taken from - and nothing about what the variation does to that
source. A line citing contract line 020 at 30 m3 could be extra quantity of
the same item, a re-measure of the item down from 40, or the whole item
omitted, and the three price differently: an omission is money coming off
the contract, an addition is money going on, and the schedule of values
cannot be re-valued without knowing which. That distinction is what makes an
omission price correctly, and the bill had no column for it.

``change_kind`` is one of ``added``, ``removed`` or ``modified``, stated by
the estimator rather than inferred from the sign of the quantity: a negative
quantity is consistent with an omission and also with a typing error, and
only a person knows which. A validation rule reports a kind that contradicts
the numbers; nothing corrects it silently.

NOT NULL with a server default of ``added``, and no backfill beyond that
default. A line with no trace row at all is added scope - the request's own
bill holds only the scope the variation changes, and a line that names no
contracted item is by construction not omitting or modifying one - so a row
that predates this column has to read the same way as no row. Any other
default would put a claim about an omission into rows nobody has looked at.

Guarded the way this tree guards ``create_table``, and for the same failure:
the boot path runs ``Base.metadata.create_all`` before anybody can run
``alembic upgrade head``, so on a real install the column already exists by
the time an operator upgrades by hand. An unguarded ``ADD COLUMN`` raises
DuplicateColumn, rolls back the whole upgrade rather than this revision, and
takes every later revision with it.

Revision ID: v3322_variation_trace_change_kind
Revises: v3321_variation_submitted_snapshot
Create Date: 2026-09-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3322_variation_trace_change_kind"
down_revision: Union[str, Sequence[str], None] = "v3321_variation_submitted_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "oe_variations_boq_trace"
COLUMN = "change_kind"


def _has_table(insp: sa.engine.reflection.Inspector, table: str) -> bool:
    return table in insp.get_table_names()


def _has_column(insp: sa.engine.reflection.Inspector, table: str, column: str) -> bool:
    if not _has_table(insp, table):
        return False
    return any(col["name"] == column for col in insp.get_columns(table))


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not _has_table(insp, TABLE) or _has_column(insp, TABLE, COLUMN):
        return
    # String(10), the same type the model declares, so a fresh volume built
    # by ``create_all`` and an upgraded one end up with one schema rather
    # than two that each look right alone. NOT NULL is safe with the server
    # default in the same statement: every existing row takes ``added``.
    op.add_column(
        TABLE,
        sa.Column(COLUMN, sa.String(length=10), nullable=False, server_default="added"),
    )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _has_column(insp, TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
