# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""costmodel - the cost line travels down the chain: bid, contract, change, invoice.

One new table and five columns, no data rewrite:

* ``oe_costmodel_line_allocation``: one share of a downstream line (bid line, contract line, order item,
  invoice line) on a cost line, inherited from a bill position split over several cost lines. A row on a
  single cost line has no rows here and keeps naming its line in its own ``cost_line_id``.
* ``oe_bid_management_line_item.cost_line_id``: the scope line's cost line, copied from the position.
* ``oe_contracts_contract.cost_line_id``: the contract's own account, for a lump-sum contract with no
  bill behind it and as the default of its lines, change items and invoice lines.
* ``oe_changeorders_item.cost_line_id`` and ``cost_line_source``: the account of a change order item and
  where it came from (the schedule line it changes, the bill position, the contract, or a person).
* ``oe_finance_invoice_item.contract_line_id``: the schedule line an invoice line bills.

Existing rows keep their links as they are; nothing is backfilled, because which account an old award
line belongs to is the user's answer, not this revision's. Cost control lists those rows in its suspense
buckets, where one action takes the account from the bill for every row that can inherit one.

Every step is inspector-guarded, so a database whose tables ``create_all`` already built reaches this
revision without error.

Revision ID: v93_costmodel_cost_inheritance
Revises: v92_costmodel_cost_structure
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.db_types import MoneyType
from app.database import GUID

revision: str = "v93_costmodel_cost_inheritance"
down_revision: str | Sequence[str] | None = "v92_costmodel_cost_structure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LINE_ALLOC = "oe_costmodel_line_allocation"

#: ``(table, column, type factory, index name or None)`` for every plain column this revision adds.
_COLUMNS: tuple[tuple[str, str, object, str | None], ...] = (
    ("oe_bid_management_line_item", "cost_line_id", GUID, "ix_oe_bid_management_line_item_cost_line_id"),
    ("oe_contracts_contract", "cost_line_id", GUID, "ix_oe_contracts_contract_cost_line_id"),
    ("oe_changeorders_item", "cost_line_id", GUID, "ix_oe_changeorders_item_cost_line_id"),
    ("oe_changeorders_item", "cost_line_source", lambda: sa.String(length=20), None),
    ("oe_finance_invoice_item", "contract_line_id", GUID, "ix_oe_finance_invoice_item_contract_line_id"),
)


def _columns(bind: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _indexes(bind: sa.engine.Connection, table: str) -> set[str]:
    return {ix["name"] for ix in sa.inspect(bind).get_indexes(table)}


def _add_columns(bind: sa.engine.Connection) -> None:
    tables = set(sa.inspect(bind).get_table_names())
    for table, column, type_factory, index in _COLUMNS:
        if table not in tables:
            continue
        if column not in _columns(bind, table):
            op.add_column(table, sa.Column(column, type_factory(), nullable=True))  # type: ignore[operator]
        if index is not None and index not in _indexes(bind, table):
            op.create_index(index, table, [column])


def _create_line_allocation(bind: sa.engine.Connection) -> None:
    if _LINE_ALLOC not in sa.inspect(bind).get_table_names():
        op.create_table(
            _LINE_ALLOC,
            sa.Column("id", GUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column(
                "project_id",
                GUID(),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE", name="fk_costmodel_line_alloc_project"),
                nullable=False,
            ),
            sa.Column("source_type", sa.String(length=30), nullable=False),
            sa.Column("source_id", GUID(), nullable=False),
            sa.Column(
                "cost_line_id",
                GUID(),
                sa.ForeignKey(
                    "oe_costmodel_cost_line.id", ondelete="CASCADE", name="fk_costmodel_line_alloc_cost_line"
                ),
                nullable=False,
            ),
            sa.Column("share", MoneyType(20, 6), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_oe_costmodel_line_allocation"),
            sa.UniqueConstraint("source_type", "source_id", "cost_line_id", name="uq_costmodel_line_alloc_source_line"),
        )
    existing = _indexes(bind, _LINE_ALLOC)
    for name, cols in (
        ("ix_oe_costmodel_line_allocation_project_id", ["project_id"]),
        ("ix_oe_costmodel_line_allocation_cost_line_id", ["cost_line_id"]),
        ("ix_costmodel_line_alloc_source", ["source_type", "source_id"]),
    ):
        if name not in existing:
            op.create_index(name, _LINE_ALLOC, cols)


def upgrade() -> None:
    """Create the allocation table and add the five columns."""
    bind = op.get_bind()
    _create_line_allocation(bind)
    _add_columns(bind)


def downgrade() -> None:
    """Drop the five columns and the allocation table."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table, column, _type_factory, index in reversed(_COLUMNS):
        if table not in tables or column not in _columns(bind, table):
            continue
        if index is not None and index in _indexes(bind, table):
            op.drop_index(index, table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column(column)
    if _LINE_ALLOC in tables:
        op.drop_table(_LINE_ALLOC)
