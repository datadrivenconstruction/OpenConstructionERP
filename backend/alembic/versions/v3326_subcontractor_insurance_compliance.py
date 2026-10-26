# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""subcontractors: mandatory insurance certificates and the payment override log

Adds ``is_mandatory``, ``policy_number``, ``coverage_amount`` and
``coverage_currency`` to ``oe_subcontractors_certificate``, and creates
``oe_subcontractors_payment_compliance_override``: one append-only row per
manager decision to pay despite lapsed mandatory insurance, with the reason
and the lapses it covered.

Existing certificates stay non-mandatory, so no payment that flows today is
blocked by this revision.

Revision ID: v3326_subcontractor_insurance_compliance
Revises: v3325_lps_constraint_links_commitment_trade
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v3326_subcontractor_insurance_compliance"
down_revision: str | Sequence[str] | None = "v3325_lps_constraint_links_commitment_trade"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CERT = "oe_subcontractors_certificate"
_OVERRIDE = "oe_subcontractors_payment_compliance_override"
_PAY_APP = "oe_subcontractors_payment_application"


def _cert_columns() -> list[sa.Column]:
    return [
        sa.Column("is_mandatory", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("policy_number", sa.String(120), nullable=True),
        sa.Column("coverage_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("coverage_currency", sa.String(3), nullable=True),
    ]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if _CERT in tables:
        have = {c["name"] for c in inspector.get_columns(_CERT)}
        for col in _cert_columns():
            if col.name not in have:
                op.add_column(_CERT, col)
    if _OVERRIDE not in tables:
        op.create_table(
            _OVERRIDE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "payment_application_id",
                sa.String(36),
                sa.ForeignKey(f"{_PAY_APP}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("subcontractor_id", sa.String(36), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("covered_reasons", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("overridden_by", sa.String(36), nullable=True),
            sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index(f"ix_{_OVERRIDE}_payment_application_id", _OVERRIDE, ["payment_application_id"])
        op.create_index(f"ix_{_OVERRIDE}_subcontractor_id", _OVERRIDE, ["subcontractor_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if _OVERRIDE in tables:
        op.drop_table(_OVERRIDE)
    if _CERT in tables:
        have = {c["name"] for c in inspector.get_columns(_CERT)}
        for col in _cert_columns():
            if col.name in have:
                op.drop_column(_CERT, col.name)
