# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""tendering:​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ bidder clarification questions and published answers

Creates ``oe_tendering_clarification``: one row per bidder question on a tender
package, with the answer published to all bidders without the asker's name and
the addendum it was promoted into. Addenda, BOQ revisions and acknowledgements
stay in the package ``metadata`` JSON store, so no existing row changes.

Revision ID: v3327_tender_clarifications
Revises: vw01_wip_report_periods
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v3327_tender_clarifications"
down_revision: str | Sequence[str] | None = "vw01_wip_report_periods"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_tendering_clarification"


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _TABLE in tables:
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "package_id",
            sa.String(36),
            sa.ForeignKey("oe_tendering_package.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("recipient_id", sa.String(64), nullable=True),
        sa.Column("asked_by_email", sa.String(255), nullable=False, server_default=""),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_by", sa.String(36), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("addendum_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(f"ix_{_TABLE}_package_id", _TABLE, ["package_id"])


def downgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_TABLE)
