# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""bi_dashboards — Module 20 (Wave 4): BI Dashboards & Reporting.

Creates nine tables for the read-only consumer module that produces
role-based dashboards, KPI library, report definitions, schedules and
threshold alerts.

The module never owns business data — it consumes from every other
module's tables via Python formula functions. The tables created here
are purely configuration + caches:

    oe_bi_dashboards_kpi_definition   — KPI catalog
    oe_bi_dashboards_dashboard        — dashboard config
    oe_bi_dashboards_widget           — widgets on dashboards
    oe_bi_dashboards_widget_snapshot  — cached widget values
    oe_bi_dashboards_report_definition  — saved reports
    oe_bi_dashboards_report_schedule  — scheduled report runs
    oe_bi_dashboards_alert_rule       — KPI threshold alerts
    oe_bi_dashboards_saved_filter     — reusable filter sets
    oe_bi_dashboards_kpi_value        — KPI value history (trends)

Idempotent — re-running on a DB where ``Base.metadata.create_all`` has
already created the tables is a no-op.

This migration chains off ``v2943_compliance_docs``, the most recent
shipped revision in this branch. If the planned ``v3025_supplier_catalogs``
ships first, this revision should be rebased onto it before merge.

Revision ID: v3026_bi_dashboards
Revises: v2943_compliance_docs
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3026_bi_dashboards"
down_revision: Union[str, Sequence[str], None] = "v3025_supplier_catalogs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BASE_COLS = (
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
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

    # ── KPI Definition ────────────────────────────────────────────
    if not _has_table(inspector, "oe_bi_dashboards_kpi_definition"):
        op.create_table(
            "oe_bi_dashboards_kpi_definition",
            sa.Column("id", guid_type, primary_key=True),
            *_BASE_COLS,
            sa.Column("code", sa.String(64), nullable=False, unique=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("formula_ref", sa.String(128), nullable=False),
            sa.Column("source_modules", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("unit", sa.String(32), nullable=False, server_default="ratio"),
            sa.Column("target_default", sa.Numeric(20, 6), nullable=True),
            sa.Column("aggregation", sa.String(16), nullable=False, server_default="last"),
            sa.Column("category", sa.String(32), nullable=False, server_default="operational"),
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default="0"),
        )

    # ── Dashboard ─────────────────────────────────────────────────
    if not _has_table(inspector, "oe_bi_dashboards_dashboard"):
        op.create_table(
            "oe_bi_dashboards_dashboard",
            sa.Column("id", guid_type, primary_key=True),
            *_BASE_COLS,
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("owner_user_id", guid_type, nullable=True),
            sa.Column("scope", sa.String(16), nullable=False, server_default="personal"),
            sa.Column("role_ref", sa.String(64), nullable=True),
            sa.Column("project_id", guid_type, nullable=True),
            sa.Column("layout_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("refresh_interval_seconds", sa.Integer(), nullable=False, server_default="300"),
        )

    # ── Widget ────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_bi_dashboards_widget"):
        op.create_table(
            "oe_bi_dashboards_widget",
            sa.Column("id", guid_type, primary_key=True),
            *_BASE_COLS,
            sa.Column(
                "dashboard_id",
                guid_type,
                sa.ForeignKey("oe_bi_dashboards_dashboard.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("widget_type", sa.String(32), nullable=False, server_default="kpi_card"),
            sa.Column("kpi_code", sa.String(64), nullable=True),
            sa.Column("config_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("position_x", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("position_y", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("width", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("height", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("order_seq", sa.Integer(), nullable=False, server_default="0"),
        )

    # ── Widget Snapshot ──────────────────────────────────────────
    if not _has_table(inspector, "oe_bi_dashboards_widget_snapshot"):
        op.create_table(
            "oe_bi_dashboards_widget_snapshot",
            sa.Column("id", guid_type, primary_key=True),
            *_BASE_COLS,
            sa.Column(
                "widget_id",
                guid_type,
                sa.ForeignKey("oe_bi_dashboards_widget.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("value_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        )

    # ── Report Definition ────────────────────────────────────────
    if not _has_table(inspector, "oe_bi_dashboards_report_definition"):
        op.create_table(
            "oe_bi_dashboards_report_definition",
            sa.Column("id", guid_type, primary_key=True),
            *_BASE_COLS,
            sa.Column("code", sa.String(64), nullable=False, unique=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("owner_user_id", guid_type, nullable=True),
            sa.Column("source_modules", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("query_spec_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("output_format", sa.String(16), nullable=False, server_default="pdf"),
            sa.Column("template_ref", sa.String(255), nullable=True),
            sa.Column("scope", sa.String(16), nullable=False, server_default="personal"),
        )

    # ── Report Schedule ──────────────────────────────────────────
    if not _has_table(inspector, "oe_bi_dashboards_report_schedule"):
        op.create_table(
            "oe_bi_dashboards_report_schedule",
            sa.Column("id", guid_type, primary_key=True),
            *_BASE_COLS,
            sa.Column(
                "report_definition_id",
                guid_type,
                sa.ForeignKey(
                    "oe_bi_dashboards_report_definition.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("frequency", sa.String(16), nullable=False, server_default="daily"),
            sa.Column("day_of_week", sa.Integer(), nullable=True),
            sa.Column("day_of_month", sa.Integer(), nullable=True),
            sa.Column("time_of_day", sa.String(5), nullable=False, server_default="08:00"),
            sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
            sa.Column("recipients_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("filter_overrides_json", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── Alert Rule ───────────────────────────────────────────────
    if not _has_table(inspector, "oe_bi_dashboards_alert_rule"):
        op.create_table(
            "oe_bi_dashboards_alert_rule",
            sa.Column("id", guid_type, primary_key=True),
            *_BASE_COLS,
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("kpi_code", sa.String(64), nullable=False),
            sa.Column("condition", sa.String(32), nullable=False, server_default="below"),
            sa.Column("threshold_value", sa.Numeric(20, 6), nullable=False),
            sa.Column("threshold_unit", sa.String(32), nullable=True),
            sa.Column("severity", sa.String(16), nullable=False, server_default="warning"),
            sa.Column("scope_project_id", guid_type, nullable=True),
            sa.Column("recipients_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("channels_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("throttle_seconds", sa.Integer(), nullable=False, server_default="3600"),
            sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        )

    # ── Saved Filter ─────────────────────────────────────────────
    if not _has_table(inspector, "oe_bi_dashboards_saved_filter"):
        op.create_table(
            "oe_bi_dashboards_saved_filter",
            sa.Column("id", guid_type, primary_key=True),
            *_BASE_COLS,
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("owner_user_id", guid_type, nullable=True),
            sa.Column("scope", sa.String(16), nullable=False, server_default="personal"),
            sa.Column("module", sa.String(64), nullable=False),
            sa.Column("filter_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
        )

    # ── KPI Value (history) ──────────────────────────────────────
    if not _has_table(inspector, "oe_bi_dashboards_kpi_value"):
        op.create_table(
            "oe_bi_dashboards_kpi_value",
            sa.Column("id", guid_type, primary_key=True),
            *_BASE_COLS,
            sa.Column("kpi_code", sa.String(64), nullable=False),
            sa.Column("project_id", guid_type, nullable=True),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("value", sa.Numeric(20, 6), nullable=False),
            sa.Column("unit", sa.String(32), nullable=False, server_default="ratio"),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "source_record_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    # ── Indexes (created after tables; cache is stale) ───────────
    inspector = sa.inspect(bind)
    index_specs: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
        ("ix_oe_bi_dashboards_kpi_definition_code", "oe_bi_dashboards_kpi_definition", ("code",), False),
        ("ix_oe_bi_dashboards_kpi_definition_category", "oe_bi_dashboards_kpi_definition", ("category",), False),
        ("ix_oe_bi_dashboards_dashboard_owner_user_id", "oe_bi_dashboards_dashboard", ("owner_user_id",), False),
        ("ix_oe_bi_dashboards_dashboard_scope", "oe_bi_dashboards_dashboard", ("scope",), False),
        ("ix_oe_bi_dashboards_dashboard_project_id", "oe_bi_dashboards_dashboard", ("project_id",), False),
        ("ix_oe_bi_dashboards_widget_dashboard_id", "oe_bi_dashboards_widget", ("dashboard_id",), False),
        ("ix_oe_bi_dashboards_widget_kpi_code", "oe_bi_dashboards_widget", ("kpi_code",), False),
        ("ix_oe_bi_dashboards_widget_snapshot_widget_id", "oe_bi_dashboards_widget_snapshot", ("widget_id",), False),
        (
            "ix_oe_bi_dashboards_widget_snapshot_valid_until",
            "oe_bi_dashboards_widget_snapshot",
            ("valid_until",),
            False,
        ),
        ("ix_oe_bi_dashboards_report_definition_code", "oe_bi_dashboards_report_definition", ("code",), False),
        (
            "ix_oe_bi_dashboards_report_definition_owner_user_id",
            "oe_bi_dashboards_report_definition",
            ("owner_user_id",),
            False,
        ),
        ("ix_oe_bi_dashboards_report_definition_scope", "oe_bi_dashboards_report_definition", ("scope",), False),
        (
            "ix_oe_bi_dashboards_report_schedule_report_definition_id",
            "oe_bi_dashboards_report_schedule",
            ("report_definition_id",),
            False,
        ),
        (
            "ix_oe_bi_dashboards_report_schedule_next_run_at",
            "oe_bi_dashboards_report_schedule",
            ("next_run_at",),
            False,
        ),
        ("ix_oe_bi_dashboards_alert_rule_kpi_code", "oe_bi_dashboards_alert_rule", ("kpi_code",), False),
        (
            "ix_oe_bi_dashboards_alert_rule_scope_project_id",
            "oe_bi_dashboards_alert_rule",
            ("scope_project_id",),
            False,
        ),
        ("ix_oe_bi_dashboards_saved_filter_owner_user_id", "oe_bi_dashboards_saved_filter", ("owner_user_id",), False),
        ("ix_oe_bi_dashboards_saved_filter_module", "oe_bi_dashboards_saved_filter", ("module",), False),
        ("ix_oe_bi_dashboards_kpi_value_kpi_code", "oe_bi_dashboards_kpi_value", ("kpi_code",), False),
        ("ix_oe_bi_dashboards_kpi_value_project_id", "oe_bi_dashboards_kpi_value", ("project_id",), False),
    )
    for name, table, cols, unique in index_specs:
        if _has_table(inspector, table) and not _has_index(inspector, table, name):
            op.create_index(name, table, list(cols), unique=unique)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Drop tables in reverse FK order
    for table in (
        "oe_bi_dashboards_kpi_value",
        "oe_bi_dashboards_saved_filter",
        "oe_bi_dashboards_alert_rule",
        "oe_bi_dashboards_widget_snapshot",
        "oe_bi_dashboards_report_schedule",
        "oe_bi_dashboards_report_definition",
        "oe_bi_dashboards_widget",
        "oe_bi_dashboards_dashboard",
        "oe_bi_dashboards_kpi_definition",
    ):
        if _has_table(inspector, table):
            op.drop_table(table)
