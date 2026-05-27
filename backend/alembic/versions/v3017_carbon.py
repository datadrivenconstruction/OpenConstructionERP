# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""carbon — Embodied + operational carbon, EPDs, targets, sustainability reports.

Adds the nine ``oe_carbon_*`` tables backing the Carbon & Sustainability
module: EPD database, material factors, project inventories, embodied
entries, scope 1/2/3 entries, targets, sustainability reports.

Idempotent — re-applying on a DB where ``Base.metadata.create_all`` has
already created the tables is a no-op.

Revision ID: v3017_carbon
Revises: v3013_portal
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3017_carbon"
down_revision: Union[str, Sequence[str], None] = "v3016_crm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table_name, [(index_name, (columns,), unique)])
_INDEX_PLAN: tuple[tuple[str, tuple[tuple[str, tuple[str, ...], bool], ...]], ...] = (
    (
        "oe_carbon_epd_record",
        (
            ("ix_oe_carbon_epd_record_epd_id", ("epd_id",), True),
            ("ix_oe_carbon_epd_record_source", ("source",), False),
            ("ix_oe_carbon_epd_record_material_class", ("material_class",), False),
            ("ix_oe_carbon_epd_record_region", ("region",), False),
        ),
    ),
    (
        "oe_carbon_material_factor",
        (
            ("ix_oe_carbon_material_factor_cost_item_id", ("cost_item_id",), False),
            ("ix_oe_carbon_material_factor_epd_id", ("epd_id",), False),
            ("ix_oe_carbon_material_factor_region", ("region",), False),
        ),
    ),
    (
        "oe_carbon_inventory",
        (
            ("ix_oe_carbon_inventory_project_id", ("project_id",), False),
            ("ix_oe_carbon_inventory_scope", ("scope",), False),
            ("ix_oe_carbon_inventory_status", ("status",), False),
        ),
    ),
    (
        "oe_carbon_embodied_entry",
        (
            ("ix_oe_carbon_embodied_entry_inventory_id", ("inventory_id",), False),
            ("ix_oe_carbon_embodied_entry_element_ref", ("element_ref",), False),
            ("ix_oe_carbon_embodied_entry_factor_id", ("factor_id",), False),
            ("ix_oe_carbon_embodied_entry_stage", ("stage",), False),
        ),
    ),
    (
        "oe_carbon_scope1_entry",
        (
            ("ix_oe_carbon_scope1_entry_inventory_id", ("inventory_id",), False),
            ("ix_oe_carbon_scope1_entry_fuel_type", ("fuel_type",), False),
            ("ix_oe_carbon_scope1_entry_source", ("source",), False),
        ),
    ),
    (
        "oe_carbon_scope2_entry",
        (
            ("ix_oe_carbon_scope2_entry_inventory_id", ("inventory_id",), False),
            ("ix_oe_carbon_scope2_entry_energy_type", ("energy_type",), False),
        ),
    ),
    (
        "oe_carbon_scope3_entry",
        (
            ("ix_oe_carbon_scope3_entry_inventory_id", ("inventory_id",), False),
            ("ix_oe_carbon_scope3_entry_category", ("category",), False),
        ),
    ),
    (
        "oe_carbon_target",
        (
            ("ix_oe_carbon_target_project_id", ("project_id",), False),
            ("ix_oe_carbon_target_target_type", ("target_type",), False),
            ("ix_oe_carbon_target_status", ("status",), False),
        ),
    ),
    (
        "oe_carbon_report",
        (
            ("ix_oe_carbon_report_project_id", ("project_id",), False),
            ("ix_oe_carbon_report_inventory_id", ("inventory_id",), False),
            ("ix_oe_carbon_report_framework", ("framework",), False),
        ),
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

    # ── EPD ──────────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_carbon_epd_record"):
        op.create_table(
            "oe_carbon_epd_record",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column("epd_id", sa.String(120), nullable=False),
            sa.Column("source", sa.String(50), nullable=False, server_default="custom"),
            sa.Column("material_class", sa.String(80), nullable=False),
            sa.Column("product_name", sa.String(500), nullable=False),
            sa.Column("manufacturer", sa.String(255), nullable=True),
            sa.Column("region", sa.String(8), nullable=False, server_default=""),
            sa.Column("declared_unit", sa.String(20), nullable=False, server_default="kg"),
            sa.Column("gwp_a1a3", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("gwp_a4", sa.Numeric(18, 6), nullable=True),
            sa.Column("gwp_a5", sa.Numeric(18, 6), nullable=True),
            sa.Column("gwp_b_total", sa.Numeric(18, 6), nullable=True),
            sa.Column("gwp_c_total", sa.Numeric(18, 6), nullable=True),
            sa.Column("gwp_d_credits", sa.Numeric(18, 6), nullable=True),
            sa.Column("validity_until", sa.Date(), nullable=True),
            sa.Column("document_url", sa.String(1024), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── Material factors ─────────────────────────────────────────────────
    if not _has_table(inspector, "oe_carbon_material_factor"):
        op.create_table(
            "oe_carbon_material_factor",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column("cost_item_id", guid, nullable=True),
            sa.Column(
                "epd_id",
                guid,
                sa.ForeignKey("oe_carbon_epd_record.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("manual_override_factor", sa.Numeric(18, 6), nullable=True),
            sa.Column("unit_for_factor", sa.String(20), nullable=False, server_default="kg"),
            sa.Column("region", sa.String(8), nullable=False, server_default=""),
            sa.Column("last_reviewed_at", sa.Date(), nullable=True),
            sa.Column(
                "confidence",
                sa.String(16),
                nullable=False,
                server_default="medium",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── Inventory ────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_carbon_inventory"):
        op.create_table(
            "oe_carbon_inventory",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "name",
                sa.String(255),
                nullable=False,
                server_default="Baseline inventory",
            ),
            sa.Column(
                "scope",
                sa.String(40),
                nullable=False,
                server_default="cradle_to_gate",
            ),
            sa.Column("as_of_date", sa.Date(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("totals", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── Embodied ─────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_carbon_embodied_entry"):
        op.create_table(
            "oe_carbon_embodied_entry",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "inventory_id",
                guid,
                sa.ForeignKey("oe_carbon_inventory.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("element_ref", sa.String(255), nullable=True),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("quantity", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("unit", sa.String(20), nullable=False, server_default="kg"),
            sa.Column(
                "factor_id",
                guid,
                sa.ForeignKey("oe_carbon_material_factor.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "factor_value_used",
                sa.Numeric(18, 6),
                nullable=False,
                server_default="0",
            ),
            sa.Column("carbon_kg", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("stage", sa.String(8), nullable=False, server_default="a1a3"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── Scope 1 ──────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_carbon_scope1_entry"):
        op.create_table(
            "oe_carbon_scope1_entry",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "inventory_id",
                guid,
                sa.ForeignKey("oe_carbon_inventory.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column(
                "fuel_type",
                sa.String(40),
                nullable=False,
                server_default="diesel",
            ),
            sa.Column("litres_or_m3", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column(
                "emission_factor_kg_co2e_per_unit",
                sa.Numeric(18, 6),
                nullable=False,
                server_default="0",
            ),
            sa.Column("total_co2e_kg", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("source", sa.String(40), nullable=False, server_default="manual"),
            sa.Column("source_ref", guid, nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── Scope 2 ──────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_carbon_scope2_entry"):
        op.create_table(
            "oe_carbon_scope2_entry",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "inventory_id",
                guid,
                sa.ForeignKey("oe_carbon_inventory.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column(
                "energy_type",
                sa.String(40),
                nullable=False,
                server_default="grid_electricity",
            ),
            sa.Column("kwh", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column(
                "emission_factor_kg_co2e_per_kwh",
                sa.Numeric(18, 6),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "market_or_location",
                sa.String(16),
                nullable=False,
                server_default="location",
            ),
            sa.Column("total_co2e_kg", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("supplier_name", sa.String(255), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── Scope 3 ──────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_carbon_scope3_entry"):
        op.create_table(
            "oe_carbon_scope3_entry",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "inventory_id",
                guid,
                sa.ForeignKey("oe_carbon_inventory.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column(
                "category",
                sa.String(40),
                nullable=False,
                server_default="transport_upstream",
            ),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("activity_data", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column(
                "activity_unit",
                sa.String(40),
                nullable=False,
                server_default="tkm",
            ),
            sa.Column(
                "emission_factor",
                sa.Numeric(18, 6),
                nullable=False,
                server_default="0",
            ),
            sa.Column("total_co2e_kg", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── Target ───────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_carbon_target"):
        op.create_table(
            "oe_carbon_target",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column(
                "target_type",
                sa.String(40),
                nullable=False,
                server_default="absolute",
            ),
            sa.Column("baseline_value", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("target_value", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("baseline_year", sa.Integer(), nullable=False, server_default="2020"),
            sa.Column("target_year", sa.Integer(), nullable=False, server_default="2030"),
            sa.Column("scope_set", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── Report ───────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_carbon_report"):
        op.create_table(
            "oe_carbon_report",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "inventory_id",
                guid,
                sa.ForeignKey("oe_carbon_inventory.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column(
                "framework",
                sa.String(40),
                nullable=False,
                server_default="ghg_protocol",
            ),
            sa.Column("totals", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("narrative", sa.Text(), nullable=True),
            sa.Column("generated_at", sa.Date(), nullable=True),
            sa.Column(
                "generated_by",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # Indexes (idempotent + wrapped in try/except for resilience).
    inspector = sa.inspect(bind)
    for table, indexes in _INDEX_PLAN:
        for name, cols, unique in indexes:
            if _has_index(inspector, table, name):
                continue
            try:
                op.create_index(name, table, list(cols), unique=unique)
            except sa.exc.OperationalError:
                # Index race / already exists under a different inspector view.
                continue


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Drop in FK-safe order.
    table_order = (
        "oe_carbon_report",
        "oe_carbon_target",
        "oe_carbon_scope3_entry",
        "oe_carbon_scope2_entry",
        "oe_carbon_scope1_entry",
        "oe_carbon_embodied_entry",
        "oe_carbon_inventory",
        "oe_carbon_material_factor",
        "oe_carbon_epd_record",
    )
    for table in table_order:
        if not _has_table(inspector, table):
            continue
        for name, _cols, _u in dict(_INDEX_PLAN).get(table, ()):
            if _has_index(inspector, table, name):
                try:
                    op.drop_index(name, table_name=table)
                except sa.exc.OperationalError:
                    continue
        op.drop_table(table)
