# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""service_charges module: owners associations, keys, budgets, demands, reconciliations

New tables only, inspector-guarded, so a database that ``create_all`` already built
reaches this revision and does nothing.

Revision ID: v3342_service_charges
Revises: v3341_leasing_module
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v3342_service_charges"
down_revision: str | Sequence[str] | None = "v3341_leasing_module"
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


def _fk(name: str, target: str, ondelete: str = "CASCADE") -> sa.Column:
    return sa.Column(name, GUID(), sa.ForeignKey(target, ondelete=ondelete), nullable=False)


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "oe_service_charges_association" not in tables:
        op.create_table(
            "oe_service_charges_association",
            *_base(),
            _fk("project_id", "oe_projects_project.id"),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("legal_entity_id", GUID(), nullable=True),
            sa.Column("registration", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("fiscal_year_start_month", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("project_id", "name", name="uq_svcchg_association_project_name"),
        )
        op.create_index(
            "ix_oe_service_charges_association_project_id", "oe_service_charges_association", ["project_id"]
        )
        op.create_index(
            "ix_oe_service_charges_association_legal_entity_id", "oe_service_charges_association", ["legal_entity_id"]
        )
    if "oe_service_charges_key" not in tables:
        op.create_table(
            "oe_service_charges_key",
            *_base(),
            _fk("association_id", "oe_service_charges_association.id"),
            sa.Column("project_id", GUID(), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("method", sa.String(10), nullable=False, server_default="permille"),
            sa.UniqueConstraint("association_id", "name", name="uq_svcchg_key_association_name"),
        )
        op.create_index("ix_oe_service_charges_key_association_id", "oe_service_charges_key", ["association_id"])
        op.create_index("ix_oe_service_charges_key_project_id", "oe_service_charges_key", ["project_id"])
    if "oe_service_charges_key_line" not in tables:
        op.create_table(
            "oe_service_charges_key_line",
            *_base(),
            _fk("key_id", "oe_service_charges_key.id"),
            sa.Column("unit_ref", sa.String(64), nullable=False),
            sa.Column("unit_label", sa.String(255), nullable=False, server_default=""),
            sa.Column("share", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("payer_contact_id", sa.String(36), nullable=True),
            sa.UniqueConstraint("key_id", "unit_ref", name="uq_svcchg_key_line_unit"),
        )
        op.create_index("ix_oe_service_charges_key_line_key_id", "oe_service_charges_key_line", ["key_id"])
    if "oe_service_charges_budget" not in tables:
        op.create_table(
            "oe_service_charges_budget",
            *_base(),
            _fk("association_id", "oe_service_charges_association.id"),
            sa.Column("project_id", GUID(), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
            sa.Column("demand_frequency", sa.String(12), nullable=False, server_default="quarterly"),
            sa.Column("default_key_id", GUID(), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("approved_by", sa.String(36), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.UniqueConstraint("association_id", "year", name="uq_svcchg_budget_association_year"),
        )
        op.create_index("ix_oe_service_charges_budget_association_id", "oe_service_charges_budget", ["association_id"])
        op.create_index("ix_oe_service_charges_budget_project_id", "oe_service_charges_budget", ["project_id"])
    if "oe_service_charges_budget_line" not in tables:
        op.create_table(
            "oe_service_charges_budget_line",
            *_base(),
            _fk("budget_id", "oe_service_charges_budget.id"),
            sa.Column("category", sa.String(100), nullable=False),
            sa.Column("description", sa.String(500), nullable=False, server_default=""),
            _money("amount"),
            _fk("key_id", "oe_service_charges_key.id", "RESTRICT"),
            sa.UniqueConstraint("budget_id", "category", name="uq_svcchg_budget_line_category"),
        )
        op.create_index("ix_oe_service_charges_budget_line_budget_id", "oe_service_charges_budget_line", ["budget_id"])
        op.create_index("ix_oe_service_charges_budget_line_key_id", "oe_service_charges_budget_line", ["key_id"])
    if "oe_service_charges_demand" not in tables:
        op.create_table(
            "oe_service_charges_demand",
            *_base(),
            _fk("budget_id", "oe_service_charges_budget.id"),
            sa.Column("project_id", GUID(), nullable=False),
            sa.Column("unit_ref", sa.String(64), nullable=False),
            sa.Column("period", sa.Integer(), nullable=False),
            sa.Column("issue_date", sa.Date(), nullable=False),
            _money("amount"),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("payer_contact_id", sa.String(36), nullable=True),
            sa.Column("invoice_id", GUID(), nullable=True),
            sa.UniqueConstraint("budget_id", "unit_ref", "period", name="uq_svcchg_demand_unit_period"),
        )
        op.create_index("ix_oe_service_charges_demand_budget_id", "oe_service_charges_demand", ["budget_id"])
        op.create_index("ix_oe_service_charges_demand_project_id", "oe_service_charges_demand", ["project_id"])
        op.create_index("ix_oe_service_charges_demand_invoice_id", "oe_service_charges_demand", ["invoice_id"])
    if "oe_service_charges_reconciliation" not in tables:
        op.create_table(
            "oe_service_charges_reconciliation",
            *_base(),
            _fk("budget_id", "oe_service_charges_budget.id"),
            sa.Column("project_id", GUID(), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
            sa.Column("actual_by_category", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("unit_balances", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("unallocated", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("sources", sa.JSON(), nullable=False, server_default="[]"),
            _money("total_actual"),
            _money("total_demanded"),
            sa.Column("posted_invoice_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("posted_credit_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("posted_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("budget_id", name="uq_svcchg_reconciliation_budget"),
        )
        op.create_index(
            "ix_oe_service_charges_reconciliation_budget_id", "oe_service_charges_reconciliation", ["budget_id"]
        )
        op.create_index(
            "ix_oe_service_charges_reconciliation_project_id", "oe_service_charges_reconciliation", ["project_id"]
        )


def downgrade() -> None:
    for table in (
        "oe_service_charges_reconciliation",
        "oe_service_charges_demand",
        "oe_service_charges_budget_line",
        "oe_service_charges_budget",
        "oe_service_charges_key_line",
        "oe_service_charges_key",
        "oe_service_charges_association",
    ):
        op.drop_table(table)
