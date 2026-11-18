# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""china_pack - the per-project provincial fee profile.

One new table, ``oe_china_pack_fee_profile``: the rates a person picked inside
a provincial fee programme, the zone, grade or class options, the bases they
set where the source leaves a base open, an optional schedule override, and
whether labour already includes social insurance. One row per project at most.

Nothing existing changes. ``Base.metadata.create_all`` also creates the table
on a running install from the model; the migration is inspector-guarded, so a
re-run or a downgrade without the table changes nothing.

Revision ID: vcnf01_china_fee_profile
Revises: vptx01_project_tax_profile
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "vcnf01_china_fee_profile"
down_revision: Union[str, Sequence[str], None] = "vptx01_project_tax_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_china_pack_fee_profile"
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
        sa.Column("schedule_key", sa.String(60), nullable=True),
        sa.Column("rates", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("options", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("bases", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("labour_includes_social_insurance", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("apply_labour_factor", sa.Boolean(), nullable=True),
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
