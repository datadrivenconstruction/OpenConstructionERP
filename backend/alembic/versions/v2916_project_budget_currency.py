"""v2.9.16 — ProjectBudget.currency_code.

Adds a ``currency_code`` ISO 4217 column to ``oe_finance_budget`` so each
budget line can record its native currency instead of relying on the first
row in the response payload to seed the page-wide currency. Mirrors the
shape of ``Invoice.currency_code`` and ``Payment.currency_code``.

Revision ID: v2916_project_budget_currency
Revises: v294_project_storage_override
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2916_project_budget_currency"
down_revision: Union[str, Sequence[str], None] = "v294_project_storage_override"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_finance_budget"
_COLUMN = "currency_code"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(col["name"] == name for col in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    if _has_column(inspector, _TABLE, _COLUMN):
        return
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.String(length=3), nullable=False, server_default="EUR"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    if not _has_column(inspector, _TABLE, _COLUMN):
        return
    op.drop_column(_TABLE, _COLUMN)
