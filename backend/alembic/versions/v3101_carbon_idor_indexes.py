# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3101 — carbon (project_id, scope) covering indexes.

Round-5 carbon-footprint IDOR closure added a project-access gate on
22 endpoints. Each endpoint now filters by ``project_id`` server-side
(replacing the URL-trusted lookup pattern). The covering indexes here
keep that filter at index-scan cost as the carbon-inventory tables grow.

Strictly-additive + inspector-guarded.

Revision ID: v3101_carbon
Revises: v3100_sched
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3101_carbon"
down_revision: Union[str, Sequence[str], None] = "v3100_sched"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, [columns], index_name)
_INDEXES: list[tuple[str, list[str], str]] = [
    ("oe_carbon_scope1_emission", ["project_id"], "ix_carbon_scope1_project"),
    ("oe_carbon_scope2_emission", ["project_id"], "ix_carbon_scope2_project"),
    ("oe_carbon_scope3_emission", ["project_id"], "ix_carbon_scope3_project"),
    ("oe_carbon_emission_factor", ["project_id"], "ix_carbon_factor_project"),
    ("oe_carbon_reduction_target", ["project_id"], "ix_carbon_target_project"),
    ("oe_carbon_offset_purchase", ["project_id"], "ix_carbon_offset_project"),
    ("oe_carbon_report", ["project_id"], "ix_carbon_report_project"),
]


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def _has_columns(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    cols: list[str],
) -> bool:
    if table not in inspector.get_table_names():
        return False
    present = {c["name"] for c in inspector.get_columns(table)}
    return all(c in present for c in cols)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, cols, name in _INDEXES:
        if (
            table in inspector.get_table_names()
            and _has_columns(inspector, table, cols)
            and not _has_index(inspector, table, name)
        ):
            op.create_index(name, table, cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, _cols, name in _INDEXES:
        if _has_index(inspector, table, name):
            op.drop_index(name, table_name=table)
