# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""leasing module: leases, rent schedule lines and lease events

Creates ``oe_leasing_lease``, ``oe_leasing_lease_document``,
``oe_leasing_schedule_line`` and ``oe_leasing_event``. New tables only, inspector-guarded, so a database that
``create_all`` already built reaches this revision and does nothing.

Revision ID: v3341_leasing_module
Revises: v3332_prefab_supply_chain_tracking
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v3341_leasing_module"
down_revision: str | Sequence[str] | None = "v3332_prefab_supply_chain_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _money(name: str) -> sa.Column:
    return sa.Column(name, sa.Numeric(18, 2), nullable=False, server_default="0")


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "oe_leasing_lease" not in tables:
        op.create_table(
            "oe_leasing_lease",
            *_base(),
            sa.Column(
                "project_id", GUID(), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("unit_kind", sa.String(20), nullable=False, server_default="plot"),
            sa.Column("unit_ref", sa.String(64), nullable=False),
            sa.Column("unit_label", sa.String(255), nullable=False, server_default=""),
            sa.Column("tenant_contact_id", sa.String(36), nullable=False),
            sa.Column("landlord_legal_entity_id", GUID(), nullable=True),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("term_months", sa.Integer(), nullable=False, server_default="0"),
            _money("rent_amount"),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("frequency", sa.String(20), nullable=False, server_default="monthly"),
            _money("deposit"),
            sa.Column("escalation_kind", sa.String(10), nullable=False, server_default="none"),
            sa.Column("escalation_rate", sa.Numeric(9, 4), nullable=True),
            sa.Column("escalation_index", sa.String(100), nullable=True),
            sa.Column("escalation_every_months", sa.Integer(), nullable=False, server_default="12"),
            sa.Column("tax_code", sa.String(30), nullable=True),
            sa.Column("tax_rate", sa.Numeric(7, 4), nullable=False, server_default="0"),
            sa.Column("payment_terms_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
            sa.Column("break_date", sa.Date(), nullable=True),
            sa.Column("notice_date", sa.Date(), nullable=True),
            sa.Column("ended_on", sa.Date(), nullable=True),
            sa.Column("renewed_from_id", GUID(), nullable=True),
            sa.Column("ext_refs", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("project_id", "code", name="uq_leasing_lease_project_code"),
        )
        op.create_index("ix_oe_leasing_lease_project_id", "oe_leasing_lease", ["project_id"])
        op.create_index("ix_oe_leasing_lease_tenant_contact_id", "oe_leasing_lease", ["tenant_contact_id"])
        op.create_index(
            "ix_oe_leasing_lease_landlord_legal_entity_id", "oe_leasing_lease", ["landlord_legal_entity_id"]
        )
        op.create_index("ix_oe_leasing_lease_status", "oe_leasing_lease", ["status"])
        op.create_index("ix_leasing_lease_unit", "oe_leasing_lease", ["unit_kind", "unit_ref"])
    if "oe_leasing_lease_document" not in tables:
        op.create_table(
            "oe_leasing_lease_document",
            *_base(),
            sa.Column("lease_id", GUID(), sa.ForeignKey("oe_leasing_lease.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "document_id", GUID(), sa.ForeignKey("oe_documents_document.id", ondelete="CASCADE"), nullable=False
            ),
            sa.UniqueConstraint("lease_id", "document_id", name="uq_leasing_lease_document"),
        )
        op.create_index("ix_oe_leasing_lease_document_lease_id", "oe_leasing_lease_document", ["lease_id"])
        op.create_index("ix_oe_leasing_lease_document_document_id", "oe_leasing_lease_document", ["document_id"])
    if "oe_leasing_schedule_line" not in tables:
        op.create_table(
            "oe_leasing_schedule_line",
            *_base(),
            sa.Column("lease_id", GUID(), sa.ForeignKey("oe_leasing_lease.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", GUID(), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("due_date", sa.Date(), nullable=False),
            _money("amount"),
            sa.Column("tax_code", sa.String(30), nullable=True),
            _money("tax_amount"),
            sa.Column("review_number", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("invoice_id", GUID(), nullable=True),
            sa.UniqueConstraint("lease_id", "period_start", name="uq_leasing_line_lease_period"),
        )
        for col in ("lease_id", "project_id", "due_date", "invoice_id"):
            op.create_index(f"ix_oe_leasing_schedule_line_{col}", "oe_leasing_schedule_line", [col])
    if "oe_leasing_event" not in tables:
        op.create_table(
            "oe_leasing_event",
            *_base(),
            sa.Column("lease_id", GUID(), sa.ForeignKey("oe_leasing_lease.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", GUID(), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("event_date", sa.Date(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("actor_id", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_leasing_event_lease_id", "oe_leasing_event", ["lease_id"])
        op.create_index("ix_oe_leasing_event_project_id", "oe_leasing_event", ["project_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name in ("oe_leasing_event", "oe_leasing_schedule_line", "oe_leasing_lease_document", "oe_leasing_lease"):
        if name in tables:
            op.drop_table(name)
