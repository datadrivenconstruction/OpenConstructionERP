# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""property_dev — Property Development + Buyer Portal foundation.

Creates twelve ``oe_property_dev_*`` tables: developments, plots, house
types + variants, buyer option groups + options, buyers + selections +
selection items, handovers, snags, warranty claims.

External UUID references (NO FK at DB level):
    - portal_user_id              (oe_portal_user.id  — Module 21)
    - linked_service_ticket_id    (oe_service_ticket.id — Module 18)
    - bim_model_ref               (canonical model id, string)

Idempotent — re-applying on a DB where ``Base.metadata.create_all`` has
already created the tables is a no-op.

Revision ID: v3018_property_dev
Revises: v3017_carbon
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3018_property_dev"
down_revision: Union[str, Sequence[str], None] = "v3017_carbon"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES: tuple[str, ...] = (
    "oe_property_dev_development",
    "oe_property_dev_house_type",
    "oe_property_dev_house_type_variant",
    "oe_property_dev_plot",
    "oe_property_dev_buyer_option_group",
    "oe_property_dev_buyer_option",
    "oe_property_dev_buyer",
    "oe_property_dev_buyer_selection",
    "oe_property_dev_buyer_selection_item",
    "oe_property_dev_handover",
    "oe_property_dev_snag",
    "oe_property_dev_warranty_claim",
)


# (table, index_name, columns, unique).
_INDEXES: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    (
        "oe_property_dev_development",
        "ix_oe_property_dev_development_project_id",
        ("project_id",),
        False,
    ),
    (
        "oe_property_dev_development",
        "ix_oe_property_dev_development_code",
        ("code",),
        True,
    ),
    (
        "oe_property_dev_development",
        "ix_oe_property_dev_development_sales_phase",
        ("sales_phase",),
        False,
    ),
    (
        "oe_property_dev_development",
        "ix_oe_property_dev_development_status",
        ("status",),
        False,
    ),
    (
        "oe_property_dev_house_type",
        "ix_oe_property_dev_house_type_development_id",
        ("development_id",),
        False,
    ),
    (
        "oe_property_dev_house_type_variant",
        "ix_oe_property_dev_house_type_variant_house_type_id",
        ("house_type_id",),
        False,
    ),
    (
        "oe_property_dev_plot",
        "ix_oe_property_dev_plot_development_id",
        ("development_id",),
        False,
    ),
    (
        "oe_property_dev_plot",
        "ix_oe_property_dev_plot_house_type_id",
        ("house_type_id",),
        False,
    ),
    (
        "oe_property_dev_plot",
        "ix_oe_property_dev_plot_status",
        ("status",),
        False,
    ),
    (
        "oe_property_dev_buyer_option_group",
        "ix_oe_property_dev_buyer_option_group_development_id",
        ("development_id",),
        False,
    ),
    (
        "oe_property_dev_buyer_option",
        "ix_oe_property_dev_buyer_option_group_id",
        ("group_id",),
        False,
    ),
    (
        "oe_property_dev_buyer_option",
        "ix_oe_property_dev_buyer_option_sku",
        ("sku",),
        False,
    ),
    (
        "oe_property_dev_buyer_option",
        "ix_oe_property_dev_buyer_option_is_active",
        ("is_active",),
        False,
    ),
    (
        "oe_property_dev_buyer",
        "ix_oe_property_dev_buyer_development_id",
        ("development_id",),
        False,
    ),
    (
        "oe_property_dev_buyer",
        "ix_oe_property_dev_buyer_email",
        ("email",),
        False,
    ),
    (
        "oe_property_dev_buyer",
        "ix_oe_property_dev_buyer_status",
        ("status",),
        False,
    ),
    (
        "oe_property_dev_buyer_selection",
        "ix_oe_property_dev_buyer_selection_buyer_id",
        ("buyer_id",),
        False,
    ),
    (
        "oe_property_dev_buyer_selection",
        "ix_oe_property_dev_buyer_selection_status",
        ("status",),
        False,
    ),
    (
        "oe_property_dev_buyer_selection_item",
        "ix_oe_property_dev_buyer_selection_item_selection_id",
        ("selection_id",),
        False,
    ),
    (
        "oe_property_dev_buyer_selection_item",
        "ix_oe_property_dev_buyer_selection_item_option_id",
        ("option_id",),
        False,
    ),
    (
        "oe_property_dev_snag",
        "ix_oe_property_dev_snag_handover_id",
        ("handover_id",),
        False,
    ),
    (
        "oe_property_dev_snag",
        "ix_oe_property_dev_snag_severity",
        ("severity",),
        False,
    ),
    (
        "oe_property_dev_snag",
        "ix_oe_property_dev_snag_status",
        ("status",),
        False,
    ),
    (
        "oe_property_dev_warranty_claim",
        "ix_oe_property_dev_warranty_claim_plot_id",
        ("plot_id",),
        False,
    ),
    (
        "oe_property_dev_warranty_claim",
        "ix_oe_property_dev_warranty_claim_buyer_id",
        ("buyer_id",),
        False,
    ),
    (
        "oe_property_dev_warranty_claim",
        "ix_oe_property_dev_warranty_claim_category",
        ("category",),
        False,
    ),
    (
        "oe_property_dev_warranty_claim",
        "ix_oe_property_dev_warranty_claim_status",
        ("status",),
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


def _audit_columns() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    # ── development ──────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_development"):
        op.create_table(
            "oe_property_dev_development",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("location_address", sa.Text(), nullable=True),
            sa.Column(
                "total_plots",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "sales_phase",
                sa.String(40),
                nullable=False,
                server_default="planning",
            ),
            sa.Column("launch_date", sa.String(20), nullable=True),
            sa.Column("completion_date", sa.String(20), nullable=True),
            sa.Column("marketing_brief", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(40),
                nullable=False,
                server_default="active",
            ),
            sa.Column(
                "units",
                sa.String(16),
                nullable=False,
                server_default="metric",
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # ── house_type ───────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_house_type"):
        op.create_table(
            "oe_property_dev_house_type",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "development_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_development.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("bedrooms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("bathrooms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "total_area_m2",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "footprint_m2",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("levels", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "base_price",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(8), nullable=False, server_default=""),
            sa.Column("bim_model_ref", sa.String(120), nullable=True),
            sa.Column("thumbnail_url", sa.String(1024), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.UniqueConstraint(
                "development_id",
                "code",
                name="uq_oe_property_dev_house_type_dev_code",
            ),
        )

    # ── house_type_variant ───────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_house_type_variant"):
        op.create_table(
            "oe_property_dev_house_type_variant",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "house_type_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_house_type.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column(
                "modifier_pct",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.UniqueConstraint(
                "house_type_id",
                "code",
                name="uq_oe_property_dev_variant_house_code",
            ),
        )

    # ── plot ─────────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_plot"):
        op.create_table(
            "oe_property_dev_plot",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "development_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_development.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("plot_number", sa.String(50), nullable=False),
            sa.Column(
                "house_type_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_house_type.id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            ),
            sa.Column(
                "house_type_variant_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_house_type_variant.id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            ),
            sa.Column("orientation", sa.String(16), nullable=True),
            sa.Column(
                "area_m2",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("garden_area_m2", sa.Numeric(18, 2), nullable=True),
            sa.Column(
                "price_base",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(8), nullable=False, server_default=""),
            sa.Column(
                "status",
                sa.String(40),
                nullable=False,
                server_default="planned",
            ),
            sa.Column("reservation_deadline", sa.String(20), nullable=True),
            sa.Column(
                "construction_status_percent",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.UniqueConstraint(
                "development_id",
                "plot_number",
                name="uq_oe_property_dev_plot_dev_number",
            ),
        )

    # ── buyer_option_group ───────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_buyer_option_group"):
        op.create_table(
            "oe_property_dev_buyer_option_group",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "development_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_development.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column(
                "group_type",
                sa.String(40),
                nullable=False,
                server_default="extras",
            ),
            sa.Column(
                "display_order",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "allow_multiple",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("max_count", sa.Integer(), nullable=True),
            sa.Column(
                "freeze_offset_days_before_handover",
                sa.Integer(),
                nullable=False,
                server_default="60",
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.UniqueConstraint(
                "development_id",
                "code",
                name="uq_oe_property_dev_option_group_dev_code",
            ),
        )

    # ── buyer_option ─────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_buyer_option"):
        op.create_table(
            "oe_property_dev_buyer_option",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "group_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_buyer_option_group.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("code", sa.String(80), nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("sku", sa.String(120), nullable=True),
            sa.Column(
                "price_delta",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(8), nullable=False, server_default=""),
            sa.Column(
                "lead_time_days",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("supplier_name", sa.String(255), nullable=True),
            sa.Column("thumbnail_url", sa.String(1024), nullable=True),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column(
                "compatibility_rules",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # ── buyer ────────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_buyer"):
        op.create_table(
            "oe_property_dev_buyer",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "development_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_development.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "plot_id",
                guid,
                sa.ForeignKey("oe_property_dev_plot.id", ondelete="SET NULL"),
                nullable=True,
            ),
            # portal_user_id intentionally NO FK (cross-module, plain UUID).
            sa.Column("portal_user_id", guid, nullable=True),
            sa.Column("full_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("email", sa.String(255), nullable=False, server_default=""),
            sa.Column("phone", sa.String(40), nullable=True),
            sa.Column("language", sa.String(10), nullable=False, server_default="en"),
            sa.Column(
                "status",
                sa.String(40),
                nullable=False,
                server_default="lead",
            ),
            sa.Column(
                "contract_value",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(8), nullable=False, server_default=""),
            sa.Column("contract_signed_at", sa.String(20), nullable=True),
            sa.Column("deposit_paid_at", sa.String(20), nullable=True),
            sa.Column("freeze_deadline", sa.String(20), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.UniqueConstraint("plot_id", name="uq_oe_property_dev_buyer_plot"),
        )

    # ── buyer_selection ──────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_buyer_selection"):
        op.create_table(
            "oe_property_dev_buyer_selection",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "buyer_id",
                guid,
                sa.ForeignKey("oe_property_dev_buyer.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.String(40),
                nullable=False,
                server_default="draft",
            ),
            sa.Column("submitted_at", sa.String(20), nullable=True),
            sa.Column("locked_at", sa.String(20), nullable=True),
            sa.Column(
                "total_options_value",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # ── buyer_selection_item ─────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_buyer_selection_item"):
        op.create_table(
            "oe_property_dev_buyer_selection_item",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "selection_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_buyer_selection.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "option_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_buyer_option.id",
                    ondelete="RESTRICT",
                ),
                nullable=False,
            ),
            sa.Column(
                "quantity",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "unit_price_snapshot",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "total_price",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "included_in_production",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # ── handover ─────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_handover"):
        op.create_table(
            "oe_property_dev_handover",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "plot_id",
                guid,
                sa.ForeignKey("oe_property_dev_plot.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("scheduled_at", sa.String(20), nullable=True),
            sa.Column("completed_at", sa.String(20), nullable=True),
            sa.Column(
                "snag_count_at_handover",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "final_check_passed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("keys_handed_over_at", sa.String(20), nullable=True),
            sa.Column("customer_signature_ref", sa.String(255), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.UniqueConstraint("plot_id", name="uq_oe_property_dev_handover_plot"),
        )

    # ── snag ─────────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_snag"):
        op.create_table(
            "oe_property_dev_snag",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "handover_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_handover.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("location_in_plot", sa.String(255), nullable=True),
            sa.Column(
                "severity",
                sa.String(20),
                nullable=False,
                server_default="minor",
            ),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="open",
            ),
            sa.Column("reported_at", sa.String(20), nullable=True),
            sa.Column("fixed_at", sa.String(20), nullable=True),
            sa.Column("fix_notes", sa.Text(), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # ── warranty_claim ───────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_warranty_claim"):
        op.create_table(
            "oe_property_dev_warranty_claim",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "plot_id",
                guid,
                sa.ForeignKey("oe_property_dev_plot.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "buyer_id",
                guid,
                sa.ForeignKey("oe_property_dev_buyer.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("raised_at", sa.String(20), nullable=True),
            sa.Column(
                "category",
                sa.String(40),
                nullable=False,
                server_default="defect",
            ),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "status",
                sa.String(40),
                nullable=False,
                server_default="raised",
            ),
            sa.Column("accepted_at", sa.String(20), nullable=True),
            sa.Column("closed_at", sa.String(20), nullable=True),
            # linked_service_ticket_id intentionally NO FK (cross-module).
            sa.Column("linked_service_ticket_id", guid, nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # Indexes — refresh inspector cache after CREATE TABLE.
    inspector = sa.inspect(bind)
    for table, name, cols, unique in _INDEXES:
        if _has_index(inspector, table, name):
            continue
        try:
            op.create_index(name, table, list(cols), unique=unique)
        except sa.exc.OperationalError:
            # Already exists under a different inspector view (race / sqlite quirk).
            continue


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table, name, _cols, _unique in _INDEXES:
        if _has_index(inspector, table, name):
            try:
                op.drop_index(name, table_name=table)
            except sa.exc.OperationalError:
                continue

    # Drop in reverse-FK order.
    for table in reversed(_TABLES):
        if _has_table(inspector, table):
            op.drop_table(table)
