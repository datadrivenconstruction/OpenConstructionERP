"""v2.6.0 — Project: fx_rates + default_vat_rate + custom_units (RFC 37, Issues #88/#89/#93).

Adds three columns to ``oe_projects_project`` so a project can carry:

* ``fx_rates`` — JSON list of additional currencies + decimal-string rates to
  ``Project.currency`` (the base). Empty list means single-currency.
* ``default_vat_rate`` — per-project VAT override that takes priority over
  the regional template at BOQ creation. NULL → use regional default.
* ``custom_units`` — JSON list of unit codes that aren't in the canonical
  frontend list. Project-scoped catalog.

All columns are nullable / default-empty so existing rows survive the
migration unchanged. Inspector-guarded so re-running the migration on an
already migrated DB is a no-op (matches the v260b pattern).

Revision ID: v260c_project_fx_rates_vat
Revises: v260b_eac_run_spool_idempotency
Create Date: 2026-04-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "v260c_project_fx_rates_vat"
down_revision: Union[str, Sequence[str], None] = "v260b_eac_run_spool_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_projects_project"
_FX_COL = "fx_rates"
_VAT_COL = "default_vat_rate"
_UNITS_COL = "custom_units"


def _has_column(inspector: sa.engine.reflection.Inspector, table: str, col: str) -> bool:
    return col in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _TABLE not in inspector.get_table_names():
        # Skip silently when the project table doesn't exist on this DB
        # (e.g. fresh service that creates tables via Base.metadata at
        # boot, not via alembic). Raising here would brick every future
        # `alembic upgrade head` even though the running service is fine.
        import logging
        logging.getLogger("alembic").warning(
            "v260c skipped: %s missing — Base.metadata.create_all() handles it at boot",
            _TABLE,
        )
        return

    if not _has_column(inspector, _TABLE, _FX_COL):
        op.add_column(
            _TABLE,
            sa.Column(
                _FX_COL,
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
        )

    if not _has_column(inspector, _TABLE, _VAT_COL):
        op.add_column(
            _TABLE,
            sa.Column(_VAT_COL, sa.String(length=10), nullable=True),
        )

    if not _has_column(inspector, _TABLE, _UNITS_COL):
        op.add_column(
            _TABLE,
            sa.Column(
                _UNITS_COL,
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _TABLE not in inspector.get_table_names():
        return

    if _has_column(inspector, _TABLE, _UNITS_COL):
        op.drop_column(_TABLE, _UNITS_COL)
    if _has_column(inspector, _TABLE, _VAT_COL):
        op.drop_column(_TABLE, _VAT_COL)
    if _has_column(inspector, _TABLE, _FX_COL):
        op.drop_column(_TABLE, _FX_COL)
