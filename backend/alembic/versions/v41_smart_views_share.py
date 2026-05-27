# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Smart Views — share-by-link token column.

Adds a single nullable ``share_token`` column to ``oe_smart_view`` plus
a partial-unique index (where ``share_token IS NOT NULL``) so revoked
views can simply NULL the column without colliding with each other.

This migration is strictly-additive — no data is rewritten, no existing
column is touched. Chained after ``v41_clash_ai_triage`` so the alembic
graph keeps a single linear tip.

Idempotent — inspector-guarded so re-runs on a partially-migrated DB
skip already-present column / index. SQLite supports partial unique
indexes from 3.8+, which is well below our minimum (we ship 3.37+).

Revision ID: v41_smart_views_share
Revises: v41_clash_ai_triage
Create Date: 2026-05-21
"""

from __future__ import annotations

import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v41_smart_views_share"
down_revision: Union[str, Sequence[str], None] = "v41_clash_ai_triage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Hardened identifier allow-list (security audit 2026-05-24 #3).
# Every identifier interpolated into a raw-SQL string in this migration
# must pass ``_safe_ident`` — a conservative regex match for the SQL
# identifier grammar. A future copy-paste that swaps the module-level
# constants below for a function arg will fail at module import time, not
# at SQL parse, so the "fragile f-string" pattern can't silently grow
# into an injection vector.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(name: str) -> str:
    """Return ``name`` unchanged if it's a valid SQL identifier, else raise."""
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name


# Module-level identifiers — never derived from a function argument or
# inspector lookup; guard pre-validated below so the f-strings below are
# proven safe at import time, not just at the next CI run.
_TABLE = _safe_ident("oe_smart_view")
_COLUMN = _safe_ident("share_token")
_INDEX = _safe_ident("ix_smart_view_share_token")


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(inspector: sa.engine.reflection.Inspector, table: str, column: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, index: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def upgrade() -> None:
    """Add ``share_token`` + its partial-unique index (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        # Parent migration hasn't run yet — nothing to upgrade. The
        # ordering enforced by ``down_revision`` should prevent this in
        # practice; we degrade silently so a re-run after a manual fix
        # is non-destructive.
        return

    if not _has_column(inspector, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, sa.String(length=255), nullable=True),
        )

    # Re-inspect for the index (we just added the column so the cached
    # inspector view of the table is stale).
    inspector = sa.inspect(bind)
    if not _has_index(inspector, _TABLE, _INDEX):
        # Partial unique index — Postgres + SQLite both honour the
        # ``where=`` predicate, so a NULL token does not collide.
        try:
            op.create_index(
                _INDEX,
                _TABLE,
                [_COLUMN],
                unique=True,
                sqlite_where=sa.text(f"{_COLUMN} IS NOT NULL"),
                postgresql_where=sa.text(f"{_COLUMN} IS NOT NULL"),
            )
        except sa.exc.OperationalError:
            # A partial re-run already left the index in place.
            pass


def downgrade() -> None:
    """Drop the index and the column."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, _TABLE, _INDEX):
        try:
            op.drop_index(_INDEX, table_name=_TABLE)
        except sa.exc.OperationalError:
            pass
    if _has_column(inspector, _TABLE, _COLUMN):
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.drop_column(_COLUMN)
