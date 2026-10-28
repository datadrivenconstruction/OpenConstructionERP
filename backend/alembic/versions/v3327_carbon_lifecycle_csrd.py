# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""carbon:​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ life-cycle stages, factor sets, data quality and company E1 reporting

Adds ``supplier_catalog_item_id`` and ``epd_format`` to EPD records,
``factor_set`` and ``factor_set_year`` to material factors, a ``data_quality``
flag (measured, calculated, estimated) to embodied and scope 1/2/3 lines, and
creates ``oe_carbon_company_activity`` and ``oe_carbon_company_report``.

Revision ID: v3327_carbon_lifecycle_csrd
Revises: v3327_equipment_telematics_site_sensors
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v3327_carbon_lifecycle_csrd"
down_revision: str | Sequence[str] | None = "v3327_equipment_telematics_site_sensors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACT = "oe_carbon_company_activity"
_REP = "oe_carbon_company_report"
_DQ_TABLES = (
    "oe_carbon_embodied_entry",
    "oe_carbon_scope1_entry",
    "oe_carbon_scope2_entry",
    "oe_carbon_scope3_entry",
)


def _new_columns() -> dict[str, list[sa.Column]]:
    cols: dict[str, list[sa.Column]] = {
        "oe_carbon_epd_record": [
            sa.Column("supplier_catalog_item_id", sa.String(36), nullable=True),
            sa.Column("epd_format", sa.String(16), nullable=True),
        ],
        "oe_carbon_material_factor": [
            sa.Column("factor_set", sa.String(80), nullable=True),
            sa.Column("factor_set_year", sa.Integer(), nullable=True),
        ],
    }
    for table in _DQ_TABLES:
        cols[table] = [sa.Column("data_quality", sa.String(16), nullable=False, server_default="calculated")]
    return cols


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table, cols in _new_columns().items():
        if table not in tables:
            continue
        have = {c["name"] for c in inspector.get_columns(table)}
        for col in cols:
            if col.name not in have:
                op.add_column(table, col)
    if "oe_carbon_epd_record" in tables:
        op.create_index(
            "ix_oe_carbon_epd_record_supplier_catalog_item_id",
            "oe_carbon_epd_record",
            ["supplier_catalog_item_id"],
            if_not_exists=True,
        )
    if _ACT not in tables:
        op.create_table(
            _ACT,
            *_stamps(),
            sa.Column("reporting_year", sa.Integer(), nullable=False),
            sa.Column("scope", sa.Integer(), nullable=False),
            sa.Column("scope3_category", sa.Integer(), nullable=True),
            sa.Column("category", sa.String(40), nullable=False, server_default="office"),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("activity_amount", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("activity_unit", sa.String(20), nullable=False, server_default="kWh"),
            sa.Column("emission_factor", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("factor_source", sa.String(255), nullable=False, server_default=""),
            sa.Column("co2e_kg", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("energy_kwh", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("renewable_share_pct", sa.Numeric(7, 3), nullable=False, server_default="0"),
            sa.Column("market_based_co2e_kg", sa.Numeric(18, 6), nullable=True),
            sa.Column("data_quality", sa.String(16), nullable=False, server_default="calculated"),
            sa.Column("source_module", sa.String(40), nullable=False, server_default="manual"),
            sa.Column("source_ref", sa.String(36), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index(f"ix_{_ACT}_reporting_year", _ACT, ["reporting_year"])
        op.create_index(f"ix_{_ACT}_scope", _ACT, ["scope"])
        op.create_index(f"ix_{_ACT}_created_by", _ACT, ["created_by"])
    if _REP not in tables:
        op.create_table(
            _REP,
            *_stamps(),
            sa.Column("reporting_year", sa.Integer(), nullable=False),
            sa.Column("template", sa.String(32), nullable=False, server_default="esrs_e1"),
            sa.Column("company_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("net_revenue", sa.Numeric(20, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
            sa.Column("datapoints", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("audit", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index(f"ix_{_REP}_reporting_year", _REP, ["reporting_year"])
        op.create_index(f"ix_{_REP}_template", _REP, ["template"])
        op.create_index(f"ix_{_REP}_created_by", _REP, ["created_by"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table in (_REP, _ACT):
        if table in tables:
            op.drop_table(table)
    if "oe_carbon_epd_record" in tables:
        op.drop_index("ix_oe_carbon_epd_record_supplier_catalog_item_id", "oe_carbon_epd_record", if_exists=True)
    for table, cols in _new_columns().items():
        if table not in tables:
            continue
        have = {c["name"] for c in inspector.get_columns(table)}
        for col in cols:
            if col.name in have:
                op.drop_column(table, col.name)
