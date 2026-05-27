# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module-4 deep pass: variations contract clauses, daywork markup, AICPA
disruption fields, EoT TIA fields. Bid_management: line-level inclusion
flag + prevailing-wage flag. Property_dev: deposit + handover-doc + P&L.

Additive columns only — no table drops. Idempotent: each ``add_column``
is gated by ``_has_column``. Re-running on a DB where the columns already
exist is a no-op.

Revision ID: v3030_module4_extras
Revises: v3029_qms_calibration_template_hse_extras
Created: 2026-05-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3030_module4_extras"
down_revision: Union[str, Sequence[str], None] = "v3029_qms_calibration_template_hse_extras"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def _safe_create_index(name: str, table: str, cols: list[str]) -> None:
    try:
        op.create_index(name, table, cols)
    except sa.exc.OperationalError:
        pass


def _money(scale: int = 4) -> sa.types.TypeEngine:
    """MoneyType compatible — Numeric(18, scale)."""
    return sa.Numeric(18, scale)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    # ── Variations: request — clause + NEC4 timers ─────────────────────
    additions_request: list[tuple[str, sa.Column]] = [
        (
            "contract_standard",
            sa.Column(
                "contract_standard",
                sa.String(20),
                nullable=False,
                server_default="",
            ),
        ),
        (
            "contract_clause_ref",
            sa.Column(
                "contract_clause_ref",
                sa.String(60),
                nullable=False,
                server_default="",
            ),
        ),
        (
            "quotation_due_at",
            sa.Column("quotation_due_at", sa.String(40), nullable=True),
        ),
        (
            "assessment_due_at",
            sa.Column("assessment_due_at", sa.String(40), nullable=True),
        ),
    ]
    for col_name, col_def in additions_request:
        if not _has_column(inspector, "oe_variations_request", col_name):
            with op.batch_alter_table("oe_variations_request") as batch:
                batch.add_column(col_def)

    # ── Variations: order — clause + contracts soft-link ────────────────
    additions_order: list[tuple[str, sa.Column]] = [
        (
            "contract_standard",
            sa.Column(
                "contract_standard",
                sa.String(20),
                nullable=False,
                server_default="",
            ),
        ),
        (
            "contract_clause_ref",
            sa.Column(
                "contract_clause_ref",
                sa.String(60),
                nullable=False,
                server_default="",
            ),
        ),
        (
            "affected_contract_id",
            sa.Column("affected_contract_id", guid_type, nullable=True),
        ),
    ]
    for col_name, col_def in additions_order:
        if not _has_column(inspector, "oe_variations_order", col_name):
            with op.batch_alter_table("oe_variations_order") as batch:
                batch.add_column(col_def)

    # ── Variations: daywork — BS 6079 markup ────────────────────────────
    additions_dw: list[tuple[str, sa.Column]] = [
        (
            "subtotal_amount",
            sa.Column(
                "subtotal_amount",
                _money(4),
                nullable=False,
                server_default="0",
            ),
        ),
        (
            "markup_percent",
            sa.Column(
                "markup_percent",
                _money(2),
                nullable=False,
                server_default="0",
            ),
        ),
    ]
    for col_name, col_def in additions_dw:
        if not _has_column(inspector, "oe_variations_daywork_sheet", col_name):
            with op.batch_alter_table("oe_variations_daywork_sheet") as batch:
                batch.add_column(col_def)

    # ── Variations: disruption — AICPA measured-mile ─────────────────────
    additions_disr: list[tuple[str, sa.Column]] = [
        (
            "baseline_productivity",
            sa.Column("baseline_productivity", _money(6), nullable=True),
        ),
        (
            "impacted_productivity",
            sa.Column("impacted_productivity", _money(6), nullable=True),
        ),
        (
            "unit_of_measure",
            sa.Column(
                "unit_of_measure",
                sa.String(30),
                nullable=False,
                server_default="",
            ),
        ),
        (
            "labour_hours_lost",
            sa.Column("labour_hours_lost", _money(2), nullable=True),
        ),
    ]
    for col_name, col_def in additions_disr:
        if not _has_column(inspector, "oe_variations_disruption_claim", col_name):
            with op.batch_alter_table("oe_variations_disruption_claim") as batch:
                batch.add_column(col_def)

    # ── Variations: EoT — TIA result + activity reference ───────────────
    additions_eot: list[tuple[str, sa.Column]] = [
        (
            "affected_activity_ref",
            sa.Column(
                "affected_activity_ref",
                sa.String(255),
                nullable=False,
                server_default="",
            ),
        ),
        (
            "tia_delta_days",
            sa.Column("tia_delta_days", sa.Integer(), nullable=True),
        ),
        (
            "tia_computed_at",
            sa.Column("tia_computed_at", sa.String(40), nullable=True),
        ),
    ]
    for col_name, col_def in additions_eot:
        if not _has_column(inspector, "oe_variations_eot_claim", col_name):
            with op.batch_alter_table("oe_variations_eot_claim") as batch:
                batch.add_column(col_def)

    # ── bid_management: submission line — line-level inclusion + PW ─────
    additions_sub_line: list[tuple[str, sa.Column]] = [
        (
            "inclusion_status",
            sa.Column(
                "inclusion_status",
                sa.String(32),
                nullable=False,
                server_default="included",
            ),
        ),
        (
            "prevailing_wage_applicable",
            sa.Column(
                "prevailing_wage_applicable",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0" if is_sqlite else "false"),
            ),
        ),
    ]
    for col_name, col_def in additions_sub_line:
        if not _has_column(
            inspector,
            "oe_bid_management_submission_line",
            col_name,
        ):
            with op.batch_alter_table("oe_bid_management_submission_line") as batch:
                batch.add_column(col_def)

    # ── property_dev: buyer — deposit + jurisdiction ────────────────────
    additions_buyer: list[tuple[str, sa.Column]] = [
        (
            "deposit_amount",
            sa.Column(
                "deposit_amount",
                _money(2),
                nullable=False,
                server_default="0",
            ),
        ),
        (
            "deposit_forfeited",
            sa.Column(
                "deposit_forfeited",
                _money(2),
                nullable=False,
                server_default="0",
            ),
        ),
        (
            "deposit_refunded",
            sa.Column(
                "deposit_refunded",
                _money(2),
                nullable=False,
                server_default="0",
            ),
        ),
        (
            "jurisdiction",
            sa.Column(
                "jurisdiction",
                sa.String(8),
                nullable=False,
                server_default="",
            ),
        ),
        (
            "cancelled_at",
            sa.Column("cancelled_at", sa.String(20), nullable=True),
        ),
        (
            "cancelled_reason",
            sa.Column(
                "cancelled_reason",
                sa.String(500),
                nullable=False,
                server_default="",
            ),
        ),
    ]
    for col_name, col_def in additions_buyer:
        if not _has_column(inspector, "oe_property_dev_buyer", col_name):
            with op.batch_alter_table("oe_property_dev_buyer") as batch:
                batch.add_column(col_def)

    # ── property_dev: handover-doc bundle table ─────────────────────────
    if not _has_table(inspector, "oe_property_dev_handover_doc"):
        op.create_table(
            "oe_property_dev_handover_doc",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "handover_id",
                guid_type,
                sa.ForeignKey(
                    "oe_property_dev_handover.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("doc_type", sa.String(40), nullable=False),
            sa.Column(
                "title",
                sa.String(255),
                nullable=False,
                server_default="",
            ),
            sa.Column("file_url", sa.String(1024), nullable=True),
            sa.Column(
                "is_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0" if is_sqlite else "false"),
            ),
            sa.Column(
                "is_delivered",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0" if is_sqlite else "false"),
            ),
            sa.Column("delivered_at", sa.String(40), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
        )

    # Indexes
    inspector = sa.inspect(bind)
    for name, table, cols in (
        (
            "ix_oe_variations_order_affected_contract_id",
            "oe_variations_order",
            ["affected_contract_id"],
        ),
        (
            "ix_oe_property_dev_handover_doc_handover_id",
            "oe_property_dev_handover_doc",
            ["handover_id"],
        ),
    ):
        if not _has_index(inspector, table, name):
            _safe_create_index(name, table, cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for name, table in (
        (
            "ix_oe_variations_order_affected_contract_id",
            "oe_variations_order",
        ),
        (
            "ix_oe_property_dev_handover_doc_handover_id",
            "oe_property_dev_handover_doc",
        ),
    ):
        if _has_index(inspector, table, name):
            try:
                op.drop_index(name, table_name=table)
            except sa.exc.OperationalError:
                pass

    if _has_table(inspector, "oe_property_dev_handover_doc"):
        op.drop_table("oe_property_dev_handover_doc")

    drops: list[tuple[str, str]] = [
        ("oe_property_dev_buyer", "cancelled_reason"),
        ("oe_property_dev_buyer", "cancelled_at"),
        ("oe_property_dev_buyer", "jurisdiction"),
        ("oe_property_dev_buyer", "deposit_refunded"),
        ("oe_property_dev_buyer", "deposit_forfeited"),
        ("oe_property_dev_buyer", "deposit_amount"),
        ("oe_bid_management_submission_line", "prevailing_wage_applicable"),
        ("oe_bid_management_submission_line", "inclusion_status"),
        ("oe_variations_eot_claim", "tia_computed_at"),
        ("oe_variations_eot_claim", "tia_delta_days"),
        ("oe_variations_eot_claim", "affected_activity_ref"),
        ("oe_variations_disruption_claim", "labour_hours_lost"),
        ("oe_variations_disruption_claim", "unit_of_measure"),
        ("oe_variations_disruption_claim", "impacted_productivity"),
        ("oe_variations_disruption_claim", "baseline_productivity"),
        ("oe_variations_daywork_sheet", "markup_percent"),
        ("oe_variations_daywork_sheet", "subtotal_amount"),
        ("oe_variations_order", "affected_contract_id"),
        ("oe_variations_order", "contract_clause_ref"),
        ("oe_variations_order", "contract_standard"),
        ("oe_variations_request", "assessment_due_at"),
        ("oe_variations_request", "quotation_due_at"),
        ("oe_variations_request", "contract_clause_ref"),
        ("oe_variations_request", "contract_standard"),
    ]
    for table, col in drops:
        if _has_column(inspector, table, col):
            with op.batch_alter_table(table) as batch:
                batch.drop_column(col)
