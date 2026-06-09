# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""QA hardening - numbering columns and per-project unique constraints.

Adds the integrity guards behind the 2026-06-09 module-logic QA wave:

    oe_procurement_requisition  - new req_number column + unique(project_id, req_number)
    oe_approval_routes_step     - new required_approver_count column
    oe_correspondence_correspondence - unique(project_id, reference_number)
    oe_ncr_ncr                  - unique(project_id, ncr_number)
    oe_safety_incident          - unique(project_id, incident_number)
    oe_safety_observation       - unique(project_id, observation_number)
    oe_inspections_inspection   - unique(project_id, inspection_number)

The embedded PostgreSQL runtime materialises the schema via ``create_all`` from
the models at startup, so this migration is for external-PostgreSQL deployments
that manage schema with Alembic. Every change is guarded with an existence
check so a re-run, or a DB the runtime already auto-created, is a no-op.
PostgreSQL-only - no SQLite shims.

Revision ID: v3173_qa_hardening
Revises: v3172_closeout_init
Create Date: 2026-06-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v3173_qa_hardening"
down_revision = "v3172_closeout_init"
branch_labels = None
depends_on = None


# (constraint name, table, columns)
_UNIQUES = [
    (
        "uq_procurement_req_project_number",
        "oe_procurement_requisition",
        ["project_id", "req_number"],
    ),
    (
        "uq_oe_correspondence_correspondence_project_reference",
        "oe_correspondence_correspondence",
        ["project_id", "reference_number"],
    ),
    ("uq_oe_ncr_ncr_project_number", "oe_ncr_ncr", ["project_id", "ncr_number"]),
    (
        "uq_oe_safety_incident_project_number",
        "oe_safety_incident",
        ["project_id", "incident_number"],
    ),
    (
        "uq_oe_safety_observation_project_number",
        "oe_safety_observation",
        ["project_id", "observation_number"],
    ),
    (
        "uq_oe_inspections_inspection_project_number",
        "oe_inspections_inspection",
        ["project_id", "inspection_number"],
    ),
]

# (table, column name, column factory)
_COLUMNS = [
    ("oe_procurement_requisition", "req_number", lambda: sa.Column("req_number", sa.String(length=50), nullable=True)),
    ("oe_approval_routes_step", "required_approver_count", lambda: sa.Column("required_approver_count", sa.Integer(), nullable=True)),
]


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def _has_unique(table: str, name: str) -> bool:
    if not _has_table(table):
        return False
    existing = {uc.get("name") for uc in sa.inspect(op.get_bind()).get_unique_constraints(table)}
    return name in existing


def upgrade() -> None:
    for table, column, factory in _COLUMNS:
        if _has_table(table) and not _has_column(table, column):
            op.add_column(table, factory())
    for name, table, columns in _UNIQUES:
        if _has_table(table) and not _has_unique(table, name):
            op.create_unique_constraint(name, table, columns)


def downgrade() -> None:
    for name, table, _columns in _UNIQUES:
        if _has_unique(table, name):
            op.drop_constraint(name, table, type_="unique")
    for table, column, _factory in _COLUMNS:
        if _has_column(table, column):
            op.drop_column(table, column)
