"""variations -- Notices, VRs, VOs, site measurements, daywork, claims, final account.

Creates 11 tables under the ``oe_variations_*`` namespace for Module 14.

Idempotent: each ``op.create_table`` is gated by an inspector check, and
``op.create_index`` calls are wrapped in try/except for ``OperationalError``
so re-running on a DB where Base.metadata.create_all already executed is
a no-op.

Revision ID: v3020_variations
Revises: v3017_carbon
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3020_variations"
down_revision: Union[str, Sequence[str], None] = "v3019_bid_management"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES: tuple[str, ...] = (
    "oe_variations_notice",
    "oe_variations_request",
    "oe_variations_order",
    "oe_variations_cost_impact",
    "oe_variations_schedule_impact",
    "oe_variations_site_measurement",
    "oe_variations_daywork_sheet",
    "oe_variations_daywork_line",
    "oe_variations_disruption_claim",
    "oe_variations_eot_claim",
    "oe_variations_final_account",
)


# (index_name, table, columns, unique)
_INDEXES: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    ("ix_oe_variations_notice_project_id", "oe_variations_notice", ("project_id",), False),
    ("ix_oe_variations_notice_status", "oe_variations_notice", ("status",), False),
    ("ix_oe_variations_request_project_id", "oe_variations_request", ("project_id",), False),
    ("ix_oe_variations_request_notice_id", "oe_variations_request", ("notice_id",), False),
    ("ix_oe_variations_request_status", "oe_variations_request", ("status",), False),
    ("ix_oe_variations_order_project_id", "oe_variations_order", ("project_id",), False),
    ("ix_oe_variations_order_variation_request_id", "oe_variations_order", ("variation_request_id",), False),
    ("ix_oe_variations_order_status", "oe_variations_order", ("status",), False),
    ("ix_oe_variations_cost_impact_variation_order_id", "oe_variations_cost_impact", ("variation_order_id",), False),
    (
        "ix_oe_variations_schedule_impact_variation_order_id",
        "oe_variations_schedule_impact",
        ("variation_order_id",),
        False,
    ),
    ("ix_oe_variations_site_measurement_project_id", "oe_variations_site_measurement", ("project_id",), False),
    (
        "ix_oe_variations_site_measurement_variation_order_id",
        "oe_variations_site_measurement",
        ("variation_order_id",),
        False,
    ),
    ("ix_oe_variations_daywork_sheet_project_id", "oe_variations_daywork_sheet", ("project_id",), False),
    ("ix_oe_variations_daywork_sheet_status", "oe_variations_daywork_sheet", ("status",), False),
    ("ix_oe_variations_daywork_line_sheet_id", "oe_variations_daywork_line", ("sheet_id",), False),
    ("ix_oe_variations_disruption_claim_project_id", "oe_variations_disruption_claim", ("project_id",), False),
    ("ix_oe_variations_disruption_claim_status", "oe_variations_disruption_claim", ("status",), False),
    ("ix_oe_variations_eot_claim_project_id", "oe_variations_eot_claim", ("project_id",), False),
    ("ix_oe_variations_eot_claim_status", "oe_variations_eot_claim", ("status",), False),
    ("ix_oe_variations_final_account_project_id", "oe_variations_final_account", ("project_id",), False),
    ("ix_oe_variations_final_account_status", "oe_variations_final_account", ("status",), False),
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


def _money_type(is_sqlite: bool, scale: int = 4) -> sa.types.TypeEngine:
    # MoneyType maps to String(50) on SQLite, NUMERIC(18, scale) on PG.
    return sa.String(50) if is_sqlite else sa.Numeric(18, scale)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)
    money = _money_type(is_sqlite, 4)
    money6 = _money_type(is_sqlite, 6)

    # ── oe_variations_notice ──────────────────────────────────────────────
    if not _has_table(inspector, "oe_variations_notice"):
        op.create_table(
            "oe_variations_notice",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "project_id", guid_type, sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("title", sa.String(500), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("raised_at", sa.String(40), nullable=True),
            sa.Column("raised_by", sa.String(36), nullable=True),
            sa.Column("recipient_type", sa.String(40), nullable=False, server_default="owner"),
            sa.Column("recipient_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("target_response_date", sa.String(20), nullable=True),
            sa.Column("response_received_at", sa.String(40), nullable=True),
            sa.Column("response_summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(40), nullable=False, server_default="issued"),
            # Plain UUID, no FK.
            sa.Column("reference_change_order_id", guid_type, nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint("project_id", "code", name="uq_oe_variations_notice_project_code"),
        )

    # ── oe_variations_request ─────────────────────────────────────────────
    if not _has_table(inspector, "oe_variations_request"):
        op.create_table(
            "oe_variations_request",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "project_id", guid_type, sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column(
                "notice_id", guid_type, sa.ForeignKey("oe_variations_notice.id", ondelete="SET NULL"), nullable=True
            ),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("title", sa.String(500), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("requested_by", sa.String(36), nullable=True),
            sa.Column("requested_at", sa.String(40), nullable=True),
            sa.Column("classification", sa.String(40), nullable=False, server_default="scope_change"),
            sa.Column("urgency", sa.String(20), nullable=False, server_default="med"),
            sa.Column("estimated_cost_impact", money, nullable=False, server_default="0"),
            sa.Column("estimated_schedule_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
            sa.Column("submitted_at", sa.String(40), nullable=True),
            sa.Column("decision_at", sa.String(40), nullable=True),
            sa.Column("decision_notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("decided_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint("project_id", "code", name="uq_oe_variations_request_project_code"),
        )

    # ── oe_variations_order ───────────────────────────────────────────────
    if not _has_table(inspector, "oe_variations_order"):
        op.create_table(
            "oe_variations_order",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "project_id", guid_type, sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column(
                "variation_request_id",
                guid_type,
                sa.ForeignKey("oe_variations_request.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("title", sa.String(500), nullable=False, server_default=""),
            sa.Column("final_cost_impact", money, nullable=False, server_default="0"),
            sa.Column("final_schedule_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("agreed_at", sa.String(40), nullable=True),
            sa.Column("signed_by", sa.String(36), nullable=True),
            sa.Column("status", sa.String(40), nullable=False, server_default="issued"),
            # Plain UUID, no FK.
            sa.Column("reference_change_order_id", guid_type, nullable=True),
            sa.Column("implementation_started_at", sa.String(40), nullable=True),
            sa.Column("implementation_completed_at", sa.String(40), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint("project_id", "code", name="uq_oe_variations_order_project_code"),
        )

    # ── oe_variations_cost_impact ─────────────────────────────────────────
    if not _has_table(inspector, "oe_variations_cost_impact"):
        op.create_table(
            "oe_variations_cost_impact",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "variation_order_id",
                guid_type,
                sa.ForeignKey("oe_variations_order.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("category", sa.String(40), nullable=False, server_default="material"),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("quantity", money6, nullable=False, server_default="0"),
            sa.Column("unit", sa.String(20), nullable=False, server_default=""),
            sa.Column("unit_rate", money6, nullable=False, server_default="0"),
            sa.Column("total", money, nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("source", sa.String(40), nullable=False, server_default="manual"),
        )

    # ── oe_variations_schedule_impact ─────────────────────────────────────
    if not _has_table(inspector, "oe_variations_schedule_impact"):
        op.create_table(
            "oe_variations_schedule_impact",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "variation_order_id",
                guid_type,
                sa.ForeignKey("oe_variations_order.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("affected_activity_ref", sa.String(255), nullable=False, server_default=""),
            sa.Column("original_finish_date", sa.String(20), nullable=True),
            sa.Column("revised_finish_date", sa.String(20), nullable=True),
            sa.Column("days_added", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "is_critical_path",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0") if is_sqlite else sa.text("false"),
            ),
            sa.Column("justification", sa.Text(), nullable=False, server_default=""),
        )

    # ── oe_variations_site_measurement ────────────────────────────────────
    if not _has_table(inspector, "oe_variations_site_measurement"):
        op.create_table(
            "oe_variations_site_measurement",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "project_id", guid_type, sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("recorded_at", sa.String(40), nullable=True),
            sa.Column("recorded_by", sa.String(36), nullable=True),
            sa.Column("location", sa.String(500), nullable=False, server_default=""),
            sa.Column("item_description", sa.Text(), nullable=False, server_default=""),
            sa.Column("unit", sa.String(20), nullable=False, server_default=""),
            sa.Column("measured_quantity", money6, nullable=False, server_default="0"),
            sa.Column("agreed_with_owner_at", sa.String(40), nullable=True),
            sa.Column("owner_signature_ref", sa.String(255), nullable=False, server_default=""),
            sa.Column("photos", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            # Plain UUID, no FK to oe_contracts_*.
            sa.Column("contract_line_id", guid_type, nullable=True),
            sa.Column(
                "variation_order_id",
                guid_type,
                sa.ForeignKey("oe_variations_order.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    # ── oe_variations_daywork_sheet ───────────────────────────────────────
    if not _has_table(inspector, "oe_variations_daywork_sheet"):
        op.create_table(
            "oe_variations_daywork_sheet",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "project_id", guid_type, sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("sheet_number", sa.String(50), nullable=False),
            sa.Column("work_date", sa.String(20), nullable=True),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("total_amount", money, nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
            sa.Column("signed_by", sa.String(36), nullable=True),
            sa.Column("signed_at", sa.String(40), nullable=True),
            sa.Column("owner_signature_ref", sa.String(255), nullable=False, server_default=""),
            # Plain UUID, no FK.
            sa.Column("supplied_via_contract_id", guid_type, nullable=True),
            sa.UniqueConstraint(
                "project_id",
                "sheet_number",
                name="uq_oe_variations_daywork_project_sheet",
            ),
        )

    # ── oe_variations_daywork_line ────────────────────────────────────────
    if not _has_table(inspector, "oe_variations_daywork_line"):
        op.create_table(
            "oe_variations_daywork_line",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "sheet_id",
                guid_type,
                sa.ForeignKey("oe_variations_daywork_sheet.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("line_type", sa.String(20), nullable=False, server_default="labor"),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("quantity", money6, nullable=False, server_default="0"),
            sa.Column("unit", sa.String(20), nullable=False, server_default=""),
            sa.Column("unit_rate", money6, nullable=False, server_default="0"),
            sa.Column("total", money, nullable=False, server_default="0"),
            sa.Column("worker_name", sa.String(255), nullable=True),
            sa.Column("equipment_code", sa.String(100), nullable=True),
        )

    # ── oe_variations_disruption_claim ────────────────────────────────────
    if not _has_table(inspector, "oe_variations_disruption_claim"):
        op.create_table(
            "oe_variations_disruption_claim",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "project_id", guid_type, sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("raised_at", sa.String(40), nullable=True),
            sa.Column("raised_by", sa.String(36), nullable=True),
            sa.Column("claim_period_start", sa.String(20), nullable=True),
            sa.Column("claim_period_end", sa.String(20), nullable=True),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("root_cause", sa.Text(), nullable=False, server_default=""),
            sa.Column("cost_amount", money, nullable=False, server_default="0"),
            sa.Column("schedule_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
            sa.Column("decision_at", sa.String(40), nullable=True),
            sa.Column("decided_amount", money, nullable=True),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        )

    # ── oe_variations_eot_claim ───────────────────────────────────────────
    if not _has_table(inspector, "oe_variations_eot_claim"):
        op.create_table(
            "oe_variations_eot_claim",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "project_id", guid_type, sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("raised_at", sa.String(40), nullable=True),
            sa.Column("raised_by", sa.String(36), nullable=True),
            sa.Column("claim_period_start", sa.String(20), nullable=True),
            sa.Column("claim_period_end", sa.String(20), nullable=True),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("root_cause_category", sa.String(40), nullable=False, server_default="neutral"),
            sa.Column("requested_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("granted_days", sa.Integer(), nullable=True),
            sa.Column(
                "critical_path_impact",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0") if is_sqlite else sa.text("false"),
            ),
            sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
            sa.Column("decision_at", sa.String(40), nullable=True),
            sa.Column("decision_notes", sa.Text(), nullable=False, server_default=""),
        )

    # ── oe_variations_final_account ───────────────────────────────────────
    if not _has_table(inspector, "oe_variations_final_account"):
        op.create_table(
            "oe_variations_final_account",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "project_id", guid_type, sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("original_contract_value", money, nullable=False, server_default="0"),
            sa.Column("variations_total", money, nullable=False, server_default="0"),
            sa.Column("daywork_total", money, nullable=False, server_default="0"),
            sa.Column("claims_total", money, nullable=False, server_default="0"),
            sa.Column("retention_held", money, nullable=False, server_default="0"),
            sa.Column("retention_released", money, nullable=False, server_default="0"),
            sa.Column("final_value", money, nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
            sa.Column("agreed_at", sa.String(40), nullable=True),
            sa.Column("closed_at", sa.String(40), nullable=True),
            sa.UniqueConstraint(
                "project_id",
                name="uq_oe_variations_final_account_project",
            ),
        )

    # Inspector cache is stale after CREATE TABLE -- rebuild.
    inspector = sa.inspect(bind)
    for name, table, cols, unique in _INDEXES:
        if _has_index(inspector, table, name):
            continue
        try:
            op.create_index(name, table, list(cols), unique=unique)
        except sa.exc.OperationalError:
            # Already exists or table missing in some weird state — ignore.
            pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for name, table, _cols, _unique in _INDEXES:
        if _has_index(inspector, table, name):
            try:
                op.drop_index(name, table_name=table)
            except sa.exc.OperationalError:
                pass

    # Drop child tables first to respect FK constraints.
    drop_order = (
        "oe_variations_daywork_line",
        "oe_variations_daywork_sheet",
        "oe_variations_site_measurement",
        "oe_variations_schedule_impact",
        "oe_variations_cost_impact",
        "oe_variations_eot_claim",
        "oe_variations_disruption_claim",
        "oe_variations_final_account",
        "oe_variations_order",
        "oe_variations_request",
        "oe_variations_notice",
    )
    inspector = sa.inspect(bind)
    for table in drop_order:
        if _has_table(inspector, table):
            op.drop_table(table)
