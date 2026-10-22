# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""tendering - sealed submission mode: sealing and receipt tables.

Two new tables, nothing on an existing one, so an install that builds its
schema with ``create_all`` gets them on the next start and this revision only
matters where an operator walks the chain by hand. Each table is created only
when missing.

* ``oe_tendering_sealing``: one row per package tendered in sealed mode, with
  the two-person opening state and the opening itself.
* ``oe_tendering_bid_receipt``: UTC time stamp and SHA-256 of each accepted
  sealed submission.

Revision ID: v200_tendering_sealed_submissions
Revises: v199_subcontractor_contact_link
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v200_tendering_sealed_submissions"
down_revision: str | Sequence[str] | None = "v199_subcontractor_contact_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PACKAGE = "oe_tendering_package"
_BID = "oe_tendering_bid"
_SEALING = "oe_tendering_sealing"
_RECEIPT = "oe_tendering_bid_receipt"


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    """Create both tables when missing."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if _PACKAGE not in tables or _BID not in tables:
        return
    if _SEALING not in tables:
        op.create_table(
            _SEALING,
            *_base_columns(),
            sa.Column(
                "package_id",
                GUID(),
                sa.ForeignKey(
                    f"{_PACKAGE}.id", ondelete="CASCADE", name="fk_oe_tendering_sealing_package_id_oe_tendering_package"
                ),
                nullable=False,
            ),
            sa.Column("dual_opening", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("first_approver_id", sa.String(36), nullable=True),
            sa.Column("first_approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("opened_by", sa.String(36), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_oe_tendering_sealing"),
        )
        op.create_index("ix_oe_tendering_sealing_package_id", _SEALING, ["package_id"], unique=True)
    if _RECEIPT not in tables:
        op.create_table(
            _RECEIPT,
            *_base_columns(),
            sa.Column(
                "package_id",
                GUID(),
                sa.ForeignKey(
                    f"{_PACKAGE}.id",
                    ondelete="CASCADE",
                    name="fk_oe_tendering_bid_receipt_package_id_oe_tendering_package",
                ),
                nullable=False,
            ),
            sa.Column(
                "bid_id",
                GUID(),
                sa.ForeignKey(
                    f"{_BID}.id", ondelete="CASCADE", name="fk_oe_tendering_bid_receipt_bid_id_oe_tendering_bid"
                ),
                nullable=False,
            ),
            sa.Column("invitation_id", GUID(), nullable=True),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_oe_tendering_bid_receipt"),
        )
        op.create_index("ix_oe_tendering_bid_receipt_package_id", _RECEIPT, ["package_id"])
        op.create_index("ix_oe_tendering_bid_receipt_bid_id", _RECEIPT, ["bid_id"])


def downgrade() -> None:
    """Drop both tables when present."""
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _RECEIPT in tables:
        op.drop_table(_RECEIPT)
    if _SEALING in tables:
        op.drop_table(_SEALING)
