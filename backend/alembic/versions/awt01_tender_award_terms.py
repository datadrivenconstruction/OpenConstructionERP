# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""tendering - award terms and negotiation rounds.

Two new tables: ``oe_tendering_negotiation_round`` (one negotiated offer of a
bidder, numbered per bid, one of them marked final and approved) and
``oe_tendering_award_terms`` (the structured terms a package is awarded on:
discount, lump sum, retention and cap, payment discount and days).

Nothing existing changes. ``Base.metadata.create_all`` also creates both on a
running install from the models; the migration is inspector-guarded, so a
re-run or a downgrade without the tables changes nothing.

Revision ID: awt01_tender_award_terms
Revises: vcrm01_deal_activities
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "awt01_tender_award_terms"
down_revision: Union[str, Sequence[str], None] = "vcrm01_deal_activities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROUND = "oe_tendering_negotiation_round"
_TERMS = "oe_tendering_award_terms"
_GUID = sa.String(36)


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("id", _GUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
    ]


def upgrade() -> None:
    """Create the two tables."""
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if _ROUND not in existing:
        op.create_table(
            _ROUND,
            *_stamps(),
            sa.Column("package_id", _GUID, nullable=False),
            sa.Column("bid_id", _GUID, nullable=False),
            sa.Column("round_no", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("pricing_mode", sa.String(20), nullable=False, server_default="unit_price"),
            sa.Column("lines_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("lump_sum", sa.Numeric(18, 2), nullable=True),
            sa.Column("discount_percent", sa.Numeric(7, 4), nullable=False, server_default="0"),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("approved_by", sa.String(36), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("approval_verdict", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.PrimaryKeyConstraint("id", name=f"pk_{_ROUND}"),
            sa.ForeignKeyConstraint(
                ["package_id"], ["oe_tendering_package.id"], name=f"fk_{_ROUND}_package", ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["bid_id"], ["oe_tendering_bid.id"], name=f"fk_{_ROUND}_bid", ondelete="CASCADE"),
            sa.UniqueConstraint("bid_id", "round_no", name="uq_oe_tendering_negotiation_round_bid_no"),
        )
        op.create_index(f"ix_{_ROUND}_package_id", _ROUND, ["package_id"])
        op.create_index(f"ix_{_ROUND}_bid_id", _ROUND, ["bid_id"])
    if _TERMS not in existing:
        op.create_table(
            _TERMS,
            *_stamps(),
            sa.Column("package_id", _GUID, nullable=False),
            sa.Column("bid_id", _GUID, nullable=False),
            sa.Column("round_id", _GUID, nullable=True),
            sa.Column("discount_percent", sa.Numeric(7, 4), nullable=False, server_default="0"),
            sa.Column("lump_sum", sa.Numeric(18, 2), nullable=True),
            sa.Column("retention_percent", sa.Numeric(7, 4), nullable=True),
            sa.Column("retention_cap_percent", sa.Numeric(7, 4), nullable=True),
            sa.Column("payment_discount_percent", sa.Numeric(7, 4), nullable=True),
            sa.Column("payment_discount_days", sa.Integer(), nullable=True),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("updated_by", sa.String(36), nullable=True),
            sa.PrimaryKeyConstraint("id", name=f"pk_{_TERMS}"),
            sa.ForeignKeyConstraint(
                ["package_id"], ["oe_tendering_package.id"], name=f"fk_{_TERMS}_package", ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["bid_id"], ["oe_tendering_bid.id"], name=f"fk_{_TERMS}_bid", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["round_id"], [f"{_ROUND}.id"], name=f"fk_{_TERMS}_round", ondelete="SET NULL"),
        )
        op.create_index(f"ix_{_TERMS}_package_id", _TERMS, ["package_id"], unique=True)
        op.create_index(f"ix_{_TERMS}_bid_id", _TERMS, ["bid_id"])


def downgrade() -> None:
    """Drop the two tables when present."""
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (_TERMS, _ROUND):
        if table in existing:
            op.drop_table(table)
