"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regression test for DXF arc length — audit C3.

The DXF processor stores arc angles as ``math.radians(dxf.start_angle)``
in :mod:`app.modules.dwg_takeoff.dxf_processor` (see ``_extract_geometry``
ARC branch). Before the fix ``calculate_entity_measurement`` then called
``math.radians()`` a SECOND time on those already-radian values, so the
arc length came out off by ``(π/180)² ≈ 3.05e-4``. A 90° arc was
reported as ~0 metres, and circular features were silently dropped from
takeoff totals.

These tests pin the correct behaviour by feeding the calculator the
geometry it would receive from ``_extract_geometry`` for a 90° arc
of radius 1 — the expected length is ``π/2`` (~1.5708 m). The OLD
buggy result would be ``π/2 × (π/180)² ≈ 4.79e-4 m`` — three orders of
magnitude off — so the assertion below catches a regression decisively.
"""

from __future__ import annotations

import math

import pytest

from app.modules.dwg_takeoff.dxf_processor import calculate_entity_measurement


def _arc(start_deg: float, end_deg: float, radius: float = 1.0) -> dict:
    """Build the geometry payload exactly as ``_extract_geometry`` does.

    ``start_angle`` and ``end_angle`` are stored in **radians** already;
    the regression target is that ``calculate_entity_measurement`` does
    not pass them through ``math.radians`` a second time.
    """
    return {
        "entity_type": "ARC",
        "geometry_data": {
            "center": {"x": 0.0, "y": 0.0},
            "radius": radius,
            "start_angle": math.radians(start_deg),
            "end_angle": math.radians(end_deg),
        },
    }


class TestDxfArcLength:
    def test_quarter_arc_radius_one(self) -> None:
        """90° arc, r=1 → length = π/2."""
        result = calculate_entity_measurement(_arc(0.0, 90.0, 1.0))
        assert result == pytest.approx(math.pi / 2, rel=1e-9)

    def test_half_arc_radius_two(self) -> None:
        """180° arc, r=2 → length = 2π."""
        result = calculate_entity_measurement(_arc(0.0, 180.0, 2.0))
        assert result == pytest.approx(2 * math.pi, rel=1e-9)

    def test_full_circle_via_arc(self) -> None:
        """360° arc → 2πr (we treat negative sweep as +2π — matches old behaviour)."""
        # 359.999° → ~2π, full 360° = wrap → 0 by convention is acceptable;
        # check we get the long way around (the wrap-to-+2π branch).
        result = calculate_entity_measurement(_arc(0.0, 359.999, 1.0))
        assert result == pytest.approx(2 * math.pi, rel=1e-3)

    def test_wraparound_arc(self) -> None:
        """Arc from 350° to 10° must measure 20°·r — not 340°·r."""
        result = calculate_entity_measurement(_arc(350.0, 10.0, 1.0))
        # The implementation adds 2π to a negative sweep, giving the
        # short positive way from 350° to 10° = 20° = π/9 rad.
        assert result == pytest.approx(math.radians(20.0), rel=1e-9)

    def test_arc_length_not_off_by_pi_over_180_squared(self) -> None:
        """Direct sentinel against the OLD double-radians bug.

        Old (buggy) code returned length × (π/180)² ≈ 0.000305 for a
        90° quarter-circle of r=1. New code must return π/2. If the bug
        is ever reintroduced, the value drops by ~5000× and this
        assertion fails loudly.
        """
        result = calculate_entity_measurement(_arc(0.0, 90.0, 1.0))
        old_buggy = (math.pi / 2) * ((math.pi / 180.0) ** 2)
        # If the new value matched the old, ratio would be (π/180)² ≈ 3e-4.
        # We require the ratio to be at least 100× greater than the buggy one.
        assert result > 100 * old_buggy
