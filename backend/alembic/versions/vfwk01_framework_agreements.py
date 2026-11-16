# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""framework agreements: price list, rate periods, condition adjustments

Additive new tables only, so a deploy that heals its schema at boot picks them up
without ``alembic upgrade``. The agreement and its call-off orders are rows of
``oe_contracts_contract`` (``contract_type`` framework / call_off), which needs no DDL.

Revision ID: vfwk01_framework_agreements
Revises: vbt01_boq_templates
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vfwk01_framework_agreements"
down_revision: str | Sequence[str] | None = "vbt01_boq_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ITEM = "oe_framework_rate_item"
_PERIOD = "oe_framework_rate_period"
_ADJ = "oe_framework_adjustment"
_CONTRACT = "oe_contracts_contract"


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "agreement_id",
            sa.String(36),
            sa.ForeignKey(f"{_CONTRACT}.id", ondelete="CASCADE"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if _ITEM not in existing:
        op.create_table(
            _ITEM,
            *_base_columns(),
            sa.Column("code", sa.String(80), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("unit", sa.String(20), nullable=False, server_default=""),
            sa.Column("base_rate", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("classification", sa.String(80), nullable=True),
            sa.Column("max_qty", sa.Numeric(18, 4), nullable=True),
            sa.Column("estimated_qty", sa.Numeric(18, 4), nullable=True),
            sa.Column("surcharge_flags", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("escalation_group", sa.String(40), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index(f"ix_{_ITEM}_agreement_id", _ITEM, ["agreement_id"])
        op.create_index("ix_framework_rate_item_agreement_code", _ITEM, ["agreement_id", "code"])
    if _PERIOD not in existing:
        op.create_table(
            _PERIOD,
            *_base_columns(),
            sa.Column("label", sa.String(80), nullable=False, server_default=""),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("method", sa.String(20), nullable=False, server_default="none"),
            sa.Column("template_code", sa.String(40), nullable=True),
            sa.Column("base_period", sa.String(7), nullable=True),
            sa.Column("fixed_price_until", sa.Date(), nullable=True),
            sa.Column("fixed_part", sa.Numeric(9, 6), nullable=True),
            sa.Column("fixed_factor", sa.Numeric(12, 6), nullable=True),
            sa.Column("series_refs", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("rate_overrides", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        )
        op.create_index(f"ix_{_PERIOD}_agreement_id", _PERIOD, ["agreement_id"])
    if _ADJ not in existing:
        op.create_table(
            _ADJ,
            *_base_columns(),
            sa.Column("code", sa.String(40), nullable=False),
            sa.Column("label", sa.String(255), nullable=False, server_default=""),
            sa.Column("kind", sa.String(20), nullable=False, server_default="multiplier"),
            sa.Column("value", sa.Numeric(12, 6), nullable=False, server_default="1"),
            sa.Column("scope", sa.String(20), nullable=False, server_default="all"),
            sa.Column("scope_items", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("scope_group", sa.String(40), nullable=True),
            sa.Column("condition", sa.String(60), nullable=False, server_default=""),
        )
        op.create_index(f"ix_{_ADJ}_agreement_id", _ADJ, ["agreement_id"])


def downgrade() -> None:
    for table in (_ADJ, _PERIOD, _ITEM):
        op.drop_table(table)
