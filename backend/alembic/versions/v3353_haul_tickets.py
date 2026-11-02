# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""haul_tickets​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: truck load tickets, haulier invoices, rates, materials, settings

Creates the five ``oe_haul_tickets_*`` tables. New tables only; nothing
existing changes.

Revision ID: v3353_haul_tickets
Revises: v3352_dispatch_board
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v3353_haul_tickets"
down_revision: str | Sequence[str] | None = "v3352_dispatch_board"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "oe_haul_tickets_ticket",
    "oe_haul_tickets_invoice",
    "oe_haul_tickets_rate",
    "oe_haul_tickets_material",
    "oe_haul_tickets_settings",
)


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "oe_haul_tickets_ticket" not in existing:
        op.create_table(
            "oe_haul_tickets_ticket",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("ticket_number", sa.String(60), nullable=False, server_default=""),
            sa.Column("haul_type", sa.String(20), nullable=False, server_default="other"),
            sa.Column("direction", sa.String(10), nullable=False, server_default="inbound"),
            sa.Column("ticket_date", sa.Date(), nullable=False),
            sa.Column("time_out", sa.DateTime(timezone=True), nullable=True),
            sa.Column("time_in", sa.DateTime(timezone=True), nullable=True),
            sa.Column("origin", sa.String(255), nullable=False, server_default=""),
            sa.Column("origin_kind", sa.String(20), nullable=False, server_default="other"),
            sa.Column("destination", sa.String(255), nullable=False, server_default=""),
            sa.Column("destination_kind", sa.String(20), nullable=False, server_default="site"),
            sa.Column("material_code", sa.String(60), nullable=False, server_default=""),
            sa.Column("material_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("unit", sa.String(10), nullable=False, server_default="t"),
            sa.Column("gross_t", sa.Numeric(12, 3), nullable=True),
            sa.Column("tare_t", sa.Numeric(12, 3), nullable=True),
            sa.Column("net_t", sa.Numeric(12, 3), nullable=True),
            sa.Column("volume_m3", sa.Numeric(12, 3), nullable=True),
            sa.Column("loads", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("quantity", sa.Numeric(14, 3), nullable=False, server_default="0"),
            sa.Column("truck_source", sa.String(10), nullable=False, server_default="hired"),
            sa.Column("equipment_id", sa.String(36), nullable=True),
            sa.Column("haulier_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("haulier_party_id", sa.String(36), nullable=True),
            sa.Column("plate", sa.String(30), nullable=False, server_default=""),
            sa.Column("driver_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("vehicle_max_gross_t", sa.Numeric(10, 2), nullable=True),
            sa.Column("vehicle_capacity", sa.Numeric(10, 2), nullable=True),
            sa.Column("po_id", sa.String(36), nullable=True),
            sa.Column("rate_basis", sa.String(10), nullable=False, server_default="t"),
            sa.Column("rate", sa.Numeric(18, 4), nullable=True),
            sa.Column("hours", sa.Numeric(8, 2), nullable=True),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("boq_position_id", sa.String(36), nullable=True),
            sa.Column("cost_code", sa.String(100), nullable=False, server_default=""),
            sa.Column("status", sa.String(20), nullable=False, server_default="issued"),
            sa.Column("reject_reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("receiver_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("signature", sa.Text(), nullable=True),
            sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("photos", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("waste_code", sa.String(40), nullable=False, server_default=""),
            sa.Column("waste_catalogue", sa.String(40), nullable=False, server_default=""),
            sa.Column("hazardous", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("receiving_facility", sa.String(255), nullable=False, server_default=""),
            sa.Column("facility_permit_ref", sa.String(120), nullable=False, server_default=""),
            sa.Column("transport_id", sa.String(36), nullable=True),
            sa.Column("delivery_id", sa.String(36), nullable=True),
            sa.Column("invoice_id", sa.String(36), nullable=True),
            sa.Column("qr_token", sa.String(40), nullable=False, unique=True),
            sa.Column("source", sa.String(10), nullable=False, server_default="manual"),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_{tname}_project_id", "{tname}", ["project_id"])
        op.create_index("ix_haul_ticket_project_date", "oe_haul_tickets_ticket", ["project_id", "ticket_date"])
        op.create_index(
            "ix_haul_ticket_haulier_number", "oe_haul_tickets_ticket", ["project_id", "haulier_name", "ticket_number"]
        )
        op.create_index("ix_haul_ticket_position", "oe_haul_tickets_ticket", ["boq_position_id"])
        op.create_index("ix_oe_haul_tickets_ticket_status", "oe_haul_tickets_ticket", ["status"])
    if "oe_haul_tickets_invoice" not in existing:
        op.create_table(
            "oe_haul_tickets_invoice",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("haulier_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("invoice_number", sa.String(60), nullable=False, server_default=""),
            sa.Column("invoice_date", sa.Date(), nullable=True),
            sa.Column("period_from", sa.Date(), nullable=True),
            sa.Column("period_to", sa.Date(), nullable=True),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("total", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("lines", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("result", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_{tname}_project_id", "{tname}", ["project_id"])
    if "oe_haul_tickets_rate" not in existing:
        op.create_table(
            "oe_haul_tickets_rate",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("haulier_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("material_code", sa.String(60), nullable=False, server_default=""),
            sa.Column("rate_basis", sa.String(10), nullable=False, server_default="t"),
            sa.Column("rate", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("po_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_{tname}_project_id", "{tname}", ["project_id"])
    if "oe_haul_tickets_material" not in existing:
        op.create_table(
            "oe_haul_tickets_material",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("code", sa.String(60), nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("unit", sa.String(10), nullable=False, server_default="t"),
            sa.Column("haul_type", sa.String(20), nullable=False, server_default="other"),
            sa.Column("density_t_m3", sa.Numeric(8, 3), nullable=True),
            sa.Column("waste_code", sa.String(40), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_{tname}_project_id", "{tname}", ["project_id"])
    if "oe_haul_tickets_settings" not in existing:
        op.create_table(
            "oe_haul_tickets_settings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("mandatory_fields", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("max_gross_t", sa.Numeric(10, 2), nullable=True),
            sa.Column("capacity_tolerance_pct", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("price_tolerance_pct", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("waste_catalogue", sa.String(40), nullable=False, server_default=""),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_{tname}_project_id", "{tname}", ["project_id"])


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for name in reversed(_TABLES):
        if name in existing:
            op.drop_table(name)
