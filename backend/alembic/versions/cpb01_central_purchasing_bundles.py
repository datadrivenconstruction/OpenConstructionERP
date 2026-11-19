# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""central purchasing: bundles over several projects, shares, award split

Additive new tables only, so a deploy that heals its schema at boot picks them up
without ``alembic upgrade``. The documents an award drafts are rows of
``oe_contracts_contract`` and ``oe_procurement_po``, which need no DDL.

Revision ID: cpb01_central_purchasing_bundles
Revises: svc01_survey_calcs
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cpb01_central_purchasing_bundles"
down_revision: str | Sequence[str] | None = "svc01_survey_calcs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BUNDLE = "oe_central_purchasing_bundle"
_PROJECT = "oe_central_purchasing_project"
_LINE = "oe_central_purchasing_line"
_SHARE = "oe_central_purchasing_share"
_SPLIT = "oe_central_purchasing_split"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def _fk(column: str, table: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(column, sa.String(36), sa.ForeignKey(f"{table}.id", ondelete="CASCADE"), nullable=nullable)


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if _BUNDLE not in existing:
        op.create_table(
            _BUNDLE,
            *_base(),
            sa.Column("code", sa.String(40), nullable=False),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("kind", sa.String(20), nullable=False, server_default="subcontract"),
            sa.Column("mode", sa.String(30), nullable=False, server_default="per_project_contracts"),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("cost_code_standard", sa.String(40), nullable=True),
            sa.Column("budget_tolerance_pct", sa.Numeric(7, 4), nullable=False, server_default="0"),
            sa.Column("bid_package_id", sa.String(36), nullable=True),
            sa.Column("vendor_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("subcontractor_id", sa.String(36), nullable=True),
            sa.Column("contact_id", sa.String(36), nullable=True),
            sa.Column("discount_pct", sa.Numeric(7, 4), nullable=True),
            sa.Column("lump_sum", sa.Numeric(18, 2), nullable=True),
            sa.Column("awarded_gross", sa.Numeric(18, 2), nullable=True),
            sa.Column("awarded_net", sa.Numeric(18, 2), nullable=True),
            sa.Column("awarded_at", sa.String(40), nullable=True),
            sa.Column("awarded_by", sa.String(36), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint("code", name="uq_oe_central_purchasing_bundle_code"),
        )
        op.create_index(f"ix_{_BUNDLE}_status", _BUNDLE, ["status"])
        op.create_index(f"ix_{_BUNDLE}_bid_package_id", _BUNDLE, ["bid_package_id"])
    if _PROJECT not in existing:
        op.create_table(
            _PROJECT,
            *_base(),
            _fk("bundle_id", _BUNDLE),
            _fk("project_id", "oe_projects_project"),
            sa.Column("legal_entity_id", sa.String(36), nullable=True),
            sa.Column("budget_amount", sa.Numeric(18, 2), nullable=True),
            sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
            sa.UniqueConstraint("bundle_id", "project_id", name="uq_oe_central_purchasing_project_bundle_project"),
        )
        op.create_index(f"ix_{_PROJECT}_bundle_id", _PROJECT, ["bundle_id"])
        op.create_index("ix_oe_central_purchasing_project_project", _PROJECT, ["project_id"])
    if _LINE not in existing:
        op.create_table(
            _LINE,
            *_base(),
            _fk("bundle_id", _BUNDLE),
            sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("code", sa.String(80), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("unit", sa.String(20), nullable=False, server_default=""),
            sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
            sa.Column("unit_rate", sa.Numeric(18, 4), nullable=True),
            sa.Column("cost_code", sa.String(40), nullable=True),
        )
        op.create_index(f"ix_{_LINE}_bundle_id", _LINE, ["bundle_id"])
    if _SHARE not in existing:
        op.create_table(
            _SHARE,
            *_base(),
            _fk("line_id", _LINE),
            _fk("bundle_project_id", _PROJECT),
            sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
            sa.Column("cost_line_id", sa.String(36), nullable=True),
            sa.UniqueConstraint("line_id", "bundle_project_id", name="uq_oe_central_purchasing_share_line_project"),
        )
        op.create_index(f"ix_{_SHARE}_line_id", _SHARE, ["line_id"])
        op.create_index(f"ix_{_SHARE}_bundle_project_id", _SHARE, ["bundle_project_id"])
    if _SPLIT not in existing:
        op.create_table(
            _SPLIT,
            *_base(),
            _fk("bundle_id", _BUNDLE),
            _fk("bundle_project_id", _PROJECT),
            sa.Column("gross", sa.Numeric(18, 2), nullable=False),
            sa.Column("discount", sa.Numeric(18, 2), nullable=False),
            sa.Column("net", sa.Numeric(18, 2), nullable=False),
            sa.Column("document_type", sa.String(30), nullable=False),
            sa.Column("document_id", sa.String(36), nullable=True),
            sa.UniqueConstraint("bundle_project_id", name="uq_oe_central_purchasing_split_project"),
        )
        op.create_index(f"ix_{_SPLIT}_bundle_id", _SPLIT, ["bundle_id"])


def downgrade() -> None:
    for table in (_SPLIT, _SHARE, _LINE, _PROJECT, _BUNDLE):
        op.drop_table(table)
