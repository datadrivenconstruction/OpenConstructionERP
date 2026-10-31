# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""estimate_checks: workspace settings, user display preference, accepted findings

Creates ``oe_estchk_settings`` (one row per workspace), ``oe_estchk_user_pref``
(per-user display mode) and ``oe_estchk_acceptance`` (a finding accepted with a
reason, author and time). Ratings are computed on demand and never stored.

Revision ID: v3350_estimate_checks
Revises: v3327_accounting_sync
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v3350_estimate_checks"
down_revision: str | Sequence[str] | None = "v3327_accounting_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SET = "oe_estchk_settings"
_PREF = "oe_estchk_user_pref"
_ACC = "oe_estchk_acceptance"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _SET not in tables:
        op.create_table(
            _SET,
            *_base(),
            sa.Column("tenant_key", sa.String(64), nullable=False, server_default=""),
            sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("updated_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("tenant_key", name="uq_estchk_settings_tenant"),
        )
    if _PREF not in tables:
        op.create_table(
            _PREF,
            *_base(),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("display_mode", sa.String(10), nullable=False, server_default="badge"),
            sa.UniqueConstraint("user_id", name="uq_estchk_user_pref_user"),
        )
    if _ACC not in tables:
        op.create_table(
            _ACC,
            *_base(),
            sa.Column("boq_id", sa.String(36), nullable=False),
            sa.Column("kpi_id", sa.String(60), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("status_at_accept", sa.String(10), nullable=False, server_default="suspect"),
            sa.Column("value_at_accept", sa.String(50), nullable=True),
            sa.Column("accepted_by", sa.String(36), nullable=False),
            sa.UniqueConstraint("boq_id", "kpi_id", name="uq_estchk_acceptance_boq_kpi"),
        )
        op.create_index("ix_oe_estchk_acceptance_boq_id", _ACC, ["boq_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _ACC in tables:
        op.drop_index("ix_oe_estchk_acceptance_boq_id", table_name=_ACC)
        op.drop_table(_ACC)
    for name in (_PREF, _SET):
        if name in tables:
            op.drop_table(name)
