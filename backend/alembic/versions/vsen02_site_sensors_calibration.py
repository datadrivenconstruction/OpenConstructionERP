# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""site_sensors: equivalent age, calibration cubes, noise zones, vibration classes, strike reasons.

Mix: ``method``, ``activation_energy_kj_mol``, ``reference_temp_c``, ``fit_r2``,
``calibrated_min`` and ``calibrated_max``. New table ``oe_site_sensors_calibration``.
Device: ``noise_zone``, ``building_class``, ``frequency_band``. Reading:
``frequency_hz``. Strip: ``strike_reason``, ``struck_by``. Every column is
nullable or carries a server default, so the boot heal adds the same columns
from the ORM. Additive and idempotent (inspector-guarded).

Revision ID: vsen02_site_sensors_calibration
Revises: voff01_customer_offers
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsen02_site_sensors_calibration"
down_revision: str | Sequence[str] | None = "voff01_customer_offers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MIX = "oe_site_sensors_mix"
_DEVICE = "oe_site_sensors_device"
_READING = "oe_site_sensors_reading"
_STRIP = "oe_site_sensors_strip"
_CAL = "oe_site_sensors_calibration"


def _columns() -> dict[str, list[sa.Column]]:
    return {
        _MIX: [
            sa.Column("method", sa.String(20), nullable=False, server_default="nurse_saul"),
            sa.Column("activation_energy_kj_mol", sa.Numeric(6, 2), nullable=False, server_default="40"),
            sa.Column("reference_temp_c", sa.Numeric(5, 2), nullable=False, server_default="20"),
            sa.Column("fit_r2", sa.Float(), nullable=True),
            sa.Column("calibrated_min", sa.Float(), nullable=True),
            sa.Column("calibrated_max", sa.Float(), nullable=True),
        ],
        _DEVICE: [
            sa.Column("noise_zone", sa.String(4), nullable=False, server_default=""),
            sa.Column("building_class", sa.String(4), nullable=False, server_default=""),
            sa.Column("frequency_band", sa.String(10), nullable=False, server_default=""),
        ],
        _READING: [sa.Column("frequency_hz", sa.Float(), nullable=True)],
        _STRIP: [
            sa.Column("strike_reason", sa.Text(), nullable=True),
            sa.Column("struck_by", sa.String(36), nullable=True),
        ],
    }


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for table, cols in _columns().items():
        if table not in tables:
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        for col in cols:
            if col.name not in have:
                op.add_column(table, col)
    if _CAL not in tables and _MIX in tables:
        op.create_table(
            _CAL,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("mix_id", sa.String(36), sa.ForeignKey(f"{_MIX}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("maturity_index", sa.Float(), nullable=False),
            sa.Column("strength_mpa", sa.Numeric(8, 2), nullable=False),
            sa.Column("age_hours", sa.Float(), nullable=True),
            sa.Column("note", sa.String(200), nullable=False, server_default=""),
        )
        op.create_index("ix_oe_site_sensors_calibration_mix_id", _CAL, ["mix_id"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if _CAL in tables:
        op.drop_table(_CAL)
    for table, cols in _columns().items():
        if table not in tables:
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        with op.batch_alter_table(table) as b:
            for col in cols:
                if col.name in have:
                    b.drop_column(col.name)
