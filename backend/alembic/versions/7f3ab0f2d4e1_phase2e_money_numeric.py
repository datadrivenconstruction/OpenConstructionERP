"""phase2e_money_numeric

Revision ID: 7f3ab0f2d4e1
Revises: 85f7cfa6eecf
Create Date: 2026-04-19 11:40:00.000000

Phase 2e: convert string-stored money columns to native ``NUMERIC`` on
PostgreSQL so aggregation, range queries, and ORDER BY work at the SQL
layer without per-row Python parsing.

SQLite intentionally skipped — it stores everything as text regardless
of declared type, the MoneyType TypeDecorator handles the Python-side
normalisation, and ``ALTER COLUMN TYPE`` would require a ``batch_alter_table``
rebuild that churns every row for zero storage benefit. Dev DBs keep
working against the new ORM definitions unchanged.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "7f3ab0f2d4e1"
down_revision: Union[str, None] = "85f7cfa6eecf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Column specs ────────────────────────────────────────────────────────────
#
# Each entry: (table, column, precision, scale).  Scale=2 for money
# amounts, scale=6 for quantities / unit-rates / exchange rates so
# "1.234567 units" don't round-trip as "1.23".

_MONEY_COLUMNS: list[tuple[str, str, int, int]] = [
    # Finance — Invoice
    ("oe_finance_invoice", "amount_subtotal", 18, 2),
    ("oe_finance_invoice", "tax_amount", 18, 2),
    ("oe_finance_invoice", "retention_amount", 18, 2),
    ("oe_finance_invoice", "amount_total", 18, 2),
    # Finance — Invoice line items
    ("oe_finance_invoice_item", "quantity", 18, 6),
    ("oe_finance_invoice_item", "unit_rate", 18, 6),
    ("oe_finance_invoice_item", "amount", 18, 2),
    # Finance — Payment
    ("oe_finance_payment", "amount", 18, 2),
    ("oe_finance_payment", "exchange_rate_snapshot", 18, 6),
    # Finance — ProjectBudget (ported in Phase 2d, kept here so a single
    # roll-forward covers the whole money surface on a fresh PG deploy)
    ("oe_finance_budget", "original_budget", 18, 2),
    ("oe_finance_budget", "revised_budget", 18, 2),
    ("oe_finance_budget", "committed", 18, 2),
    ("oe_finance_budget", "actual", 18, 2),
    ("oe_finance_budget", "forecast_final", 18, 2),
    # Change orders
    ("oe_changeorders_order", "cost_impact", 18, 2),
    ("oe_changeorders_order", "contractor_amount", 18, 2),
    ("oe_changeorders_order", "engineer_amount", 18, 2),
    ("oe_changeorders_order", "approved_amount", 18, 2),
    ("oe_changeorders_item", "original_quantity", 18, 6),
    ("oe_changeorders_item", "new_quantity", 18, 6),
    ("oe_changeorders_item", "original_rate", 18, 6),
    ("oe_changeorders_item", "new_rate", 18, 6),
    ("oe_changeorders_item", "cost_delta", 18, 2),
]


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        # SQLite / other: no-op. MoneyType uses VARCHAR(50) on those.
        return

    for table, column, precision, scale in _MONEY_COLUMNS:
        # USING clause lets Postgres cast the existing VARCHAR row by row.
        # NULLIF handles empty strings that sometimes slip in from legacy
        # import paths; they become NULL rather than blowing up the cast.
        op.execute(
            f'ALTER TABLE {table} '
            f'ALTER COLUMN {column} TYPE NUMERIC({precision}, {scale}) '
            f'USING NULLIF({column}, \'\')::NUMERIC({precision}, {scale})'
        )


def downgrade() -> None:
    if not _is_postgres():
        return

    for table, column, _precision, _scale in _MONEY_COLUMNS:
        op.execute(
            f'ALTER TABLE {table} '
            f'ALTER COLUMN {column} TYPE VARCHAR(50) '
            f'USING {column}::TEXT'
        )
