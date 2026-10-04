# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""price_index - resource-index values and overhead/profit norms.

Two new tables for pricing a Russian estimate by the resource-index method:

* ``oe_price_index_resource_index`` (model ``ResourceIndexValue``) - one index
  per region, quarter and resource group (workers' wages, machine operation,
  machine operators' wages, materials), with the letter it came from and a
  flag for the platform's sample rows.
* ``oe_price_index_overhead_norm`` (model ``WorkTypeOverheadNorm``) - overheads
  and estimated profit as percentages of the wage fund, per type of work.

This one does NOT need running by hand. It adds tables and nothing else, and
``Base.metadata.create_all`` creates every table the models declare that the
database does not have yet, so a running install that boots the new code gets
both tables from the models without an upgrade. The revision exists so that an
install that walks the chain with ``alembic upgrade head`` ends up with exactly
the same tables, constraints and indexes: the names below are the ones the
metadata naming convention in ``app.database`` produces.

Inspector-guarded, so a re-run on a database that already has a table, or a
downgrade on one that never got it, changes nothing.

Revision ID: v50_ru_resource_index_tables
Revises: v49_boq_change_flag
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v50_ru_resource_index_tables"
down_revision: Union[str, Sequence[str], None] = "v49_boq_change_flag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_TABLE = "oe_price_index_resource_index"
_NORM_TABLE = "oe_price_index_overhead_norm"
_GUID = sa.String(36)


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    """Create both tables with their constraints and indexes."""
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if _INDEX_TABLE not in existing:
        op.create_table(
            _INDEX_TABLE,
            *_timestamps(),
            sa.Column("region_code", sa.String(64), nullable=False, server_default=""),
            sa.Column("quarter", sa.String(7), nullable=False, server_default=""),
            sa.Column("resource_group", sa.String(32), nullable=False, server_default=""),
            sa.Column("index_value", sa.Numeric(18, 6), nullable=False, server_default="1"),
            sa.Column("source", sa.Text(), nullable=False, server_default=""),
            sa.Column("is_sample", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.PrimaryKeyConstraint("id", name=f"pk_{_INDEX_TABLE}"),
            sa.UniqueConstraint(
                "region_code",
                "quarter",
                "resource_group",
                name="uq_price_index_resource_index_key",
            ),
        )
        op.create_index(f"ix_{_INDEX_TABLE}_region_code", _INDEX_TABLE, ["region_code"])

    if _NORM_TABLE not in existing:
        op.create_table(
            _NORM_TABLE,
            *_timestamps(),
            sa.Column("work_type_code", sa.String(64), nullable=False, server_default=""),
            sa.Column("label", sa.String(255), nullable=False, server_default=""),
            sa.Column("nr_pct", sa.Numeric(9, 4), nullable=False, server_default="0"),
            sa.Column("sp_pct", sa.Numeric(9, 4), nullable=False, server_default="0"),
            sa.Column("source", sa.Text(), nullable=False, server_default=""),
            sa.Column("is_sample", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.PrimaryKeyConstraint("id", name=f"pk_{_NORM_TABLE}"),
        )
        op.create_index(f"ix_{_NORM_TABLE}_work_type_code", _NORM_TABLE, ["work_type_code"], unique=True)


def downgrade() -> None:
    """Drop both tables. Entered indices and norms are lost with them."""
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (_NORM_TABLE, _INDEX_TABLE):
        if table in existing:
            op.drop_table(table)
