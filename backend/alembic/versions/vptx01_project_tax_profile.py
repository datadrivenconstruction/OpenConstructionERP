# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""project_tax - the per-project tax profile.

One new table, ``oe_project_tax_profile``: a project's tax method and the day
it was elected, the lock period, the bill standard edition, and the site and
home regions a place-of-supply prepayment is computed between. One row per
project at most.

Nothing existing changes. ``Base.metadata.create_all`` also creates the table
on a running install from the model; the migration is inspector-guarded, so a
re-run or a downgrade without the table changes nothing.

Revision ID: vptx01_project_tax_profile
Revises: vcc440_commercial_control
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "vptx01_project_tax_profile"
down_revision: Union[str, Sequence[str], None] = "vcc440_commercial_control"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_project_tax_profile"
_GUID = sa.String(36)


def upgrade() -> None:
    """Create the table."""
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", _GUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column("project_id", _GUID, nullable=False),
        sa.Column("tax_method", sa.String(20), nullable=False, server_default="general"),
        sa.Column("election_date", sa.Date(), nullable=True),
        sa.Column("lock_months", sa.Integer(), nullable=True),
        sa.Column("grandfathered", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("simplified_basis", sa.String(40), nullable=True),
        sa.Column("employer_supplied", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("taxpayer_size", sa.String(20), nullable=False, server_default="general"),
        sa.Column("permit_start_date", sa.Date(), nullable=True),
        sa.Column("contract_date", sa.Date(), nullable=True),
        sa.Column("tender_date", sa.Date(), nullable=True),
        sa.Column("standard_edition", sa.String(40), nullable=True),
        sa.Column("site_subdivision", sa.String(10), nullable=True),
        sa.Column("site_city", sa.String(100), nullable=True),
        sa.Column("home_subdivision", sa.String(10), nullable=True),
        sa.Column("home_city", sa.String(100), nullable=True),
        sa.Column("method_history", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{_TABLE}"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["oe_projects_project.id"],
            name=f"fk_{_TABLE}_project_id_oe_projects_project",
            ondelete="CASCADE",
        ),
    )
    op.create_index(f"ix_{_TABLE}_project_id", _TABLE, ["project_id"], unique=True)


def downgrade() -> None:
    """Drop the table."""
    if _TABLE not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.drop_index(f"ix_{_TABLE}_project_id", table_name=_TABLE)
    op.drop_table(_TABLE)
