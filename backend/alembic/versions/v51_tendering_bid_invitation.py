# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""tendering - bidder price-entry links.

One new table, ``oe_tendering_bid_invitation`` (model ``TenderBidInvitation``):
one row per personal link that lets an invited firm price a tender package
through the web app without an account. Only the sha256 of the link token is
stored. The row keeps the firm's draft unit prices until it submits, and the
id of the ``oe_tendering_bid`` row its submission wrote.

This one does NOT need running by hand. It adds a table and nothing else, and
``Base.metadata.create_all`` creates every table the models declare that the
database does not have yet, so a running install that boots the new code gets
the table from the model without an upgrade. The revision exists so that an
install that walks the chain with ``alembic upgrade head`` ends up with exactly
the same table, constraints and indexes: the names below are the ones the
metadata naming convention in ``app.database`` produces.

Inspector-guarded, so a re-run on a database that already has the table, or a
downgrade on one that never got it, changes nothing.

Revision ID: v51_tendering_bid_invitation
Revises: v50_ru_resource_index_tables
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v51_tendering_bid_invitation"
down_revision: Union[str, Sequence[str], None] = "v50_ru_resource_index_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_tendering_bid_invitation"
_GUID = sa.String(36)


def upgrade() -> None:
    """Create the bidder-link table with its foreign keys and indexes."""
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", _GUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("package_id", _GUID, nullable=False),
        sa.Column("recipient_id", sa.String(64), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("draft_saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bid_id", _GUID, nullable=True),
        sa.Column("draft", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{_TABLE}"),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["oe_tendering_package.id"],
            name=f"fk_{_TABLE}_package_id_oe_tendering_package",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["bid_id"],
            ["oe_tendering_bid.id"],
            name=f"fk_{_TABLE}_bid_id_oe_tendering_bid",
            ondelete="SET NULL",
        ),
    )
    op.create_index(f"ix_{_TABLE}_package_id", _TABLE, ["package_id"])
    op.create_index(f"ix_{_TABLE}_recipient_id", _TABLE, ["recipient_id"])
    op.create_index(f"ix_{_TABLE}_token_hash", _TABLE, ["token_hash"], unique=True)


def downgrade() -> None:
    """Drop the table. Every bidder link and unsent draft is lost with it."""
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_TABLE)
