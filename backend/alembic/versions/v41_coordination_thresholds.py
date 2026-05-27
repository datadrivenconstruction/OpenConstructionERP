# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Coordination Hub — per-project alert thresholds.

Adds one strictly-additive table:

* ``oe_coordination_threshold`` — one row per (project, metric) pair
  carrying ``warn_value`` / ``error_value`` / ``enabled``. Default
  rows are seeded lazily by the service the first time a project's
  thresholds endpoint is read, so this migration creates the SCHEMA
  only.

Idempotent — inspector-guarded so re-runs on a partially-migrated DB
skip the create. SQLite-safe.

Revision ID: v41_coordination_thresholds
Revises: v41_smart_views_share
Create Date: 2026-05-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v41_coordination_thresholds"
# Chain off the current tip ``v41_smart_views_share`` so the migration
# graph stays linear (``v41_smart_views_share`` itself branched off
# ``v41_clash_ai_triage`` for the share-by-link column). This new table
# is strictly additive and has no dependency on the smart-views table —
# we just append to whichever head exists.
down_revision: Union[str, Sequence[str], None] = "v41_smart_views_share"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_coordination_threshold"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _existing_index_names(
    inspector: sa.engine.reflection.Inspector,
    table: str,
) -> set[str]:
    if not _has_table(inspector, table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    """Create ``oe_coordination_threshold`` (idempotent)."""
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)
    inspector = sa.inspect(bind)

    if _has_table(inspector, _TABLE):
        return

    op.create_table(
        _TABLE,
        sa.Column("id", guid_type, primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            guid_type,
            sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column(
            "warn_value",
            sa.Numeric(18, 4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "error_value",
            sa.Numeric(18, 4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1") if is_sqlite else sa.text("true"),
        ),
        sa.UniqueConstraint(
            "project_id",
            "metric",
            name="uq_coordination_threshold_project_metric",
        ),
    )

    existing_ix = _existing_index_names(inspector, _TABLE)
    if "ix_coordination_threshold_project" not in existing_ix:
        try:
            op.create_index(
                "ix_coordination_threshold_project",
                _TABLE,
                ["project_id"],
            )
        except sa.exc.OperationalError:
            pass


def downgrade() -> None:
    """Drop ``oe_coordination_threshold`` and its indexes."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    existing_ix = _existing_index_names(inspector, _TABLE)
    if "ix_coordination_threshold_project" in existing_ix:
        try:
            op.drop_index(
                "ix_coordination_threshold_project",
                table_name=_TABLE,
            )
        except sa.exc.OperationalError:
            pass
    op.drop_table(_TABLE)
