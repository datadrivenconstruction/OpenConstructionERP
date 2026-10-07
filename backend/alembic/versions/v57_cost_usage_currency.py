"""Snapshot the currency of a cost-item usage without relabelling old money.

Revision ID: v57_cost_usage_currency
Revises: v56_punch_contract_scope
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v57_cost_usage_currency"
down_revision: str | Sequence[str] | None = "v56_punch_contract_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
_TABLE = "oe_cost_item_usage"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE in inspector.get_table_names() and "currency_at_use" not in {
        c["name"] for c in inspector.get_columns(_TABLE)
    }:
        op.add_column(_TABLE, sa.Column("currency_at_use", sa.String(10), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE in inspector.get_table_names() and "currency_at_use" in {
        c["name"] for c in inspector.get_columns(_TABLE)
    }:
        op.drop_column(_TABLE, "currency_at_use")
