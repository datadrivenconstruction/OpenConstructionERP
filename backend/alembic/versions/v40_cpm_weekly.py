# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍CPM Slice 1: WeeklyCommitment table for Last-Planner percent-plan-complete.

Adds a single strictly-additive table
``oe_schedule_advanced_weekly_commitment`` that stores a per-activity,
per-week Last-Planner commitment record with auto-computed PPC. Used by
the new ``POST /schedule-advanced/{schedule_id}/commitments`` and
``GET /schedule-advanced/{schedule_id}/ppc`` endpoints.

Idempotent — inspector-guarded so re-runs on a partially migrated DB
skip already-present tables/indexes. SQLite-safe via GUID()→VARCHAR(36).

Revision ID: v40_cpm_weekly
Revises: v40_ai_agents
Create Date: 2026-05-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v40_cpm_weekly"
down_revision: Union[str, Sequence[str], None] = "v40_ai_agents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COMMIT_TABLE = "oe_schedule_advanced_weekly_commitment"


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
    """Create the weekly-commitment table + supporting indexes."""
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _COMMIT_TABLE):
        op.create_table(
            _COMMIT_TABLE,
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
            # Cross-module — no FK (oe_schedule_schedule lives in another module).
            sa.Column("schedule_id", guid_type, nullable=False),
            # Cross-module — no FK (oe_schedule_activity lives in another module).
            sa.Column("activity_id", guid_type, nullable=False),
            sa.Column("week_start", sa.Date(), nullable=False),
            sa.Column(
                "committed_by",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "planned_complete_pct",
                sa.Numeric(6, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "actual_complete_pct",
                sa.Numeric(6, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "ppc",
                sa.Numeric(6, 4),
                nullable=False,
                server_default="0",
            ),
        )

        existing_ix = _existing_index_names(inspector, _COMMIT_TABLE)
        for ix_name, cols in (
            ("ix_oe_sched_adv_weekly_commit_schedule", ["schedule_id"]),
            ("ix_oe_sched_adv_weekly_commit_activity", ["activity_id"]),
            ("ix_oe_sched_adv_weekly_commit_week", ["week_start"]),
        ):
            if ix_name not in existing_ix:
                try:
                    op.create_index(ix_name, _COMMIT_TABLE, cols)
                except sa.exc.OperationalError:
                    pass


def downgrade() -> None:
    """Drop the weekly-commitment table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _COMMIT_TABLE):
        existing_ix = _existing_index_names(inspector, _COMMIT_TABLE)
        for ix in (
            "ix_oe_sched_adv_weekly_commit_schedule",
            "ix_oe_sched_adv_weekly_commit_activity",
            "ix_oe_sched_adv_weekly_commit_week",
        ):
            if ix in existing_ix:
                try:
                    op.drop_index(ix, table_name=_COMMIT_TABLE)
                except sa.exc.OperationalError:
                    pass
        op.drop_table(_COMMIT_TABLE)
