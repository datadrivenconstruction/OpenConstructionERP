# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""User-owned cost catalogs.

Adds ``oe_costs_catalog`` - the named, currency-bearing container behind the
"my own catalog of works and rates" feature - plus the bare (FK-less, by
platform convention) ``catalog_id`` column on ``oe_costs_item`` that links an
item to its owning catalog. Delete semantics (detach vs soft-delete) are
handled in the service layer, so no ON DELETE clause is needed.

The embedded PostgreSQL runtime materialises this via ``create_all`` (new
table) and the startup column auto-heal (new column), so this migration is
for external-PostgreSQL deployments that manage schema with Alembic. Every
step is guarded with a presence check so a re-run, or a DB the runtime
already auto-created, is a no-op. Additive and backfill-safe (existing items
read NULL = not in any catalog). PostgreSQL-only.

Revision ID: v3181_cost_catalogs
Revises: v3180_budget_line_earned_amount
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v3181_cost_catalogs"
down_revision = "v3180_budget_line_earned_amount"
branch_labels = None
depends_on = None

_CATALOG_TABLE = "oe_costs_catalog"
_ITEM_TABLE = "oe_costs_item"
_ITEM_COLUMN = "catalog_id"
_ITEM_INDEX = "ix_oe_costs_item_catalog_id"


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _has_index(table: str, index: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(ix["name"] == index for ix in insp.get_indexes(table))


def upgrade() -> None:
    if not _has_table(_CATALOG_TABLE):
        op.create_table(
            _CATALOG_TABLE,
            # GUID() stores as String(36); mirror the platform UUID column shape.
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Index("ix_oe_costs_catalog_created_by", "created_by"),
        )

    if not _has_column(_ITEM_TABLE, _ITEM_COLUMN):
        op.add_column(_ITEM_TABLE, sa.Column(_ITEM_COLUMN, sa.String(36), nullable=True))
    if not _has_index(_ITEM_TABLE, _ITEM_INDEX):
        op.create_index(_ITEM_INDEX, _ITEM_TABLE, [_ITEM_COLUMN])


def downgrade() -> None:
    if _has_index(_ITEM_TABLE, _ITEM_INDEX):
        op.drop_index(_ITEM_INDEX, table_name=_ITEM_TABLE)
    if _has_column(_ITEM_TABLE, _ITEM_COLUMN):
        op.drop_column(_ITEM_TABLE, _ITEM_COLUMN)
    if _has_table(_CATALOG_TABLE):
        op.drop_table(_CATALOG_TABLE)
