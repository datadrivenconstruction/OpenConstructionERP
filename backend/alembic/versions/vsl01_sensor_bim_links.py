# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""site_sensors BIM link - the model and element a device or a formwork strike belongs to.

Adds nullable ``bim_model_id`` and ``bim_element_id`` to ``oe_site_sensors_device`` and
``oe_site_sensors_strip``. Additive only, inspector-guarded, so a database whose columns
``create_all`` already built is a no-op.

Revision ID: vsl01_sensor_bim_links
Revises: vsen02_site_sensors_calibration
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsl01_sensor_bim_links"
down_revision: str | Sequence[str] | None = "vsen02_site_sensors_calibration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("oe_site_sensors_device", "oe_site_sensors_strip")
_COLUMNS = ("bim_model_id", "bim_element_id")


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    for table in _TABLES:
        have = _columns(table)
        if not have:
            continue
        for column in _COLUMNS:
            if column not in have:
                op.add_column(table, sa.Column(column, sa.String(36), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        have = _columns(table)
        for column in _COLUMNS:
            if column in have:
                op.drop_column(table, column)
