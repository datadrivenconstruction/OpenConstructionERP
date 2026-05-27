# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""moc: Management-of-Change module bootstrap.

Two tables for the new Management of Change (MoC) module
(deep-improve wave, task #180 — Variations + ChangeOrders + MoC):

* ``oe_moc_entry``   — MoC header: proposed change to engineering scope,
                       safety procedure, design or contract baseline.
* ``oe_moc_impact``  — Impact-assessment line items attached to a MoC entry.

State machine (OSHA PSM / ISO 55000 / IEC 61511):
    proposed -> reviewed -> accepted -> implemented
              ↘ declined ↗

Idempotent (checks ``inspector.get_table_names``). Fresh installs that boot
the app first will already have these tables from
``Base.metadata.create_all`` — running this migration afterwards is a no-op.
Every NOT NULL column carries a ``server_default`` so ``create_all`` works
too (Python ``default=`` is ignored by ``create_all``).

Revision ID: v3138_moc_init
Revises: v3137_wave23_currency_parameterization
Create Date: 2026-05-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3138_moc_init"
down_revision: Union[str, Sequence[str], None] = "v3137_wave23_currency_parameterization"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENTRY = "oe_moc_entry"
_IMPACT = "oe_moc_impact"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── oe_moc_entry ──────────────────────────────────────────────────
    if not _has_table(inspector, _ENTRY):
        op.create_table(
            _ENTRY,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("code", sa.String(50), nullable=False, server_default=""),
            sa.Column("title", sa.String(500), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "change_category",
                sa.String(40),
                nullable=False,
                server_default="engineering",
            ),
            sa.Column(
                "risk_level",
                sa.String(20),
                nullable=False,
                server_default="medium",
            ),
            sa.Column("proposed_by", sa.String(36), nullable=True),
            sa.Column("proposed_at", sa.String(40), nullable=True),
            sa.Column("reviewed_by", sa.String(36), nullable=True),
            sa.Column("reviewed_at", sa.String(40), nullable=True),
            sa.Column("review_notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("decided_by", sa.String(36), nullable=True),
            sa.Column("decided_at", sa.String(40), nullable=True),
            sa.Column("decision_notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("implemented_by", sa.String(36), nullable=True),
            sa.Column("implemented_at", sa.String(40), nullable=True),
            sa.Column("cost_impact", sa.String(20), nullable=False, server_default="0"),
            sa.Column(
                "schedule_delta_days",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column(
                "status",
                sa.String(40),
                nullable=False,
                server_default="proposed",
            ),
            sa.Column("variation_request_id", sa.String(36), nullable=True),
            sa.Column("variation_order_id", sa.String(36), nullable=True),
            sa.Column("change_order_id", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint(
                "project_id",
                "code",
                name="uq_oe_moc_entry_project_code",
            ),
        )
        op.create_index(f"ix_{_ENTRY}_project_id", _ENTRY, ["project_id"])
        op.create_index(f"ix_{_ENTRY}_status", _ENTRY, ["status"])
        op.create_index(
            f"ix_{_ENTRY}_variation_request_id",
            _ENTRY,
            ["variation_request_id"],
        )
        op.create_index(
            f"ix_{_ENTRY}_variation_order_id",
            _ENTRY,
            ["variation_order_id"],
        )
        op.create_index(
            f"ix_{_ENTRY}_change_order_id",
            _ENTRY,
            ["change_order_id"],
        )

    # ── oe_moc_impact ─────────────────────────────────────────────────
    if not _has_table(inspector, _IMPACT):
        op.create_table(
            _IMPACT,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "moc_entry_id",
                sa.String(36),
                sa.ForeignKey("oe_moc_entry.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "impact_area",
                sa.String(40),
                nullable=False,
                server_default="cost",
            ),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "severity",
                sa.String(20),
                nullable=False,
                server_default="medium",
            ),
            sa.Column("cost_impact", sa.String(20), nullable=False, server_default="0"),
            sa.Column(
                "schedule_delta_days",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("mitigation", sa.Text(), nullable=False, server_default=""),
        )
        op.create_index(f"ix_{_IMPACT}_moc_entry_id", _IMPACT, ["moc_entry_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _IMPACT):
        op.drop_index(f"ix_{_IMPACT}_moc_entry_id", table_name=_IMPACT)
        op.drop_table(_IMPACT)

    if _has_table(inspector, _ENTRY):
        op.drop_index(f"ix_{_ENTRY}_change_order_id", table_name=_ENTRY)
        op.drop_index(f"ix_{_ENTRY}_variation_order_id", table_name=_ENTRY)
        op.drop_index(f"ix_{_ENTRY}_variation_request_id", table_name=_ENTRY)
        op.drop_index(f"ix_{_ENTRY}_status", table_name=_ENTRY)
        op.drop_index(f"ix_{_ENTRY}_project_id", table_name=_ENTRY)
        op.drop_table(_ENTRY)
