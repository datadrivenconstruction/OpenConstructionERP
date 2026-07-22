# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Approval-route system presets: add a stable ``system_key`` column.

The approval-routes module now seeds a small library of tenant-wide review
presets on startup (see ``app.modules.approval_routes.seed``). Each preset needs
a stable identifier so the seed is idempotent (re-running never duplicates a
preset) and the API can flag a route as a read-only platform preset.

This adds a nullable ``system_key`` VARCHAR(64) to ``oe_approval_routes_route``
plus a plain unique index on it. The column is NULL for every user-created
route, and PostgreSQL treats NULLs as distinct in a unique index, so ordinary
routes never collide; only the seeded presets carry a value and each value is
unique.

Every step is inspector-guarded and idempotent, so a re-run - or a database the
embedded runtime already reconciled through ``postgres_auto_migrate`` (which
adds missing model columns and plain indexes on stamped installs that never run
this migration) - is a no-op. PostgreSQL-only. Chained after
v3251_takeoff_source_unique to keep a single linear head.

Revision ID: v3252_approval_route_system_key
Revises: v3251_takeoff_source_unique
Create Date: 2026-07-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v3252_approval_route_system_key"
down_revision = "v3251_takeoff_source_unique"
branch_labels = None
depends_on = None

_ROUTE = "oe_approval_routes_route"
_COLUMN = "system_key"
_INDEX = "uq_approval_route_system_key"


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in insp.get_columns(table))


def _has_index(table: str, name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(ix.get("name") == name for ix in insp.get_indexes(table))


def upgrade() -> None:
    """Add the nullable ``system_key`` column and its unique index."""
    if not _has_table(_ROUTE):
        return
    if not _has_column(_ROUTE, _COLUMN):
        op.add_column(_ROUTE, sa.Column(_COLUMN, sa.String(length=64), nullable=True))
    if not _has_index(_ROUTE, _INDEX):
        op.create_index(_INDEX, _ROUTE, [_COLUMN], unique=True)


def downgrade() -> None:
    """Drop the unique index and the ``system_key`` column."""
    if _has_table(_ROUTE) and _has_index(_ROUTE, _INDEX):
        op.drop_index(_INDEX, table_name=_ROUTE)
    if _has_table(_ROUTE) and _has_column(_ROUTE, _COLUMN):
        op.drop_column(_ROUTE, _COLUMN)
