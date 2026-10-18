# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""costmodel - hierarchical cost structure, imported code lists, split allocations.

Four columns on ``oe_costmodel_control_account`` and two new tables:

* ``title`` (the account's own title, separate from its code), ``level`` (depth in the tree, 1 at the top),
  ``own_amount`` (money planned on the account itself, not broken down yet) and ``is_leaf_postable``
  (whether cost lines may be posted onto it).
* ``oe_costmodel_code_list``: a code list a user imported for one project, the dictionary a custom
  structure is built from.
* ``oe_costmodel_position_allocation``: one share of a bill position on a cost line, for a position split
  over more than one. A position on a single line keeps ``oe_boq_position.cost_line_id`` and needs no row.

The backfill turns the flat trees ``generate_from_boq`` used to write into trees, by the rule in
:mod:`app.modules.costmodel.structure_backfill`: within one project and one standard of a code shape the
platform nests (DIN 276 digits, NRM dots, MasterFormat groups, UniFormat letters), a group in which no account
has a parent or a title yet (the state an upgrade leaves it in) is nested by code, so ``330`` goes under ``300``
when both exist, and its titles come from the names or the shipped code list. A group someone already shaped,
and every custom or unnamed standard, keeps its parents. Every account then gets its level from its parent
chain.

Schema steps are inspector-guarded, so a database whose tables ``create_all`` already built reaches this
revision and only runs the backfill, which is idempotent. Installs that heal their schema at boot and stamp
head instead get the same backfill from the boot repair ``costmodel_structure_backfill``
(``app/modules/costmodel/repairs.py``), which calls the same planner on every start.

Revision ID: v92_costmodel_cost_structure
Revises: v91_requisition_line_supplier_dates
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.db_types import MoneyType
from app.database import GUID

revision: str = "v92_costmodel_cost_structure"
down_revision: str | Sequence[str] | None = "v91_requisition_line_supplier_dates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACCT = "oe_costmodel_control_account"
_LIST = "oe_costmodel_code_list"
_ALLOC = "oe_costmodel_position_allocation"


def _columns(bind: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _add_account_columns(bind: sa.engine.Connection) -> None:
    existing = _columns(bind, _ACCT)
    if "title" not in existing:
        op.add_column(_ACCT, sa.Column("title", sa.String(length=255), nullable=False, server_default=""))
    if "level" not in existing:
        op.add_column(_ACCT, sa.Column("level", sa.Integer(), nullable=False, server_default="1"))
    if "own_amount" not in existing:
        op.add_column(_ACCT, sa.Column("own_amount", MoneyType(), nullable=False, server_default="0"))
    if "is_leaf_postable" not in existing:
        op.add_column(
            _ACCT, sa.Column("is_leaf_postable", sa.Boolean(), nullable=False, server_default=sa.text("true"))
        )


def _create_code_list(bind: sa.engine.Connection) -> None:
    if _LIST not in sa.inspect(bind).get_table_names():
        op.create_table(
            _LIST,
            sa.Column("id", GUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column(
                "project_id",
                GUID(),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE", name="fk_costmodel_code_list_project"),
                nullable=False,
            ),
            sa.Column("key", sa.String(length=40), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("entries", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_oe_costmodel_code_list"),
            sa.UniqueConstraint("project_id", "key", name="uq_costmodel_code_list_project_key"),
        )
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes(_LIST)}
    if "ix_oe_costmodel_code_list_project_id" not in existing:
        op.create_index("ix_oe_costmodel_code_list_project_id", _LIST, ["project_id"])


def _create_allocation(bind: sa.engine.Connection) -> None:
    if _ALLOC not in sa.inspect(bind).get_table_names():
        op.create_table(
            _ALLOC,
            sa.Column("id", GUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column(
                "project_id",
                GUID(),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE", name="fk_costmodel_alloc_project"),
                nullable=False,
            ),
            sa.Column("boq_id", GUID(), nullable=False),
            sa.Column(
                "position_id",
                GUID(),
                sa.ForeignKey("oe_boq_position.id", ondelete="CASCADE", name="fk_costmodel_alloc_position"),
                nullable=False,
            ),
            sa.Column(
                "cost_line_id",
                GUID(),
                sa.ForeignKey("oe_costmodel_cost_line.id", ondelete="CASCADE", name="fk_costmodel_alloc_cost_line"),
                nullable=False,
            ),
            sa.Column("mode", sa.String(length=10), nullable=False, server_default="percent"),
            sa.Column("share", MoneyType(20, 6), nullable=False),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.PrimaryKeyConstraint("id", name="pk_oe_costmodel_position_allocation"),
            sa.UniqueConstraint("position_id", "cost_line_id", name="uq_costmodel_alloc_position_line"),
        )
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes(_ALLOC)}
    for name, cols in (
        ("ix_oe_costmodel_position_allocation_project_id", ["project_id"]),
        ("ix_oe_costmodel_position_allocation_position_id", ["position_id"]),
        ("ix_oe_costmodel_position_allocation_cost_line_id", ["cost_line_id"]),
        ("ix_costmodel_alloc_boq", ["boq_id"]),
    ):
        if name not in existing:
            op.create_index(name, _ALLOC, cols)


def _backfill(bind: sa.engine.Connection) -> None:
    """Parents from code shape, levels from parents, titles from names or the shipped lists.

    The decision lives in :func:`app.modules.costmodel.structure_backfill.plan_structure_backfill`,
    which the boot repair ``costmodel_structure_backfill`` calls too.
    """
    from app.modules.costmodel.structure_backfill import AccountRow, plan_structure_backfill

    acct = sa.table(
        _ACCT,
        sa.column("id", GUID()),
        sa.column("project_id", GUID()),
        sa.column("parent_id", GUID()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("title", sa.String()),
        sa.column("level", sa.Integer()),
        sa.column("classification_standard", sa.String()),
    )
    rows = bind.execute(
        sa.select(
            acct.c.id,
            acct.c.project_id,
            acct.c.parent_id,
            acct.c.code,
            acct.c.name,
            acct.c.title,
            acct.c.level,
            acct.c.classification_standard,
        )
    ).all()
    updates = plan_structure_backfill(
        AccountRow(
            id=r.id,
            project_id=r.project_id,
            parent_id=r.parent_id,
            code=r.code or "",
            name=r.name or "",
            title=r.title or "",
            level=int(r.level or 0),
            standard=r.classification_standard or "",
        )
        for r in rows
    )

    # boot-repair: registry=costmodel_structure_backfill
    # data-rewrite-ack: table=oe_costmodel_control_account growth=bounded rows=one row per cost account of a project's cost structure, a few dozen to a few hundred per project, so it tracks the number of projects rather than transaction history
    for account_id, values in updates.items():
        bind.execute(acct.update().where(acct.c.id == account_id).values(**values))


def upgrade() -> None:
    """Add the account columns, create the two tables, then backfill the trees."""
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if _ACCT in tables:
        _add_account_columns(bind)
    _create_code_list(bind)
    _create_allocation(bind)
    if _ACCT in sa.inspect(bind).get_table_names():
        _backfill(bind)


def downgrade() -> None:
    """Drop the two tables and the four columns. Parents the backfill set stay set."""
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if _ALLOC in tables:
        op.drop_table(_ALLOC)
    if _LIST in tables:
        op.drop_table(_LIST)
    if _ACCT in tables:
        existing = _columns(bind, _ACCT)
        drop = [c for c in ("is_leaf_postable", "own_amount", "level", "title") if c in existing]
        if drop:
            with op.batch_alter_table(_ACCT) as batch:
                for column in drop:
                    batch.drop_column(column)
