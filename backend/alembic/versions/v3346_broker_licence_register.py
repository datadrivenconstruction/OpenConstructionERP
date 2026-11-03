"""Broker licence register.

Adds ``oe_property_dev_broker_licence``: one row per licence a broker holds
(authority code, number, validity window, status).

A fresh install gets the table from ``create_all``. The production deploy is
``create_all`` plus ``alembic stamp head``, which creates a new table but would
never run this file; a working install that is upgraded in place must run
``alembic upgrade``. Only a new table is added, so nothing else needs backfill.

Revision ID: v3346_broker_licence_register
Revises: v3345_einvoice_lifecycle
Create Date: 2026-11-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3346_broker_licence_register"
down_revision: Union[str, Sequence[str], None] = "v3345_einvoice_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_property_dev_broker_licence"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE in inspector.get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "broker_id",
            sa.String(36),
            sa.ForeignKey("oe_property_dev_broker.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("authority_code", sa.String(40), nullable=False, server_default=""),
        sa.Column("licence_number", sa.String(120), nullable=False, server_default=""),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.UniqueConstraint(
            "broker_id", "authority_code", "licence_number", name="uq_oe_property_dev_broker_licence_number"
        ),
    )
    op.create_index("ix_oe_property_dev_broker_licence_broker_id", _TABLE, ["broker_id"])
    op.create_index("ix_oe_property_dev_broker_licence_authority_code", _TABLE, ["authority_code"])
    op.create_index("ix_oe_property_dev_broker_licence_status", _TABLE, ["status"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE in inspector.get_table_names():
        op.drop_table(_TABLE)
