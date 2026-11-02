# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""change_chain_award: field-event notices, subcontract changes, leveling plugs, package type

Adds the field-event backlink to ``oe_variations_notice``; creates
``oe_subcontractors_change`` (changes to a subcontract agreement linked to the
owner change); adds ``package_type`` to ``oe_bid_management_package`` and the
plug totals to ``oe_bid_management_leveling``; creates
``oe_bid_management_leveling_plug`` (the value put on each gap with its source).

Revision ID: vcc01_change_chain_award
Revises: v3354_owner_schedule
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vcc01_change_chain_award"
down_revision: str | Sequence[str] | None = "v3354_owner_schedule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOTICE = "oe_variations_notice"
_CHANGE = "oe_subcontractors_change"
_PACKAGE = "oe_bid_management_package"
_LEVELING = "oe_bid_management_leveling"
_PLUG = "oe_bid_management_leveling_plug"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _add_missing(table: str, tables: set[str], columns: list[sa.Column]) -> None:
    if table not in tables:
        return
    have = _columns(table)
    for column in columns:
        if column.name not in have:
            op.add_column(table, column)


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    _add_missing(
        _NOTICE,
        tables,
        [
            sa.Column("source_type", sa.String(40), nullable=True),
            sa.Column("source_id", sa.String(36), nullable=True),
            sa.Column("source_ref", sa.String(120), nullable=False, server_default=""),
        ],
    )
    if _NOTICE in tables:
        indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(_NOTICE)}
        if f"ix_{_NOTICE}_source_id" not in indexes:
            op.create_index(f"ix_{_NOTICE}_source_id", _NOTICE, ["source_id"])

    _add_missing(
        _PACKAGE,
        tables,
        [sa.Column("package_type", sa.String(16), nullable=False, server_default="subcontract")],
    )
    _add_missing(
        _LEVELING,
        tables,
        [
            sa.Column("plug_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("plugged_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("gap_lines", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unpriced_gap_lines", sa.Integer(), nullable=False, server_default="0"),
        ],
    )

    if _CHANGE not in tables:
        op.create_table(
            _CHANGE,
            *_base(),
            sa.Column(
                "agreement_id",
                sa.String(36),
                sa.ForeignKey("oe_subcontractors_agreement.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("title", sa.String(500), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("back_to_back", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("owner_change_type", sa.String(32), nullable=True),
            sa.Column("owner_change_id", sa.String(36), nullable=True),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decided_by", sa.String(36), nullable=True),
            sa.Column("decision_note", sa.Text(), nullable=False, server_default=""),
            sa.Column("applied_amount", sa.Numeric(18, 2), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint("agreement_id", "code", name="uq_oe_subcontractors_change_code"),
        )
        for column in ("agreement_id", "project_id", "status", "owner_change_id"):
            op.create_index(f"ix_{_CHANGE}_{column}", _CHANGE, [column])

    if _PLUG not in tables:
        op.create_table(
            _PLUG,
            *_base(),
            sa.Column(
                "comparison_id",
                sa.String(36),
                sa.ForeignKey("oe_bid_management_comparison.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "bidder_id",
                sa.String(36),
                sa.ForeignKey("oe_bid_management_bidder.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "line_item_id",
                sa.String(36),
                sa.ForeignKey("oe_bid_management_line_item.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("source", sa.String(16), nullable=False, server_default="none"),
            sa.Column("reason", sa.String(16), nullable=False, server_default="missing"),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.UniqueConstraint(
                "comparison_id", "bidder_id", "line_item_id", name="uq_oe_bid_management_leveling_plug"
            ),
        )
        for column in ("comparison_id", "bidder_id", "line_item_id"):
            op.create_index(f"ix_{_PLUG}_{column}", _PLUG, [column])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (_PLUG, _CHANGE):
        if table in tables:
            op.drop_table(table)
    for table, names in (
        (_LEVELING, ("plug_total", "plugged_total", "gap_lines", "unpriced_gap_lines")),
        (_PACKAGE, ("package_type",)),
        (_NOTICE, ("source_type", "source_id", "source_ref")),
    ):
        if table not in tables:
            continue
        have = _columns(table)
        with op.batch_alter_table(table) as batch:
            if table == _NOTICE and "source_id" in have:
                batch.drop_index(f"ix_{_NOTICE}_source_id")
            for name in names:
                if name in have:
                    batch.drop_column(name)
