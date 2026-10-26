# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""boq - estimate branches (variants) of a bill of quantities.

Additive only, no data rewrite:

* nullable column ``oe_boq_boq.branch_of_id`` (self foreign key, ``ON DELETE
  CASCADE``): the main estimate a bill is a branch of. NULL on every existing
  bill, so nothing leaves the bill register;
* new table ``oe_boq_branch``: where a branch forked from, its fork-point
  snapshot and whether it was merged.

Every step is inspector-guarded, so a database whose tables ``create_all``
already built reaches this revision and does nothing.

Revision ID: v201_boq_branches
Revises: v200_supplier_pricelists_discounts
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v201_boq_branches"
down_revision: str | Sequence[str] | None = "v200_supplier_pricelists_discounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BOQ = "oe_boq_boq"
_BRANCH = "oe_boq_branch"


def upgrade() -> None:
    """Add the column and the table when missing."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if _BOQ not in tables:
        return

    columns = {c["name"] for c in insp.get_columns(_BOQ)}
    if "branch_of_id" not in columns:
        op.add_column(_BOQ, sa.Column("branch_of_id", GUID(), nullable=True))
        op.create_index("ix_oe_boq_boq_branch_of_id", _BOQ, ["branch_of_id"])
        if bind.dialect.name != "sqlite":
            op.create_foreign_key(
                "fk_oe_boq_boq_branch_of_id", _BOQ, _BOQ, ["branch_of_id"], ["id"], ondelete="CASCADE"
            )

    if _BRANCH not in tables:
        op.create_table(
            _BRANCH,
            sa.Column("id", GUID(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("boq_id", GUID(), sa.ForeignKey(f"{_BOQ}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("main_boq_id", GUID(), sa.ForeignKey(f"{_BOQ}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("parent_boq_id", GUID(), sa.ForeignKey(f"{_BOQ}.id", ondelete="SET NULL"), nullable=True),
            sa.Column(
                "base_snapshot_id", GUID(), sa.ForeignKey("oe_boq_snapshot.id", ondelete="SET NULL"), nullable=True
            ),
            sa.Column("source_snapshot_id", GUID(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", GUID(), nullable=True),
            sa.Column("merged_at", sa.String(40), nullable=True),
            sa.Column("merged_by", GUID(), nullable=True),
            sa.Column("merge_snapshot_id", GUID(), nullable=True),
        )
        op.create_index("ix_oe_boq_branch_boq_id", _BRANCH, ["boq_id"], unique=True)
        op.create_index("ix_oe_boq_branch_main_boq_id", _BRANCH, ["main_boq_id"])
        op.create_index("ix_oe_boq_branch_parent_boq_id", _BRANCH, ["parent_boq_id"])


def downgrade() -> None:
    """Drop the table and the column."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if _BRANCH in tables:
        op.drop_table(_BRANCH)
    if _BOQ in tables and "branch_of_id" in {c["name"] for c in insp.get_columns(_BOQ)}:
        if bind.dialect.name != "sqlite":
            op.drop_constraint("fk_oe_boq_boq_branch_of_id", _BOQ, type_="foreignkey")
        op.drop_index("ix_oe_boq_boq_branch_of_id", table_name=_BOQ)
        op.drop_column(_BOQ, "branch_of_id")
