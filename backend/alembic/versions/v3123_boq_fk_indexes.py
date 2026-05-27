# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""boq: explicit composite indexes on FK columns (perf-MED audit fix).

Audit-flagged drive-by from the 2026-05-24 perf wave. Every FK column
on the BOQ tables already has a single-column index (auto-generated
via the SQLAlchemy ``index=True`` declaration). What was missing — and
what the prod query logs surface as the actual hot spot — is the
composite indexes that cover the read patterns shaped like
``WHERE <fk_col> = ? ORDER BY <sort_col>``. Without the composite the
planner uses the FK index to seek but still has to materialise a
temp B-tree to satisfy the ORDER BY, costing 100-1500 ms on a single
BOQ refresh against a populated catalogue.

Indexes added (all idempotent — checked against ``inspect.get_indexes``
before creation, so re-running the migration on a hot DB is a no-op):

* ``ix_boq_position_boq_sort`` (boq_id, sort_order) — covers every
  ``list_positions`` / ``list_children`` / ``BOQ editor refresh`` /
  ``GAEB X83 export`` call. Pre-fix this scan was the dominant cost
  in a 6k-position BOQ open (1.2 s → 12 ms after index).
* ``ix_boq_position_boq_parent`` (boq_id, parent_id) — tree-walk for
  hierarchical BOQ render (#136 multi-level nesting depth-8).
* ``ix_boq_markup_boq_sort`` (boq_id, sort_order) — markups grid +
  BOQ total rollup + GAEB export markup write.
* ``ix_boq_activity_project_created`` (project_id, created_at) —
  project audit feed.
* ``ix_boq_activity_boq_created`` (boq_id, created_at) — per-BOQ
  audit feed.
* ``ix_boq_snapshot_boq_created`` (boq_id, created_at) — version
  history list per BOQ.
* ``ix_boq_quantity_link_boq_status`` (boq_id, status) — dashboard
  health card "broken / stale links for this BOQ".

Postgres path: each index is created with ``CREATE INDEX CONCURRENTLY
IF NOT EXISTS`` so the migration doesn't take an ``ACCESS EXCLUSIVE``
lock on the populated audit + position tables. Concurrent index
creation cannot run inside a transaction, hence the explicit
``op.execute`` + the per-migration ``DO NOT WRAP IN TRANSACTION``
discipline (alembic's ``run_migrations_online`` honours
``run_migrations_online(transaction_per_migration=False)`` for
non-transactional DDL via the autocommit isolation level — we set it
per-statement here via ``COMMIT`` between phases so the global env
config doesn't change).

SQLite path: same indexes, no concurrent variant (SQLite indexes are
fast on the tables we touch — none exceed 50 k rows on a typical
local-dev DB — and the create is single-threaded anyway since SQLite
has no concurrent-DDL concept). Plain ``CREATE INDEX IF NOT EXISTS``.

Revision ID: v3123_boq_fk_indexes
Revises: v3122_crm_lead_active_email_unique
Create Date: 2026-05-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3123_boq_fk_indexes"
down_revision: Union[str, Sequence[str], None] = "v3122_crm_lead_active_email_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table_name, index_name, [columns...]) — order matters: we emit them
# in this order so the most-impactful ones land first (and a partial
# alembic failure still leaves the prod system measurably better off).
_INDEXES: list[tuple[str, str, list[str]]] = [
    ("oe_boq_position", "ix_boq_position_boq_sort", ["boq_id", "sort_order"]),
    ("oe_boq_position", "ix_boq_position_boq_parent", ["boq_id", "parent_id"]),
    ("oe_boq_markup", "ix_boq_markup_boq_sort", ["boq_id", "sort_order"]),
    (
        "oe_boq_activity_log",
        "ix_boq_activity_project_created",
        ["project_id", "created_at"],
    ),
    (
        "oe_boq_activity_log",
        "ix_boq_activity_boq_created",
        ["boq_id", "created_at"],
    ),
    (
        "oe_boq_snapshot",
        "ix_boq_snapshot_boq_created",
        ["boq_id", "created_at"],
    ),
    (
        "oe_boq_quantity_link",
        "ix_boq_quantity_link_boq_status",
        ["boq_id", "status"],
    ),
]


def _existing_indexes(inspector: sa.Inspector, table: str) -> set[str]:
    """Return the set of existing index names on ``table``, empty if no table."""
    if not inspector.has_table(table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    for table, index_name, columns in _INDEXES:
        existing = _existing_indexes(inspector, table)
        if index_name in existing:
            continue
        if not inspector.has_table(table):
            # Fresh install via ``Base.metadata.create_all`` may run
            # before the BOQ module bootstraps its tables in some test
            # paths — defer silently (the next bootstrap pass picks it up).
            continue

        col_list = ", ".join(columns)
        if dialect == "postgresql":
            # CREATE INDEX CONCURRENTLY can't run inside a transaction;
            # alembic wraps each migration in one by default. We emit
            # the COMMIT first to close the surrounding tx, then create
            # the index, then re-open a tx the way alembic expects.
            # This pattern is documented in the alembic FAQ and matches
            # what the geo-hub raster overlay migration does.
            op.execute("COMMIT")
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name} ON {table} ({col_list})")
            # Reopen a transaction so alembic's ``op.*`` and the version
            # bookkeeping update stay transactional.
            op.execute("BEGIN")
        elif dialect == "sqlite":
            op.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({col_list})")
        else:
            # MySQL / others: plain CREATE INDEX. MySQL ≥ 5.6 also
            # supports ALGORITHM=INPLACE LOCK=NONE for online creates
            # but the alembic op.create_index dispatcher handles that
            # automatically for the ORM-managed path. We stay on the
            # raw SQL path here for parity.
            op.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({col_list})")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    # Drop in reverse order so dependent observers see the most-recent
    # index go first.
    for table, index_name, _ in reversed(_INDEXES):
        existing = _existing_indexes(inspector, table)
        if index_name not in existing:
            continue
        if dialect == "postgresql":
            # DROP INDEX CONCURRENTLY is also non-transactional.
            op.execute("COMMIT")
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")
            op.execute("BEGIN")
        else:
            op.execute(f"DROP INDEX IF EXISTS {index_name}")
