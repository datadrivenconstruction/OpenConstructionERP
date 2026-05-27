# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3-P10 — match search log: user-feedback + envelope-context columns.

Per MAPPING_PROCESS.md §10 the search-log row must capture not only the
search inputs / outputs (covered by v2934) but also the **user
feedback**: which rank did the operator pick, and the rate_code they
ended up with. Without this signal the §10 alerts can't fire (no way
to compute "user_picked_rank > 4 for >20% of requests").

Three additional envelope-context columns let analytics queries answer
"recall by ifc_class" or "p95 latency by source_type" without the
3-table JOIN that the v2934 schema otherwise forced.

Adds (all nullable, defaults preserve existing rows untouched):

* ``picked_rank``       — 1-based index of the confirmed candidate
                          inside the original results list.
* ``picked_rate_code``  — the rate_code the user actually accepted.
* ``picked_at``         — when the confirmation landed (UTC).
* ``source_type``       — ``"bim"`` / ``"dwg"`` / ``"boq"`` / ``"text"``
                          / ``"image"`` / ``"pdf"``.
* ``ifc_class``         — ``"IfcWall"`` / ``"IfcSlab"`` / etc. (NULL
                          for non-BIM sources).
* ``country``           — region head pinned for the search (e.g. ``"DE"``,
                          ``"RU"``) — derived from catalog_id at write
                          time so the analytics query doesn't need to
                          re-derive on every row.

Idempotent — re-applying on an already-migrated DB skips columns and
indexes that already exist.

Revision ID: v2936_match_search_log_feedback
Revises: v2935_match_session_stage
Create Date: 2026-05-10
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2936_match_search_log_feedback"
down_revision: Union[str, Sequence[str], None] = "v2935_match_session_stage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_match_elements_search_log"

_NEW_COLUMNS = (
    ("picked_rank", sa.Integer(), True),
    ("picked_rate_code", sa.String(64), True),
    ("picked_at", sa.DateTime(timezone=True), True),
    ("source_type", sa.String(32), True),
    ("ifc_class", sa.String(64), True),
    ("country", sa.String(16), True),
)

_NEW_INDEXES = (
    ("ix_match_search_log_picked_rank", ("picked_rank",)),
    ("ix_match_search_log_source_type", ("source_type",)),
    ("ix_match_search_log_country_time", ("country", "created_at")),
)


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    column: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    index: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        # v2934 must have run — bail out cleanly so a corrupt
        # migration chain doesn't half-apply.
        return

    for col_name, col_type, nullable in _NEW_COLUMNS:
        if not _has_column(inspector, _TABLE, col_name):
            op.add_column(_TABLE, sa.Column(col_name, col_type, nullable=nullable))

    # Inspector cache is stale after ALTER TABLE — re-inspect.
    inspector = sa.inspect(bind)

    for ix_name, ix_cols in _NEW_INDEXES:
        if not _has_index(inspector, _TABLE, ix_name):
            op.create_index(ix_name, _TABLE, list(ix_cols))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        return

    for ix_name, _cols in _NEW_INDEXES:
        if _has_index(inspector, _TABLE, ix_name):
            op.drop_index(ix_name, table_name=_TABLE)

    for col_name, _col_type, _nullable in _NEW_COLUMNS:
        if _has_column(inspector, _TABLE, col_name):
            op.drop_column(_TABLE, col_name)
