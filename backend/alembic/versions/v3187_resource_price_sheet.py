# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Resource price sheet (makes coefficient bases calculable).

Several CWICR bases ship the full labour / material / machine breakdown of every
work item as NORM QUANTITIES but carry no prices, because they are priced
regionally (Vietnam Dinh Muc, Indonesia AHSP). For those bases a work item's
rate cannot be computed until someone supplies local resource prices. This
migration adds the schema that holds those prices:

    oe_resource_price - one editable unit price per resource per region.
                        A work item's rate is then
                        ``sum(component.quantity x unit_price)`` over its
                        components. Priced bases seed their observed unit prices
                        here on import (``source = cwicr_import``); a user edits
                        any row (``source = user``) and re-prices the region.

Codeless bases (empty ``resource_code``) key on ``resource_key`` = a normalized
resource name, so the sheet works uniformly for coded and codeless bases. Each
region keeps at most one active price per resource (the unique constraint).
``unit_price`` is a String(50) Decimal-as-string like every other money column
in the schema.

The embedded-PostgreSQL runtime materialises this table via ``create_all`` at
startup, so the migration is for external-PostgreSQL deployments that manage
schema with Alembic. Every step is inspector-guarded, so a re-run (or a DB the
runtime already auto-created) is a no-op. Additive: no existing table is touched.
GUID columns are VARCHAR(36) (the app.database.GUID TypeDecorator impl).
PostgreSQL-only, no SQLite shims.

Revision ID: v3187_resource_price_sheet
Revises: v3186_payroll_deductions_net
Create Date: 2026-07-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v3187_resource_price_sheet"
down_revision = "v3186_payroll_deductions_net"
branch_labels = None
depends_on = None

_TABLE = "oe_resource_price"


def _has_table(name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return name in insp.get_table_names()


def upgrade() -> None:
    if _has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        # GUID columns are stored as VARCHAR(36) (see app.database.GUID).
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("region", sa.String(length=50), nullable=False),
        sa.Column("resource_key", sa.String(length=300), nullable=False),
        sa.Column("resource_code", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("resource_name", sa.String(length=300), nullable=False),
        sa.Column("resource_type", sa.String(length=30), nullable=False, server_default="material"),
        sa.Column("unit", sa.String(length=30), nullable=False, server_default=""),
        sa.Column("unit_price", sa.String(length=50), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default=""),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="cwicr_import"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("region", "resource_key", name="uq_oe_resource_price_region_key"),
    )
    op.create_index(op.f("ix_oe_resource_price_region"), _TABLE, ["region"])
    op.create_index("ix_oe_resource_price_region_active", _TABLE, ["region", "is_active"])


def downgrade() -> None:
    if _has_table(_TABLE):
        op.drop_table(_TABLE)
