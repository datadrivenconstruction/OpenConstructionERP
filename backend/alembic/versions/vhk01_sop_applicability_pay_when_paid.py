# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""payment regime applicability, pay-when-paid flag, index source attribution.

Additive columns only, every one nullable or with a server default:

* ``oe_payment_clock_regime``: ``applies_from``, ``min_contract_value``,
  ``min_contract_value_supply``, ``private_scope_rule``,
  ``early_claim_counts_from_billing_date``, ``adjudication_window_days``,
  ``conditional_payment_void`` - when a security-of-payment statute covers a
  contract, and what it voids.
* ``oe_contracts_contract.pay_when_paid`` - the contract makes payment
  conditional on the payer being paid.
* ``oe_price_index_series``: ``source_attribution`` and ``source_url`` - the
  credit an official index publisher requires.

Inspector-guarded, so a re-run, or an install whose boot already added the
columns from the models, changes nothing.

Revision ID: vhk01_sop_applicability
Revises: vsub01_agreement_documents
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "vhk01_sop_applicability"
down_revision: Union[str, Sequence[str], None] = "vsub01_agreement_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns() -> dict[str, list[sa.Column]]:
    return {
        "oe_payment_clock_regime": [
            sa.Column("applies_from", sa.Date(), nullable=True),
            sa.Column("min_contract_value", sa.Numeric(18, 2), nullable=True),
            sa.Column("min_contract_value_supply", sa.Numeric(18, 2), nullable=True),
            sa.Column("private_scope_rule", sa.String(48), nullable=False, server_default=""),
            sa.Column("early_claim_counts_from_billing_date", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("adjudication_window_days", sa.Integer(), nullable=True),
            sa.Column("conditional_payment_void", sa.Boolean(), nullable=False, server_default=sa.false()),
        ],
        "oe_contracts_contract": [
            sa.Column("pay_when_paid", sa.Boolean(), nullable=False, server_default=sa.false()),
        ],
        "oe_price_index_series": [
            sa.Column("source_attribution", sa.Text(), nullable=False, server_default=""),
            sa.Column("source_url", sa.String(500), nullable=False, server_default=""),
        ],
    }


def upgrade() -> None:
    """Add the columns that are not there yet."""
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table, columns in _columns().items():
        if table not in tables:
            continue
        present = {c["name"] for c in inspector.get_columns(table)}
        for column in columns:
            if column.name not in present:
                op.add_column(table, column)


def downgrade() -> None:
    """Drop the columns this revision added."""
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table, columns in _columns().items():
        if table not in tables:
            continue
        present = {c["name"] for c in inspector.get_columns(table)}
        for column in reversed(columns):
            if column.name in present:
                op.drop_column(table, column.name)
