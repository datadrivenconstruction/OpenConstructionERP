# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""procurement concept - frozen rule snapshots and rule overrides.

Two new tables, nothing existing touched. A snapshot is the record of the rules
evaluated when a package's procedure was set (rule ids, sources, effective
dates, inputs, result) and is never updated; an override is a person's
reasoned change of one rule outcome of a snapshot. Both CASCADE with the
project. Every step is inspector-guarded.

Revision ID: v200_procurement_rule_snapshot
Revises: v199_subcontractor_contact_link
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v200_procurement_rule_snapshot"
down_revision: str | Sequence[str] | None = "v199_subcontractor_contact_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SNAPSHOT = "oe_procurement_concept_rule_snapshot"
_OVERRIDE = "oe_procurement_concept_rule_override"
_PROJECT = "oe_projects_project.id"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _SNAPSHOT not in tables:
        op.create_table(
            _SNAPSHOT,
            *_base(),
            sa.Column(
                "project_id",
                GUID(),
                sa.ForeignKey(_PROJECT, ondelete="CASCADE", name="fk_oe_pcc_snapshot_project"),
                nullable=False,
            ),
            sa.Column("package_id", GUID(), nullable=False),
            sa.Column("procedure_code", sa.String(64), nullable=False),
            sa.Column("catalogue_source", sa.String(20), nullable=False),
            sa.Column("catalogue_id", sa.String(64), nullable=False),
            sa.Column("catalogue_version", sa.Integer(), nullable=False),
            sa.Column("checked_on", sa.String(40), nullable=False),
            sa.Column("inputs", sa.JSON(), nullable=False),
            sa.Column("rules", sa.JSON(), nullable=False),
            sa.Column("result", sa.JSON(), nullable=False),
            sa.Column("digest", sa.String(64), nullable=False),
            sa.Column("taken_by", GUID(), nullable=True),
        )
        op.create_index("ix_oe_pcc_snapshot_package", _SNAPSHOT, ["project_id", "package_id"])
    if _OVERRIDE not in tables:
        op.create_table(
            _OVERRIDE,
            *_base(),
            sa.Column(
                "project_id",
                GUID(),
                sa.ForeignKey(_PROJECT, ondelete="CASCADE", name="fk_oe_pcc_override_project"),
                nullable=False,
            ),
            sa.Column(
                "snapshot_id",
                GUID(),
                sa.ForeignKey(f"{_SNAPSHOT}.id", ondelete="CASCADE", name="fk_oe_pcc_override_snapshot"),
                nullable=False,
            ),
            sa.Column("rule_code", sa.String(64), nullable=False),
            sa.Column("original_outcome", sa.String(20), nullable=False),
            sa.Column("override_outcome", sa.String(20), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("overridden_by", GUID(), nullable=True),
            sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_oe_pcc_override_snapshot", _OVERRIDE, ["snapshot_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name in (_OVERRIDE, _SNAPSHOT):
        if name in tables:
            op.drop_table(name)
