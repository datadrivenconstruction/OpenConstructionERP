# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""schedule_advanced — Last Planner System (LPS) + baselines.

Creates 10 tables backing the ``oe_schedule_advanced`` module:

* ``oe_schedule_advanced_master_schedule``
* ``oe_schedule_advanced_phase_plan``
* ``oe_schedule_advanced_look_ahead``
* ``oe_schedule_advanced_constraint``
* ``oe_schedule_advanced_weekly_plan``
* ``oe_schedule_advanced_commitment``
* ``oe_schedule_advanced_rnc``
* ``oe_schedule_advanced_baseline``
* ``oe_schedule_advanced_baseline_delta``
* ``oe_schedule_advanced_calendar``

Idempotent — guards against pre-existing tables / indexes from
``Base.metadata.create_all`` runs in tests. Each ``op.create_index``
is wrapped in ``try/except OperationalError`` per project convention.

Revision ID: v3021_schedule_advanced
Revises: v3017_carbon
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3021_schedule_advanced"
down_revision: Union[str, Sequence[str], None] = "v3020_variations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = (
    "oe_schedule_advanced_master_schedule",
    "oe_schedule_advanced_phase_plan",
    "oe_schedule_advanced_look_ahead",
    "oe_schedule_advanced_constraint",
    "oe_schedule_advanced_weekly_plan",
    "oe_schedule_advanced_commitment",
    "oe_schedule_advanced_rnc",
    "oe_schedule_advanced_baseline",
    "oe_schedule_advanced_baseline_delta",
    "oe_schedule_advanced_calendar",
)


# (index_name, table_name, columns, unique)
_INDEXES: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    (
        "ix_oe_schedule_advanced_master_schedule_project_id",
        "oe_schedule_advanced_master_schedule",
        ("project_id",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_phase_plan_master_id",
        "oe_schedule_advanced_phase_plan",
        ("master_schedule_id",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_look_ahead_master_id",
        "oe_schedule_advanced_look_ahead",
        ("master_schedule_id",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_constraint_look_ahead_id",
        "oe_schedule_advanced_constraint",
        ("look_ahead_id",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_constraint_task_ref",
        "oe_schedule_advanced_constraint",
        ("task_ref",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_constraint_status",
        "oe_schedule_advanced_constraint",
        ("status",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_weekly_plan_master_id",
        "oe_schedule_advanced_weekly_plan",
        ("master_schedule_id",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_weekly_plan_week_start",
        "oe_schedule_advanced_weekly_plan",
        ("week_start_date",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_commitment_week_plan_id",
        "oe_schedule_advanced_commitment",
        ("week_plan_id",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_commitment_task_ref",
        "oe_schedule_advanced_commitment",
        ("task_ref",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_commitment_status",
        "oe_schedule_advanced_commitment",
        ("status",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_rnc_commitment_id",
        "oe_schedule_advanced_rnc",
        ("commitment_id",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_rnc_category",
        "oe_schedule_advanced_rnc",
        ("category",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_baseline_master_id",
        "oe_schedule_advanced_baseline",
        ("master_schedule_id",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_baseline_delta_baseline_id",
        "oe_schedule_advanced_baseline_delta",
        ("baseline_id",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_baseline_delta_current_master_id",
        "oe_schedule_advanced_baseline_delta",
        ("current_master_id",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_baseline_delta_task_ref",
        "oe_schedule_advanced_baseline_delta",
        ("task_ref",),
        False,
    ),
    (
        "ix_oe_schedule_advanced_calendar_project_id",
        "oe_schedule_advanced_calendar",
        ("project_id",),
        False,
    ),
)


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


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
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    # ── MasterSchedule ─────────────────────────────────────────────────
    if not _has_table(inspector, "oe_schedule_advanced_master_schedule"):
        op.create_table(
            "oe_schedule_advanced_master_schedule",
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
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("baseline_date", sa.Date(), nullable=True),
            sa.Column("planned_start", sa.Date(), nullable=True),
            sa.Column("planned_finish", sa.Date(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
        )

    # ── PhasePlan ──────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_schedule_advanced_phase_plan"):
        op.create_table(
            "oe_schedule_advanced_phase_plan",
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
                "master_schedule_id",
                guid_type,
                sa.ForeignKey(
                    "oe_schedule_advanced_master_schedule.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("planned_start", sa.Date(), nullable=True),
            sa.Column("planned_finish", sa.Date(), nullable=True),
            sa.Column("milestone_target_id", guid_type, nullable=True),
            sa.Column(
                "pulled_status",
                sa.String(32),
                nullable=False,
                server_default="in_planning",
            ),
            sa.Column("pull_session_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "facilitator_id",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        )

    # ── LookAheadPlan ──────────────────────────────────────────────────
    if not _has_table(inspector, "oe_schedule_advanced_look_ahead"):
        op.create_table(
            "oe_schedule_advanced_look_ahead",
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
                "master_schedule_id",
                guid_type,
                sa.ForeignKey(
                    "oe_schedule_advanced_master_schedule.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column(
                "window_weeks",
                sa.Integer(),
                nullable=False,
                server_default="6",
            ),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="draft",
            ),
        )

    # ── Constraint ─────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_schedule_advanced_constraint"):
        op.create_table(
            "oe_schedule_advanced_constraint",
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
                "look_ahead_id",
                guid_type,
                sa.ForeignKey(
                    "oe_schedule_advanced_look_ahead.id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            ),
            sa.Column("task_ref", guid_type, nullable=False),
            sa.Column("constraint_type", sa.String(32), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "owner_user_id",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("target_clear_date", sa.Date(), nullable=True),
            sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "cleared_by",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="open",
            ),
        )

    # ── WeeklyWorkPlan ─────────────────────────────────────────────────
    if not _has_table(inspector, "oe_schedule_advanced_weekly_plan"):
        op.create_table(
            "oe_schedule_advanced_weekly_plan",
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
                "master_schedule_id",
                guid_type,
                sa.ForeignKey(
                    "oe_schedule_advanced_master_schedule.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("week_start_date", sa.Date(), nullable=False),
            sa.Column("week_end_date", sa.Date(), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "facilitator_id",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="draft",
            ),
            sa.Column("ppc_percent", sa.Numeric(5, 2), nullable=True),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        )

    # ── Commitment ─────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_schedule_advanced_commitment"):
        op.create_table(
            "oe_schedule_advanced_commitment",
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
                "week_plan_id",
                guid_type,
                sa.ForeignKey(
                    "oe_schedule_advanced_weekly_plan.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("task_ref", guid_type, nullable=False),
            sa.Column(
                "worker_or_crew",
                sa.String(255),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "promised_qty",
                sa.Numeric(15, 3),
                nullable=False,
                server_default="0",
            ),
            sa.Column("unit", sa.String(32), nullable=False, server_default=""),
            sa.Column("planned_start", sa.Date(), nullable=True),
            sa.Column("planned_finish", sa.Date(), nullable=True),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="planned",
            ),
            sa.Column(
                "made_by_user_id",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("made_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("actual_qty", sa.Numeric(15, 3), nullable=True),
        )

    # ── ReasonForNonCompletion ─────────────────────────────────────────
    if not _has_table(inspector, "oe_schedule_advanced_rnc"):
        op.create_table(
            "oe_schedule_advanced_rnc",
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
                "commitment_id",
                guid_type,
                sa.ForeignKey(
                    "oe_schedule_advanced_commitment.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("category", sa.String(32), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "recorded_by",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "root_cause_notes",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
        )

    # ── Baseline ───────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_schedule_advanced_baseline"):
        op.create_table(
            "oe_schedule_advanced_baseline",
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
                "master_schedule_id",
                guid_type,
                sa.ForeignKey(
                    "oe_schedule_advanced_master_schedule.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "captured_by",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("snapshot", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="active",
            ),
        )

    # ── BaselineDelta ──────────────────────────────────────────────────
    if not _has_table(inspector, "oe_schedule_advanced_baseline_delta"):
        op.create_table(
            "oe_schedule_advanced_baseline_delta",
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
                "baseline_id",
                guid_type,
                sa.ForeignKey(
                    "oe_schedule_advanced_baseline.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "current_master_id",
                guid_type,
                sa.ForeignKey(
                    "oe_schedule_advanced_master_schedule.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("task_ref", guid_type, nullable=False),
            sa.Column("planned_start_baseline", sa.Date(), nullable=True),
            sa.Column("planned_start_current", sa.Date(), nullable=True),
            sa.Column("planned_finish_baseline", sa.Date(), nullable=True),
            sa.Column("planned_finish_current", sa.Date(), nullable=True),
            sa.Column(
                "schedule_variance_days",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        )

    # ── Calendar ───────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_schedule_advanced_calendar"):
        op.create_table(
            "oe_schedule_advanced_calendar",
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
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column(
                "work_days",
                sa.JSON(),
                nullable=False,
                server_default="[0, 1, 2, 3, 4]",
            ),
            sa.Column(
                "work_hours_per_day",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="8",
            ),
            sa.Column("holidays", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column(
                "special_shifts",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "is_default",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )

    # ── Indexes (idempotent + try/except per project convention) ───────
    inspector = sa.inspect(bind)
    for name, table, cols, unique in _INDEXES:
        if not _has_table(inspector, table):
            continue
        if _has_index(inspector, table, name):
            continue
        try:
            op.create_index(name, table, list(cols), unique=unique)
        except sa.exc.OperationalError:
            # Race with concurrent migrator / already-created index outside the inspector cache
            pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop indexes first (best-effort)
    for name, table, _cols, _unique in _INDEXES:
        if _has_index(inspector, table, name):
            try:
                op.drop_index(name, table_name=table)
            except sa.exc.OperationalError:
                pass

    # Drop tables in FK-safe reverse order
    for table in (
        "oe_schedule_advanced_baseline_delta",
        "oe_schedule_advanced_baseline",
        "oe_schedule_advanced_rnc",
        "oe_schedule_advanced_commitment",
        "oe_schedule_advanced_weekly_plan",
        "oe_schedule_advanced_constraint",
        "oe_schedule_advanced_look_ahead",
        "oe_schedule_advanced_phase_plan",
        "oe_schedule_advanced_master_schedule",
        "oe_schedule_advanced_calendar",
    ):
        if _has_table(inspector, table):
            op.drop_table(table)
