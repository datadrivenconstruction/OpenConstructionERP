# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""site_sensors custom sensors and manual readings.

Adds to ``oe_site_sensors_device`` the lower limit, the limit note (source or override
reason), a rolling-mean window and the record-only flag; to ``oe_site_sensors_reading``
the source (device, manual, import), who entered it and a note; and creates
``oe_site_sensors_reading_audit``. Additive only, inspector-guarded, so a database whose
columns ``create_all`` already built is a no-op.

Revision ID: vsm01_sensor_manual_readings
Revises: vsl01_sensor_bim_links
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsm01_sensor_manual_readings"
down_revision: str | Sequence[str] | None = "vsl01_sensor_bim_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEVICE = "oe_site_sensors_device"
_READING = "oe_site_sensors_reading"
_AUDIT = "oe_site_sensors_reading_audit"


def _device_columns() -> list[sa.Column]:
    return [
        sa.Column("lower_limit", sa.Numeric(14, 4), nullable=True),
        sa.Column("limit_note", sa.String(300), nullable=False, server_default=""),
        sa.Column("rolling_mean_hours", sa.Float(), nullable=True),
        sa.Column("record_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _reading_columns() -> list[sa.Column]:
    return [
        sa.Column("source", sa.String(10), nullable=False, server_default="device"),
        sa.Column("entered_by", sa.String(36), nullable=True),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
    ]


def _have(table: str) -> set[str] | None:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return None
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    for table, columns in ((_DEVICE, _device_columns()), (_READING, _reading_columns())):
        have = _have(table)
        if have is None:
            continue
        for column in columns:
            if column.name not in have:
                op.add_column(table, column)
    if _have(_AUDIT) is None and _have(_DEVICE) is not None:
        op.create_table(
            _AUDIT,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("device_id", sa.String(36), sa.ForeignKey(f"{_DEVICE}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("action", sa.String(10), nullable=False),
            sa.Column("value_before", sa.Float(), nullable=True),
            sa.Column("value_after", sa.Float(), nullable=True),
            sa.Column("note", sa.String(500), nullable=False, server_default=""),
            sa.Column("user_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_oe_site_sensors_reading_audit_device", _AUDIT, ["device_id", "recorded_at"])


def downgrade() -> None:
    if _have(_AUDIT) is not None:
        op.drop_table(_AUDIT)
    for table, columns in ((_DEVICE, _device_columns()), (_READING, _reading_columns())):
        have = _have(table) or set()
        for column in columns:
            if column.name in have:
                op.drop_column(table, column.name)
