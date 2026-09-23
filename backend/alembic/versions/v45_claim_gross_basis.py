# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""contracts - record what a progress claim's gross amount is made of.

One nullable column, ``oe_contracts_progress_claim.gross_basis``. It holds
``"cost"`` for a claim billed off recorded cost of work and ``"lines"`` for a
claim whose gross is the sum of its own period values, and it decides whether a
later line write may re-read the gross from the lines.

NULL is the whole point of the column being nullable rather than defaulted.
Every claim written before this revision carries NULL, and NULL means not
recorded rather than "lines": those rows keep exactly the behaviour they had.
The basis cannot be backfilled for them either, because a cost claim whose
gross was already overwritten from its lines now looks identical to a line
claim that always said that, and a default would state something about them
that nobody measured.

DDL only, no row is written, and the step asks the database first, so an
install whose schema the boot heal already carried reaches this revision and
changes nothing.

This one does NOT need running by hand. A new nullable column is additive, and
``postgres_auto_migrate`` adds model-declared columns with ALTER TABLE ... ADD
COLUMN IF NOT EXISTS on boot, so a running install picks it up from the model
without an upgrade. That is why the column is declared on ``ProgressClaim``
and not only here: the model is what reaches production, and a column that
exists in the database but not in the models is read by nothing and written by
nothing.

Revision ID: v45_claim_gross_basis
Revises: v44_owner_filter_indexes
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v45_claim_gross_basis"
down_revision: Union[str, Sequence[str], None] = "v44_owner_filter_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CLAIM = "oe_contracts_progress_claim"
_COLUMN = "gross_basis"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _column_names(inspector: sa.engine.reflection.Inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not _has_table(inspector, _CLAIM):
        # The claim table comes from a much earlier revision, so a missing one
        # means the chain never got that far. Adding a column to a table that
        # is not there would stop the whole upgrade.
        return
    if _COLUMN not in _column_names(inspector, _CLAIM):
        op.add_column(_CLAIM, sa.Column(_COLUMN, sa.String(length=10), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _has_table(inspector, _CLAIM) and _COLUMN in _column_names(inspector, _CLAIM):
        op.drop_column(_CLAIM, _COLUMN)
