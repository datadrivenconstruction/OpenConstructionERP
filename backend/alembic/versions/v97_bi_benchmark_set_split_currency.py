# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""bi_dashboards - a benchmark set remembers its split and reporting currency.

Two nullable columns on ``oe_bi_dashboards_benchmark_set``, nothing else:

* ``split_by``: the project attribute (client, region, ...) or row field (``classification.din276``) each
  project's reading is split by. NULL is no split, which is how every existing set reads today.
* ``reporting_currency``: the ISO code money is restated in with the platform's FX rates. NULL keeps every
  currency apart, again exactly how existing sets read.

Purely additive and inspector-guarded, so a database where ``create_all`` already built the columns reaches
this revision and does nothing.

Revision ID: v97_bi_benchmark_set_split_currency
Revises: v96_requisition_orders_approvals_feed
Create Date: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v97_bi_benchmark_set_split_currency"
down_revision: str | Sequence[str] | None = "v96_requisition_orders_approvals_feed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SET = "oe_bi_dashboards_benchmark_set"
_COLUMNS = (
    ("split_by", sa.String(length=129)),
    ("reporting_currency", sa.String(length=3)),
)


def _existing() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if _SET not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(_SET)}


def upgrade() -> None:
    """Add the two columns, each only when missing; skip when the table itself is absent."""
    if _SET not in sa.inspect(op.get_bind()).get_table_names():
        return
    existing = _existing()
    for name, type_ in _COLUMNS:
        if name not in existing:
            with op.batch_alter_table(_SET) as batch:
                batch.add_column(sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    """Drop the two columns where present."""
    existing = _existing()
    for name, _type in reversed(_COLUMNS):
        if name in existing:
            with op.batch_alter_table(_SET) as batch:
                batch.drop_column(name)
