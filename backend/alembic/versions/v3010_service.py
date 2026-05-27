# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service & Maintenance module: contracts, assets, tickets, work orders, SLA, schedules, checklists.

Adds the nine tables backing :mod:`app.modules.service`:

    * ``oe_service_sla_definition``       — reusable SLA tiers
    * ``oe_service_checklist``            — inspection checklist templates
    * ``oe_service_contract``             — customer-scoped service agreement
    * ``oe_service_asset``                — serviceable customer asset
    * ``oe_service_ticket``               — incoming service request
    * ``oe_service_work_order``           — dispatched on-site visit
    * ``oe_service_work_order_item``      — labor / material / travel line
    * ``oe_service_debrief``              — P-C-S report
    * ``oe_service_schedule``             — PPM recurring schedule

Idempotent — re-running on a DB where ``Base.metadata.create_all`` has
already created any of these tables is a no-op for that table.

Revision ID: v3010_service
Revises: v2943_compliance_docs
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3010_service"
down_revision: Union[str, Sequence[str], None] = "v2943_compliance_docs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# All tables created by this migration, in topological order.
_TABLES: tuple[str, ...] = (
    "oe_service_sla_definition",
    "oe_service_checklist",
    "oe_service_contract",
    "oe_service_asset",
    "oe_service_ticket",
    "oe_service_work_order",
    "oe_service_work_order_item",
    "oe_service_debrief",
    "oe_service_schedule",
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


def _ensure_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    index_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if not _has_index(inspector, table, index_name):
        try:
            op.create_index(index_name, table, columns, unique=unique)
        except sa.exc.OperationalError:
            pass


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    # GUID() TypeDecorator: VARCHAR(36) on SQLite, native UUID on PostgreSQL.
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)
    inspector = sa.inspect(bind)

    # ── oe_service_sla_definition ────────────────────────────────────────
    if not _has_table(inspector, "oe_service_sla_definition"):
        op.create_table(
            "oe_service_sla_definition",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("response_time_minutes", sa.Integer(), nullable=False, server_default="240"),
            sa.Column("resolution_time_minutes", sa.Integer(), nullable=False, server_default="1440"),
            sa.Column("severity_levels", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── oe_service_checklist ─────────────────────────────────────────────
    if not _has_table(inspector, "oe_service_checklist"):
        op.create_table(
            "oe_service_checklist",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("asset_type", sa.String(64), nullable=True),
            sa.Column("items", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # Refresh inspector cache once after first batch
    inspector = sa.inspect(bind)
    _ensure_index(inspector, "oe_service_checklist", "ix_oe_service_checklist_asset_type", ["asset_type"])

    # ── oe_service_contract ──────────────────────────────────────────────
    if not _has_table(inspector, "oe_service_contract"):
        op.create_table(
            "oe_service_contract",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "customer_id",
                guid_type,
                sa.ForeignKey("oe_contacts_contact.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey("oe_projects_project.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("contract_number", sa.String(50), nullable=False),
            sa.Column("title", sa.String(255), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("period_start", sa.String(20), nullable=False),
            sa.Column("period_end", sa.String(20), nullable=False),
            sa.Column(
                "sla_definition_id",
                guid_type,
                sa.ForeignKey("oe_service_sla_definition.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("sla_tier", sa.String(50), nullable=False, server_default="standard"),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("value", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    inspector = sa.inspect(bind)
    _ensure_index(inspector, "oe_service_contract", "ix_oe_service_contract_customer_id", ["customer_id"])
    _ensure_index(inspector, "oe_service_contract", "ix_oe_service_contract_project_id", ["project_id"])
    _ensure_index(inspector, "oe_service_contract", "ix_oe_service_contract_status", ["status"])
    _ensure_index(inspector, "oe_service_contract", "ix_oe_service_contract_sla_definition_id", ["sla_definition_id"])

    # ── oe_service_asset ─────────────────────────────────────────────────
    if not _has_table(inspector, "oe_service_asset"):
        op.create_table(
            "oe_service_asset",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "contract_id",
                guid_type,
                sa.ForeignKey("oe_service_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("asset_tag", sa.String(64), nullable=True),
            sa.Column("asset_type", sa.String(64), nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("location", sa.String(500), nullable=True),
            sa.Column("manufacturer", sa.String(255), nullable=True),
            sa.Column("model", sa.String(255), nullable=True),
            sa.Column("serial", sa.String(255), nullable=True),
            sa.Column("install_date", sa.String(20), nullable=True),
            sa.Column("warranty_until", sa.String(20), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    inspector = sa.inspect(bind)
    _ensure_index(inspector, "oe_service_asset", "ix_oe_service_asset_contract_id", ["contract_id"])
    _ensure_index(inspector, "oe_service_asset", "ix_oe_service_asset_asset_type", ["asset_type"])
    _ensure_index(inspector, "oe_service_asset", "ix_oe_service_asset_status", ["status"])

    # ── oe_service_ticket ────────────────────────────────────────────────
    if not _has_table(inspector, "oe_service_ticket"):
        op.create_table(
            "oe_service_ticket",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "contract_id",
                guid_type,
                sa.ForeignKey("oe_service_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "asset_id",
                guid_type,
                sa.ForeignKey("oe_service_asset.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("ticket_number", sa.String(50), nullable=False),
            sa.Column("title", sa.String(500), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("priority", sa.String(20), nullable=False, server_default="med"),
            sa.Column("reported_at", sa.String(40), nullable=False),
            sa.Column("sla_due_at", sa.String(40), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="new"),
            sa.Column("reported_by", sa.String(36), nullable=True),
            sa.Column("assigned_to", sa.String(36), nullable=True),
            sa.Column("resolved_at", sa.String(40), nullable=True),
            sa.Column("closed_at", sa.String(40), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    inspector = sa.inspect(bind)
    _ensure_index(inspector, "oe_service_ticket", "ix_oe_service_ticket_contract_id", ["contract_id"])
    _ensure_index(inspector, "oe_service_ticket", "ix_oe_service_ticket_asset_id", ["asset_id"])
    _ensure_index(inspector, "oe_service_ticket", "ix_oe_service_ticket_priority", ["priority"])
    _ensure_index(inspector, "oe_service_ticket", "ix_oe_service_ticket_status", ["status"])
    _ensure_index(inspector, "oe_service_ticket", "ix_oe_service_ticket_assigned_to", ["assigned_to"])
    _ensure_index(inspector, "oe_service_ticket", "ix_oe_service_ticket_sla_due_at", ["sla_due_at"])

    # ── oe_service_work_order ────────────────────────────────────────────
    if not _has_table(inspector, "oe_service_work_order"):
        op.create_table(
            "oe_service_work_order",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "ticket_id",
                guid_type,
                sa.ForeignKey("oe_service_ticket.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("work_order_number", sa.String(50), nullable=False),
            sa.Column("scheduled_for", sa.String(40), nullable=True),
            sa.Column("technician_id", sa.String(36), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="scheduled"),
            sa.Column("debrief_summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("customer_signature", sa.Text(), nullable=True),
            sa.Column("billed_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("completed_at", sa.String(40), nullable=True),
            sa.Column("billed_at", sa.String(40), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    inspector = sa.inspect(bind)
    _ensure_index(inspector, "oe_service_work_order", "ix_oe_service_work_order_ticket_id", ["ticket_id"])
    _ensure_index(inspector, "oe_service_work_order", "ix_oe_service_work_order_status", ["status"])
    _ensure_index(inspector, "oe_service_work_order", "ix_oe_service_work_order_technician_id", ["technician_id"])

    # ── oe_service_work_order_item ───────────────────────────────────────
    if not _has_table(inspector, "oe_service_work_order_item"):
        op.create_table(
            "oe_service_work_order_item",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "work_order_id",
                guid_type,
                sa.ForeignKey("oe_service_work_order.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("item_type", sa.String(20), nullable=False, server_default="labor"),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("unit", sa.String(20), nullable=False, server_default=""),
            sa.Column("unit_rate", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("total", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    inspector = sa.inspect(bind)
    _ensure_index(
        inspector, "oe_service_work_order_item", "ix_oe_service_work_order_item_work_order_id", ["work_order_id"]
    )

    # ── oe_service_debrief ───────────────────────────────────────────────
    if not _has_table(inspector, "oe_service_debrief"):
        op.create_table(
            "oe_service_debrief",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "work_order_id",
                guid_type,
                sa.ForeignKey("oe_service_work_order.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("problem", sa.Text(), nullable=False, server_default=""),
            sa.Column("cause", sa.Text(), nullable=False, server_default=""),
            sa.Column("solution", sa.Text(), nullable=False, server_default=""),
            sa.Column("root_cause_category", sa.String(64), nullable=True),
            sa.Column("follow_up_required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    inspector = sa.inspect(bind)
    _ensure_index(inspector, "oe_service_debrief", "ix_oe_service_debrief_work_order_id", ["work_order_id"])

    # ── oe_service_schedule ──────────────────────────────────────────────
    if not _has_table(inspector, "oe_service_schedule"):
        op.create_table(
            "oe_service_schedule",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.Column(
                "asset_id",
                guid_type,
                sa.ForeignKey("oe_service_asset.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("frequency", sa.String(20), nullable=False, server_default="quarterly"),
            sa.Column("next_due_date", sa.String(20), nullable=False),
            sa.Column("last_completed_at", sa.String(40), nullable=True),
            sa.Column(
                "checklist_template_id",
                guid_type,
                sa.ForeignKey("oe_service_checklist.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    inspector = sa.inspect(bind)
    _ensure_index(inspector, "oe_service_schedule", "ix_oe_service_schedule_asset_id", ["asset_id"])
    _ensure_index(inspector, "oe_service_schedule", "ix_oe_service_schedule_next_due_date", ["next_due_date"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop in reverse-dependency order to avoid FK violations.
    for table in reversed(_TABLES):
        if _has_table(inspector, table):
            # Drop any explicit indexes first (op.drop_table handles unnamed ones).
            for idx in inspector.get_indexes(table):
                if idx.get("name"):
                    try:
                        op.drop_index(idx["name"], table_name=table)
                    except Exception:
                        pass
            op.drop_table(table)
            inspector = sa.inspect(bind)
