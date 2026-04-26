"""v2.8.0 — 4D module: EAC schedule links + progress entries (Section 6 MVP).

Adds two new tables and two optional cost columns on the existing activity
table to back the 4D module described in §6 of the EAC implementation spec:

* ``oe_schedule_activity.cost_planned``  — Numeric, nullable.
* ``oe_schedule_activity.cost_actual``   — Numeric, nullable.
* ``oe_schedule_eac_link``               — link between an activity and an
                                           EAC rule or inline predicate.
* ``oe_schedule_progress_entry``         — append-only progress history with
                                           geolocation / device / photo refs.

The model loader's ``Base.metadata.create_all`` already lays down the new
tables on a fresh install, so this migration is only required when stepping
forwards from an older deployed schema. Both ``upgrade`` and ``downgrade``
are guarded by ``inspector`` checks so re-running the migration on an already
migrated DB is a no-op.

Revision ID: v280_4d_schedule_eac
Revises: v270_position_version_column
Create Date: 2026-04-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "v280_4d_schedule_eac"
down_revision: Union[str, Sequence[str], None] = "v270_position_version_column"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(
    inspector: sa.engine.reflection.Inspector, table: str, column: str
) -> bool:
    if not _has_table(inspector, table):
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    """Add 4D module tables + cost columns on the activity table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── 1. cost_planned / cost_actual on Activity ─────────────────────
    if _has_table(inspector, "oe_schedule_activity"):
        with op.batch_alter_table("oe_schedule_activity") as batch_op:
            if not _has_column(inspector, "oe_schedule_activity", "cost_planned"):
                batch_op.add_column(
                    sa.Column("cost_planned", sa.Numeric(20, 4), nullable=True)
                )
            if not _has_column(inspector, "oe_schedule_activity", "cost_actual"):
                batch_op.add_column(
                    sa.Column("cost_actual", sa.Numeric(20, 4), nullable=True)
                )

    # ── 2. oe_schedule_eac_link ───────────────────────────────────────
    if not _has_table(inspector, "oe_schedule_eac_link"):
        op.create_table(
            "oe_schedule_eac_link",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "task_id",
                sa.String(length=36),
                sa.ForeignKey(
                    "oe_schedule_activity.id", ondelete="CASCADE"
                ),
                nullable=False,
            ),
            sa.Column("rule_id", sa.String(length=36), nullable=True),
            sa.Column("predicate_json", sa.JSON(), nullable=True),
            sa.Column(
                "mode",
                sa.String(length=32),
                nullable=False,
                server_default="partial_match",
            ),
            sa.Column(
                "matched_element_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("last_resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "(rule_id IS NOT NULL) OR (predicate_json IS NOT NULL)",
                name="ck_eac_schedule_link_rule_or_predicate",
            ),
        )
        op.create_index(
            "ix_eac_schedule_link_task",
            "oe_schedule_eac_link",
            ["task_id"],
        )
        op.create_index(
            "ix_eac_schedule_link_rule",
            "oe_schedule_eac_link",
            ["rule_id"],
        )

    # ── 3. oe_schedule_progress_entry ─────────────────────────────────
    if not _has_table(inspector, "oe_schedule_progress_entry"):
        op.create_table(
            "oe_schedule_progress_entry",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "task_id",
                sa.String(length=36),
                sa.ForeignKey(
                    "oe_schedule_activity.id", ondelete="CASCADE"
                ),
                nullable=False,
            ),
            sa.Column(
                "recorded_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("recorded_by_user_id", sa.String(length=36), nullable=True),
            sa.Column(
                "progress_percent",
                sa.Numeric(6, 3),
                nullable=False,
                server_default="0",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "photo_attachment_ids",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column("geolocation", sa.JSON(), nullable=True),
            sa.Column(
                "device",
                sa.String(length=16),
                nullable=False,
                server_default="desktop",
            ),
            sa.Column("actual_start_date", sa.String(length=20), nullable=True),
            sa.Column("actual_finish_date", sa.String(length=20), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_schedule_progress_entry_task_recorded",
            "oe_schedule_progress_entry",
            ["task_id", "recorded_at"],
        )


def downgrade() -> None:
    """Drop the 4D-specific tables and cost columns."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "oe_schedule_progress_entry"):
        op.drop_index(
            "ix_schedule_progress_entry_task_recorded",
            table_name="oe_schedule_progress_entry",
        )
        op.drop_table("oe_schedule_progress_entry")

    if _has_table(inspector, "oe_schedule_eac_link"):
        op.drop_index("ix_eac_schedule_link_rule", table_name="oe_schedule_eac_link")
        op.drop_index("ix_eac_schedule_link_task", table_name="oe_schedule_eac_link")
        op.drop_table("oe_schedule_eac_link")

    if _has_table(inspector, "oe_schedule_activity"):
        with op.batch_alter_table("oe_schedule_activity") as batch_op:
            if _has_column(inspector, "oe_schedule_activity", "cost_actual"):
                batch_op.drop_column("cost_actual")
            if _has_column(inspector, "oe_schedule_activity", "cost_planned"):
                batch_op.drop_column("cost_planned")
