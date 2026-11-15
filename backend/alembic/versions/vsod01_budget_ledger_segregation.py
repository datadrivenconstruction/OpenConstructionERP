# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""budget ledger: segregation of duties setting

Adds ``segregation_of_duties`` (default on) to ``oe_costmodel_cost_control_settings``. While on, the
requester of a budget transfer or modification cannot approve it. A plain column add, safe to stamp:
the setting reads as on when the row or column is absent.

Revision ID: vsod01_budget_ledger_segregation
Revises: vpc01_project_country_from_region
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsod01_budget_ledger_segregation"
down_revision: str | Sequence[str] | None = "vpc01_project_country_from_region"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "oe_costmodel_cost_control_settings"
_C = "segregation_of_duties"


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_T)}
    if _C not in cols:
        op.add_column(_T, sa.Column(_C, sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_T)}
    if _C in cols:
        op.drop_column(_T, _C)
