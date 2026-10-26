# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""boq - exchange fidelity reports.

Additive only: a new table ``oe_boq_exchange_report`` that keeps, per import
and per export of a bill, the list of what the file did not carry across
(truncated texts, rounded values, dropped attributes, markups the format
cannot hold). Inspector-guarded, so a database whose table ``create_all``
already built reaches this revision and does nothing.

Revision ID: v201_boq_exchange_report
Revises: v200_supplier_pricelists_discounts
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v201_boq_exchange_report"
down_revision: str | Sequence[str] | None = "v200_supplier_pricelists_discounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_boq_exchange_report"


def upgrade() -> None:
    """Create the report table when it is missing."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if _TABLE in tables or "oe_boq_boq" not in tables:
        return
    op.create_table(
        _TABLE,
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("boq_id", GUID(), sa.ForeignKey("oe_boq_boq.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "project_id",
            GUID(),
            sa.ForeignKey("oe_projects_project.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("format_id", sa.String(30), nullable=False),
        sa.Column("variant", sa.String(20), nullable=False, server_default=""),
        sa.Column("file_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("roundtrip", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_check", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("items", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_by", GUID(), sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index(f"ix_{_TABLE}_boq_id", _TABLE, ["boq_id"])
    op.create_index(f"ix_{_TABLE}_project_id", _TABLE, ["project_id"])
    op.create_index("ix_boq_exchange_report_boq_created", _TABLE, ["boq_id", "created_at"])


def downgrade() -> None:
    """Drop the report table."""
    bind = op.get_bind()
    if _TABLE in set(sa.inspect(bind).get_table_names()):
        op.drop_table(_TABLE)
