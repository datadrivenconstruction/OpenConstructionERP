# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""budget ledger: transfers, budget modifications, audit

Creates ``oe_costmodel_budget_transfer`` with its legs, ``oe_costmodel_budget_modification``
and ``oe_costmodel_budget_ledger_audit``.

Revision ID: vbm01_budget_ledger
Revises: vev01_event_effect
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vbm01_budget_ledger"
down_revision: str | Sequence[str] | None = "vev01_event_effect"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRANSFER = "oe_costmodel_budget_transfer"
_LEG = "oe_costmodel_budget_transfer_leg"
_MOD = "oe_costmodel_budget_modification"
_AUDIT = "oe_costmodel_budget_ledger_audit"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _project() -> sa.Column:
    return sa.Column(
        "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )


def _decision() -> list[sa.Column]:
    return [
        sa.Column("requested_by", sa.String(36), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(36), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=False, server_default=""),
    ]


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _TRANSFER not in tables:
        op.create_table(
            _TRANSFER,
            *_base(),
            _project(),
            sa.Column("code", sa.String(20), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            *_decision(),
            sa.UniqueConstraint("project_id", "code", name="uq_costmodel_budget_transfer_code"),
        )
        op.create_index(f"ix_{_TRANSFER}_project_id", _TRANSFER, ["project_id"])
    if _LEG not in tables:
        op.create_table(
            _LEG,
            *_base(),
            sa.Column(
                "transfer_id", sa.String(36), sa.ForeignKey(f"{_TRANSFER}.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column(
                "cost_line_id",
                sa.String(36),
                sa.ForeignKey("oe_costmodel_cost_line.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        )
        op.create_index(f"ix_{_LEG}_transfer_id", _LEG, ["transfer_id"])
        op.create_index(f"ix_{_LEG}_cost_line_id", _LEG, ["cost_line_id"])
    if _MOD not in tables:
        op.create_table(
            _MOD,
            *_base(),
            _project(),
            sa.Column("code", sa.String(20), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
            sa.Column(
                "cost_line_id",
                sa.String(36),
                sa.ForeignKey("oe_costmodel_cost_line.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("approval_ref", sa.String(200), nullable=False, server_default=""),
            *_decision(),
            sa.UniqueConstraint("project_id", "code", name="uq_costmodel_budget_modification_code"),
        )
        op.create_index(f"ix_{_MOD}_project_id", _MOD, ["project_id"])
        op.create_index(f"ix_{_MOD}_cost_line_id", _MOD, ["cost_line_id"])
    if _AUDIT not in tables:
        op.create_table(
            _AUDIT,
            *_base(),
            _project(),
            sa.Column("entity_kind", sa.String(12), nullable=False),
            sa.Column("entity_id", sa.String(36), nullable=False),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column("from_status", sa.String(12), nullable=False, server_default=""),
            sa.Column("to_status", sa.String(12), nullable=False, server_default=""),
            sa.Column("actor", sa.String(36), nullable=True),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
        )
        op.create_index(f"ix_{_AUDIT}_project_id", _AUDIT, ["project_id"])
        op.create_index("ix_costmodel_budget_audit_entity", _AUDIT, ["entity_kind", "entity_id"])


def downgrade() -> None:
    for table in (_AUDIT, _MOD, _LEG, _TRANSFER):
        op.drop_table(table)
