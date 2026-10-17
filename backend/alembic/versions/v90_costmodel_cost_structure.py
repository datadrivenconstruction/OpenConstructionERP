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

The backfill turns the flat trees ``generate_from_boq`` used to write into trees. Within one project and
one standard of a code shape the platform nests (DIN 276 digits, NRM dots, MasterFormat groups, UniFormat
letters) an account without a parent is placed under the most specific other account of the same project
and standard that covers its code, so ``330`` goes under ``300`` when both exist. A custom or unnamed
standard is left as it is: its parents are whatever the user set. Every account then gets its level from
its parent chain. ``title`` takes the existing name when the name is more than the code; when the name is
just the code, the title comes from the shipped code list of that standard, or stays empty.

Schema steps are inspector-guarded, so a database whose tables ``create_all`` already built reaches this
revision and only runs the backfill, which is idempotent: it fills parents that are empty and titles that
are empty, and recomputes levels. Installs that are stamped rather than upgraded MUST run this revision
(``alembic upgrade head``) to get the backfill; without it the service still works, because every reader
falls back to the name for an empty title and recomputes levels from the parent links, but the old flat
trees stay flat until the spine is regenerated from the bill.

Revision ID: v90_costmodel_cost_structure
Revises: v89_costmodel_cost_control
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.db_types import MoneyType
from app.database import GUID

revision: str = "v90_costmodel_cost_structure"
down_revision: str | Sequence[str] | None = "v89_costmodel_cost_control"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACCT = "oe_costmodel_control_account"
_LIST = "oe_costmodel_code_list"
_ALLOC = "oe_costmodel_position_allocation"

#: Standards whose codes nest by their shape, so a parent can be read off the code.
_SHAPE_STANDARDS = frozenset({"din276", "nrm", "masterformat", "uniformat"})


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
    """Parents from code shape, levels from parents, titles from names or the shipped lists."""
    from app.core.code_lists import get_code_list, parent_for, same_code

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
    if not rows:
        return
    parent_of = {r.id: r.parent_id for r in rows}
    updates: dict[object, dict[str, object]] = {}

    groups: dict[tuple[object, str], list[sa.Row]] = {}
    for r in rows:
        std = (r.classification_standard or "").strip().lower()
        if std in _SHAPE_STANDARDS:
            groups.setdefault((r.project_id, std), []).append(r)
    for members in groups.values():
        by_code = {m.code: m.id for m in members}
        codes = list(by_code)
        for m in members:
            if m.parent_id is not None:
                continue
            parent_code = parent_for(m.code, codes)
            if parent_code is not None:
                parent_of[m.id] = by_code[parent_code]
                updates.setdefault(m.id, {})["parent_id"] = by_code[parent_code]

    for r in rows:
        depth, current, seen = 1, parent_of.get(r.id), {r.id}
        while current is not None and current not in seen and current in parent_of:
            seen.add(current)
            depth += 1
            current = parent_of.get(current)
        if r.level != depth:
            updates.setdefault(r.id, {})["level"] = depth
        if not (r.title or "").strip():
            name = (r.name or "").strip()
            title = ""
            if name and not same_code(name, r.code):
                title = name
            else:
                code_list = get_code_list((r.classification_standard or "").strip().lower())
                entry = code_list.find(r.code) if code_list is not None else None
                title = entry.title if entry is not None else ""
            if title:
                updates.setdefault(r.id, {})["title"] = title[:255]

    # boot-repair: gap - nests the flat accounts of the shipped standards by code and copies their titles; the boot heal adds the four columns empty, so on an install that never runs alembic the old accounts stay flat (level 1, no title) until someone sets their parents, while every account created afterwards is nested
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
