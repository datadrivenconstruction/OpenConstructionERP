# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""subcontractors - levy catalogue, subcontract deduction terms, firm locations, favourites.

Creates ``oe_subcontractors_levy_catalogue``, ``oe_subcontractors_subcontract_terms``,
``oe_subcontractors_subcontract_levy``, ``oe_subcontractors_firm_location`` and
``oe_subcontractors_favourite``. New tables only, no data rewrite. Inspector-guarded,
so a database whose tables ``create_all`` already built is a no-op.

Revision ID: awl_subcontract_levies
Revises: vcrm01_deal_activities
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "awl_subcontract_levies"
down_revision: str | Sequence[str] | None = "vcrm01_deal_activities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CAT = "oe_subcontractors_levy_catalogue"
_TERMS = "oe_subcontractors_subcontract_terms"
_LEVY = "oe_subcontractors_subcontract_levy"
_LOC = "oe_subcontractors_firm_location"
_FAV = "oe_subcontractors_favourite"
_SUB = "oe_subcontractors_subcontractor"
_AGR = "oe_subcontractors_agreement"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def upgrade() -> None:
    have = _tables()
    if _CAT not in have:
        op.create_table(
            _CAT,
            *_base(),
            sa.Column("code", sa.String(60), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("basis", sa.String(20), nullable=False, server_default="percent"),
            sa.Column("default_percent", sa.Numeric(7, 3), nullable=True),
            sa.Column("default_fixed_amount", sa.Numeric(18, 2), nullable=True),
            sa.Column("applies_at", sa.String(20), nullable=False, server_default="each_invoice"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("source", sa.String(60), nullable=False, server_default="company"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.UniqueConstraint("code", name="uq_oe_subcontractors_levy_catalogue_code"),
        )
    if _TERMS not in have:
        op.create_table(
            _TERMS,
            *_base(),
            sa.Column("agreement_id", sa.String(36), sa.ForeignKey(f"{_AGR}.id", ondelete="CASCADE"), nullable=True),
            sa.Column("contract_id", sa.String(36), nullable=True),
            sa.Column("deduction_order", sa.String(30), nullable=False, server_default="levies_then_retention"),
            sa.Column("retention_cap_percent", sa.Numeric(7, 3), nullable=True),
            sa.Column("payment_discount_percent", sa.Numeric(7, 3), nullable=True),
            sa.Column("payment_discount_days", sa.Integer(), nullable=True),
            sa.Column("payment_discount_agreed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("agreement_id", name="uq_oe_subcontractors_subcontract_terms_agreement"),
            sa.UniqueConstraint("contract_id", name="uq_oe_subcontractors_subcontract_terms_contract"),
        )
    if _LEVY not in have:
        op.create_table(
            _LEVY,
            *_base(),
            sa.Column("terms_id", sa.String(36), sa.ForeignKey(f"{_TERMS}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("catalogue_id", sa.String(36), nullable=True),
            sa.Column("code", sa.String(60), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("basis", sa.String(20), nullable=False, server_default="percent"),
            sa.Column("rate_percent", sa.Numeric(7, 3), nullable=True),
            sa.Column("fixed_amount", sa.Numeric(18, 2), nullable=True),
            sa.Column("applies_at", sa.String(20), nullable=False, server_default="each_invoice"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("ix_oe_subcontractors_subcontract_levy_terms_id", _LEVY, ["terms_id"])
    if _LOC not in have:
        op.create_table(
            _LOC,
            *_base(),
            sa.Column(
                "subcontractor_id", sa.String(36), sa.ForeignKey(f"{_SUB}.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("lat", sa.Numeric(10, 7), nullable=False),
            sa.Column("lon", sa.Numeric(10, 7), nullable=False),
            sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("precision", sa.String(20), nullable=True),
            sa.Column("address_text", sa.String(500), nullable=True),
            sa.Column("located_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("subcontractor_id", name="uq_oe_subcontractors_firm_location_sub"),
        )
    if _FAV not in have:
        op.create_table(
            _FAV,
            *_base(),
            sa.Column(
                "subcontractor_id", sa.String(36), sa.ForeignKey(f"{_SUB}.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("trade", sa.String(120), nullable=False),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("subcontractor_id", "trade", name="uq_oe_subcontractors_favourite_trade"),
        )
        op.create_index("ix_oe_subcontractors_favourite_subcontractor_id", _FAV, ["subcontractor_id"])
        op.create_index("ix_oe_subcontractors_favourite_trade", _FAV, ["trade"])


def downgrade() -> None:
    have = _tables()
    if _FAV in have:
        op.drop_table(_FAV)
    if _LOC in have:
        op.drop_table(_LOC)
    if _LEVY in have:
        op.drop_table(_LEVY)
    if _TERMS in have:
        op.drop_table(_TERMS)
    if _CAT in have:
        op.drop_table(_CAT)
