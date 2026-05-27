# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Decimal precision pin for ``TakeoffMeasurement`` quantity columns.

Round-6 audit (2026-05-22) flagged ``measurement_value`` + ``depth`` +
``volume`` + ``perimeter`` on ``oe_takeoff_measurement`` as ``Float``
even though all four flow into BOQ totals via ``link-to-boq``. The
sibling ``DwgAnnotation.measurement_value`` was already on
``Numeric(18, 6)`` since Round 3 — this test pins the takeoff path
to the same regime by introspecting the live SQLAlchemy column type
(``Decimal`` after the fix, ``Float`` before).
"""

from __future__ import annotations

import sqlalchemy as sa


def test_takeoff_measurement_quantity_columns_are_numeric() -> None:
    """Quantity columns that feed BOQ money must be Numeric, not Float."""
    from app.modules.takeoff.models import TakeoffMeasurement

    columns_to_check = ["measurement_value", "depth", "volume", "perimeter"]
    failures: list[str] = []
    for col_name in columns_to_check:
        col = TakeoffMeasurement.__table__.c[col_name]
        col_type = col.type
        if not isinstance(col_type, sa.Numeric):
            failures.append(f"{col_name}: {col_type!r}")
            continue
        # sa.Float subclasses sa.Numeric — reject that subclass explicitly so
        # the regression catches a half-migration where someone widened
        # precision via Float() rather than switching to Numeric().
        if isinstance(col_type, sa.Float):
            failures.append(f"{col_name}: still Float ({col_type!r})")
            continue
        if col_type.precision != 18 or col_type.scale != 6:
            failures.append(
                f"{col_name}: Numeric({col_type.precision}, {col_type.scale}) — "
                "expected Numeric(18, 6) to match dwg_takeoff",
            )

    assert not failures, (
        "Float columns leak binary drift into BOQ rollups. "
        "Switch to Numeric(18, 6). Offending columns: " + "; ".join(failures)
    )


def test_takeoff_measurement_scale_pixels_per_unit_remains_float() -> None:
    """``scale_pixels_per_unit`` stays Float — it's a UI calibration ratio,
    never persisted into a money column. Migrating it would force every
    in-flight PDF takeoff session to be re-calibrated for zero gain.
    """
    from app.modules.takeoff.models import TakeoffMeasurement

    col = TakeoffMeasurement.__table__.c["scale_pixels_per_unit"]
    assert isinstance(col.type, sa.Float), "scale_pixels_per_unit should remain Float — see model docstring"
