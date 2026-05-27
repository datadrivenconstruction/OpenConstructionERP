# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""dwg_takeoff: Float -> Numeric for measurement + scale columns.

DXF/DWG takeoff measurements feed directly into BOQ totals via the
``measurement_value`` column on ``oe_dwg_takeoff_annotation`` (and the
``scale_denominator`` / ``scale_override`` / ``thickness`` columns that
the frontend applies before persisting). Storing these as ``Float``
(IEEE-754 double precision) accumulates binary drift on every divide
by the scale denominator — a 1:50 plan scaled and then multiplied by
a unit rate could disagree with the BOQ by a few hundredths of a
cent across a 50-line takeoff. Round 3 Wave-A flagged this as the
last place in the takeoff path still on Float.

This migration converts four columns to ``Numeric``:

* ``oe_dwg_takeoff_annotation.measurement_value``  Float -> Numeric(18, 6)
* ``oe_dwg_takeoff_annotation.scale_override``     Float -> Numeric(10, 6)
* ``oe_dwg_takeoff_annotation.thickness``          Float -> Numeric(10, 6)
* ``oe_dwg_takeoff_drawing.scale_denominator``     Float -> Numeric(10, 6)

Numeric(18, 6) covers every realistic takeoff measurement (km of pipe,
m^2 of slab, kg of rebar) with six fractional digits — well past what
DXF itself stores. Scales and thickness fit comfortably in Numeric(10, 6)
because the schema already caps them at <= 100_000.

Idempotent: inspects the live column type and only alters when the
column is still a binary float family (``float`` / ``real`` / ``double``).
Re-running on a partially migrated DB is a no-op. SQLite stores both
Float and Numeric as the ``REAL`` affinity, so the alter is essentially
a metadata change there; on Postgres it rewrites the column in place.

Revision ID: v3097_dwg_takeoff_decimal_quantities
Revises: v3097_markups_measurement_numeric
Create Date: 2026-05-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3097_dwg_takeoff_decimal_quantities"
# Chained behind the sibling v3097 markups Numeric rewrite so the
# Round-3 Wave-A "Float -> Numeric" sweep stays a single linear chain
# instead of forking into yet another parallel head. The markups
# migration is itself a merge node off both v3096 heads.
down_revision: Union[str, Sequence[str], None] = "v3097_markups_measurement_numeric"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, precision, scale, nullable, server_default)
_NUMERIC_COLUMNS: tuple[tuple[str, str, int, int, bool, str | None], ...] = (
    ("oe_dwg_takeoff_annotation", "measurement_value", 18, 6, True, None),
    ("oe_dwg_takeoff_annotation", "scale_override", 10, 6, True, None),
    ("oe_dwg_takeoff_annotation", "thickness", 10, 6, False, "2.0"),
    ("oe_dwg_takeoff_drawing", "scale_denominator", 10, 6, False, "1.0"),
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
    """Convert each takeoff measurement/scale column from Float to Numeric.

    Grouped per table inside a single ``batch_alter_table`` so SQLite
    rewrites the table once per group instead of four times.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Group rows by table so we can run a single batch_alter_table per
    # table — SQLite rebuilds the table on every batch, so coalescing
    # saves I/O on fresh DBs.
    by_table: dict[str, list[tuple[str, int, int, bool, str | None]]] = {}
    for table, column, precision, scale, nullable, default in _NUMERIC_COLUMNS:
        col_type = _column_type(inspector, table, column)
        if col_type is None:
            # Table or column missing — fresh DB will pick up the new
            # Numeric type from ``Base.metadata.create_all``.
            continue
        if _is_numeric_family(col_type):
            # Already migrated.
            continue
        if not _is_float_family(col_type):
            # Unknown live type (e.g. someone hand-edited the schema) —
            # skip rather than risk a data-losing cast.
            continue
        by_table.setdefault(table, []).append(
            (column, precision, scale, nullable, default),
        )

    for table, cols in by_table.items():
        with op.batch_alter_table(table) as batch:
            for column, precision, scale, nullable, default in cols:
                batch.alter_column(
                    column,
                    existing_type=sa.Float(),
                    type_=sa.Numeric(precision, scale),
                    existing_nullable=nullable,
                    existing_server_default=default,
                    postgresql_using=(f"{column}::numeric({precision},{scale})"),
                )


def downgrade() -> None:
    """Revert each column back to Float. Lossless for the value ranges
    we care about (six fractional digits round-trip cleanly through a
    double).
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    by_table: dict[str, list[tuple[str, int, int, bool, str | None]]] = {}
    for table, column, precision, scale, nullable, default in _NUMERIC_COLUMNS:
        col_type = _column_type(inspector, table, column)
        if col_type is None:
            continue
        if _is_float_family(col_type):
            continue
        if not _is_numeric_family(col_type):
            continue
        by_table.setdefault(table, []).append(
            (column, precision, scale, nullable, default),
        )

    for table, cols in by_table.items():
        with op.batch_alter_table(table) as batch:
            for column, precision, scale, nullable, default in cols:
                batch.alter_column(
                    column,
                    existing_type=sa.Numeric(precision, scale),
                    type_=sa.Float(),
                    existing_nullable=nullable,
                    existing_server_default=default,
                    postgresql_using=f"{column}::double precision",
                )
