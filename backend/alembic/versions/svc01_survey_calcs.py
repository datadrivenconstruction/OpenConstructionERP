# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""survey calculations: COGO audit trail, field traverse, level book, parcel subdivision, corners

Additive nullable or defaulted columns only, so a deploy that heals its schema
at boot picks them up without ``alembic upgrade``:

* ``oe_survey_point.method`` / ``inputs``: how a computed point was made.
* ``oe_survey_profile.angular_k_sec``: k of the angular closure k * sqrt(n).
* ``oe_survey_traverse``: angular misclosure, its k and allowance, angle count,
  and the field observations of the reduction.
* ``oe_land_parcel.parent_ids`` / ``superseded``: split and merge lineage.
* ``oe_land_parcel_point.corner_status`` / ``accuracy_class``: corner register.

Revision ID: svc01_survey_calcs
Revises: awx01_award_exchange
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "svc01_survey_calcs"
down_revision: str | Sequence[str] | None = "awx01_award_exchange"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> dict[str, list[sa.Column]]:
    return {
        "oe_survey_point": [
            sa.Column("method", sa.String(32), nullable=False, server_default=""),
            sa.Column("inputs", sa.JSON(), nullable=True),
        ],
        "oe_survey_profile": [sa.Column("angular_k_sec", sa.Numeric(8, 2), nullable=True)],
        "oe_survey_traverse": [
            sa.Column("angle_count", sa.Integer(), nullable=True),
            sa.Column("ang_misclosure_sec", sa.Numeric(10, 2), nullable=True),
            sa.Column("ang_k_sec", sa.Numeric(8, 2), nullable=True),
            sa.Column("ang_allowed_sec", sa.Numeric(10, 2), nullable=True),
            sa.Column("observations", sa.JSON(), nullable=True),
        ],
        "oe_land_parcel": [
            sa.Column("parent_ids", sa.JSON(), nullable=True),
            sa.Column("superseded", sa.Boolean(), nullable=False, server_default=sa.false()),
        ],
        "oe_land_parcel_point": [
            sa.Column("corner_status", sa.String(20), nullable=False, server_default=""),
            sa.Column("accuracy_class", sa.String(60), nullable=False, server_default=""),
        ],
    }


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table, cols in _columns().items():
        if table not in tables:
            continue
        have = {c["name"] for c in inspector.get_columns(table)}
        for col in cols:
            if col.name not in have:
                op.add_column(table, col)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table, cols in _columns().items():
        if table not in tables:
            continue
        have = {c["name"] for c in inspector.get_columns(table)}
        for col in reversed(cols):
            if col.name in have:
                op.drop_column(table, col.name)
