# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""FX rate cache and optional PPP factor tables.

The currency / FX module converts cost figures and estimates between currencies.
Live EUR-based reference rates come from the European Central Bank daily feed,
are cached here, and fall back to a small bundled seed when the network is
unavailable, so conversion never has a hard network dependency:

    oe_fx_rate    - one cached rate per (base_currency, currency): units of the
                    target currency per one unit of the base (EUR for the ECB
                    feed), plus the reference date it is effective for. A refresh
                    upserts by (base_currency, currency), so the table holds the
                    latest rate, not a history.
    oe_ppp_factor - optional World Bank purchasing-power-parity factor per
                    country (indicator PA.NUS.PPP, local currency units per
                    international dollar). The PPP path is optional and degrades
                    to an "unavailable" response when a factor is missing.

The embedded-PostgreSQL runtime materialises these tables via ``create_all`` at
startup, so this migration is for external-PostgreSQL deployments that manage
schema with Alembic. Every step is inspector-guarded, so a re-run (or a DB the
runtime already auto-created) is a no-op. Additive: no existing table is touched.
Rate/factor columns are Numeric(18, 6) ratios; timestamps default to now().
GUID columns are VARCHAR(36) (the app.database.GUID TypeDecorator impl).
PostgreSQL-only, no SQLite shims.

Revision ID: v3188_fx_rate_cache
Revises: v3187_resource_price_sheet
Create Date: 2026-07-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v3188_fx_rate_cache"
down_revision = "v3187_resource_price_sheet"
branch_labels = None
depends_on = None

_FX_TABLE = "oe_fx_rate"
_PPP_TABLE = "oe_ppp_factor"


def _has_table(name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return name in insp.get_table_names()


def upgrade() -> None:
    if not _has_table(_FX_TABLE):
        op.create_table(
            _FX_TABLE,
            # GUID columns are stored as VARCHAR(36) (see app.database.GUID).
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("base_currency", sa.String(length=3), nullable=False, server_default="EUR"),
            sa.Column("currency", sa.String(length=3), nullable=False),
            # Exchange rate is a ratio (units of currency per 1 base), not money.
            sa.Column("rate", sa.Numeric(18, 6), nullable=False, server_default="1"),
            sa.Column("rate_date", sa.Date(), nullable=False),
            sa.Column("source", sa.String(length=30), nullable=False, server_default="ecb"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("base_currency", "currency", name="uq_oe_fx_rate_base_currency"),
        )

    if not _has_table(_PPP_TABLE):
        op.create_table(
            _PPP_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("country_iso3", sa.String(length=3), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default=""),
            sa.Column("factor", sa.Numeric(18, 6), nullable=False, server_default="1"),
            sa.Column("year", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("source", sa.String(length=30), nullable=False, server_default="worldbank"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("country_iso3", name="uq_oe_ppp_factor_country"),
        )


def downgrade() -> None:
    if _has_table(_PPP_TABLE):
        op.drop_table(_PPP_TABLE)
    if _has_table(_FX_TABLE):
        op.drop_table(_FX_TABLE)
