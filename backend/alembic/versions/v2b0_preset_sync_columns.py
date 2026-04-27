"""v2.11.0 — Dashboards: preset sync-status columns (T09).

Adds two columns to ``oe_dashboards_preset`` so the sync protocol
(``app.modules.dashboards.sync_protocol``) can persist its state:

* ``sync_status``        — ``'synced'`` / ``'stale'`` / ``'needs_review'``.
* ``last_sync_check_at`` — when the user last ran a sync-check.

Both columns are inspector-guarded so re-running on an already-migrated
DB is a no-op (matches the v260c / v280 / v290 / v2a0 style). The
default for ``sync_status`` is ``'synced'`` because every existing row
predates the protocol — first sync-check call will reclassify them.

Revision ID: v2b0_preset_sync_columns
Revises: v2a0_compliance_dsl_rules
Create Date: 2026-04-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2b0_preset_sync_columns"
down_revision: Union[str, Sequence[str], None] = "v2a0_compliance_dsl_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_dashboards_preset"
_SYNC_STATUS_COL = "sync_status"
_LAST_CHECK_COL = "last_sync_check_at"
_CHECK_CONSTRAINT = "ck_oe_dashboards_preset_sync_status"


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


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        # The base preset table hasn't been created yet — nothing to do
        # here (``v290_dashboards_presets`` will run before this and
        # bring the table; in the unlikely "skipped migrations" case we
        # bail rather than half-create).
        return

    if not _has_column(inspector, _TABLE, _SYNC_STATUS_COL):
        op.add_column(
            _TABLE,
            sa.Column(
                _SYNC_STATUS_COL,
                sa.String(length=32),
                nullable=False,
                server_default="synced",
            ),
        )

    if not _has_column(inspector, _TABLE, _LAST_CHECK_COL):
        op.add_column(
            _TABLE,
            sa.Column(
                _LAST_CHECK_COL,
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )

    # SQLite cannot ALTER TABLE ADD CONSTRAINT — the production target
    # is PostgreSQL, but we guard with the dialect check so dev / tests
    # on SQLite still apply cleanly.
    dialect = bind.dialect.name
    if dialect != "sqlite":
        existing_checks = {
            cc["name"] for cc in inspector.get_check_constraints(_TABLE)
        }
        if _CHECK_CONSTRAINT not in existing_checks:
            op.create_check_constraint(
                _CHECK_CONSTRAINT,
                _TABLE,
                f"{_SYNC_STATUS_COL} IN ('synced', 'stale', 'needs_review')",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        return

    dialect = bind.dialect.name
    if dialect != "sqlite":
        existing_checks = {
            cc["name"] for cc in inspector.get_check_constraints(_TABLE)
        }
        if _CHECK_CONSTRAINT in existing_checks:
            op.drop_constraint(
                _CHECK_CONSTRAINT, _TABLE, type_="check",
            )

    if _has_column(inspector, _TABLE, _LAST_CHECK_COL):
        op.drop_column(_TABLE, _LAST_CHECK_COL)
    if _has_column(inspector, _TABLE, _SYNC_STATUS_COL):
        op.drop_column(_TABLE, _SYNC_STATUS_COL)
