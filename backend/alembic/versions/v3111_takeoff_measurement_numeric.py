# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""takeoff: Float -> Numeric(18, 6) for measurement columns.

Round-6 audit flagged ``oe_takeoff_measurement.measurement_value``,
``depth``, ``volume`` and ``perimeter`` as the last places in the PDF
takeoff path still stored as ``Float`` (IEEE-754 double precision).
Every one of these columns feeds BOQ totals via the link-to-boq
endpoint, so binary float drift accumulated across (points × scale →
measurement → unit_rate × measurement) was leaking into the money
column. The sibling ``dwg_takeoff.DwgAnnotation.measurement_value``
moved to ``Numeric(18, 6)`` in v3097_dwg_takeoff_decimal_quantities
back in Round 3 — this migration brings the PDF surface up to the
same precision regime.

The four affected columns:

* ``oe_takeoff_measurement.measurement_value`` Float -> Numeric(18, 6)
* ``oe_takeoff_measurement.depth``             Float -> Numeric(18, 6)
* ``oe_takeoff_measurement.volume``            Float -> Numeric(18, 6)
* ``oe_takeoff_measurement.perimeter``         Float -> Numeric(18, 6)

``scale_pixels_per_unit`` stays Float — it's a UI calibration ratio
used as a divisor, never persisted into a money rollup, and migrating
it would force every existing PDF takeoff session in production to
be re-calibrated for zero precision gain.

Idempotent: inspects the live column type and only alters when the
column is still a binary float family. Re-running on a partially
migrated DB is a no-op. SQLite stores both Float and Numeric as the
``REAL`` affinity, so the alter is essentially a metadata change
there; on Postgres it rewrites the column in place.

Revision ID: v3107_takeoff_measurement_numeric
Revises: v3106_geo_hub_init
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3111_takeoff_measurement_numeric"
down_revision: Union[str, Sequence[str], None] = "v3110_propdev_snag_buyer_cost_photos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, precision, scale, nullable)
_NUMERIC_COLUMNS: tuple[tuple[str, str, int, int, bool], ...] = (
    ("oe_takeoff_measurement", "measurement_value", 18, 6, True),
    ("oe_takeoff_measurement", "depth", 18, 6, True),
    ("oe_takeoff_measurement", "volume", 18, 6, True),
    ("oe_takeoff_measurement", "perimeter", 18, 6, True),
)


def _column_type(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    column: str,
) -> str | None:
    """Return the live column type as a lowercase string, or None."""
    if table not in inspector.get_table_names():
        return None
    for col in inspector.get_columns(table):
        if col["name"] == column:
            return str(col["type"]).lower()
    return None


def _is_float_family(col_type: str | None) -> bool:
    """True if the live column is still a binary-float-affinity type."""
    if not col_type:
        return False
    return any(token in col_type for token in ("float", "real", "double"))


def _is_numeric_family(col_type: str | None) -> bool:
    """True if the live column is already on Numeric/Decimal."""
    if not col_type:
        return False
    return "numeric" in col_type or "decimal" in col_type


def upgrade() -> None:
    """Convert each takeoff measurement column from Float to Numeric.

    Grouped per table inside a single ``batch_alter_table`` so SQLite
    rewrites the table once instead of four times.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    by_table: dict[str, list[tuple[str, int, int, bool]]] = {}
    for table, column, precision, scale, nullable in _NUMERIC_COLUMNS:
        col_type = _column_type(inspector, table, column)
        if col_type is None:
            # Table or column missing — fresh DB picks up the new Numeric
            # type from ``Base.metadata.create_all``.
            continue
        if _is_numeric_family(col_type):
            # Already migrated.
            continue
        if not _is_float_family(col_type):
            # Unknown live type — skip rather than risk a data-losing cast.
            continue
        by_table.setdefault(table, []).append((column, precision, scale, nullable))

    for table, cols in by_table.items():
        with op.batch_alter_table(table) as batch:
            for column, precision, scale, nullable in cols:
                batch.alter_column(
                    column,
                    existing_type=sa.Float(),
                    type_=sa.Numeric(precision, scale),
                    existing_nullable=nullable,
                    postgresql_using=(f"{column}::numeric({precision},{scale})"),
                )


def downgrade() -> None:
    """Revert each column back to Float."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    by_table: dict[str, list[tuple[str, int, int, bool]]] = {}
    for table, column, precision, scale, nullable in _NUMERIC_COLUMNS:
        col_type = _column_type(inspector, table, column)
        if col_type is None:
            continue
        if _is_float_family(col_type):
            continue
        if not _is_numeric_family(col_type):
            continue
        by_table.setdefault(table, []).append((column, precision, scale, nullable))

    for table, cols in by_table.items():
        with op.batch_alter_table(table) as batch:
            for column, precision, scale, nullable in cols:
                batch.alter_column(
                    column,
                    existing_type=sa.Numeric(precision, scale),
                    type_=sa.Float(),
                    existing_nullable=nullable,
                    postgresql_using=f"{column}::double precision",
                )
