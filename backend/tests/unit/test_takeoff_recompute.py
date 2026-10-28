"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Server-side measurement recompute — Audit B8 regression suite.

The takeoff API used to trust client-supplied ``measurement_value``
alongside the raw ``points`` array. A malicious client could draw a
2 m polygon and claim it was 9999 m², which then propagated into BOQ
totals via ``link_measurement_to_boq``. The
``recompute_measurement_value`` helper now reconstructs the value from
(points x scale) on the server.

These tests pin:

* distance: euclidean length / scale
* polyline: sum-of-segment lengths / scale
* area: shoelace area / scale^2
* volume: same area derivation (depth handled elsewhere)
* count: trusts ``count_value``, ignores points
* annotation types: pass through client_value unchanged
* missing scale or <2 points: degrades to client_value, never crashes
* unknown types: pass through client_value
"""

from __future__ import annotations

import math

import pytest

from app.modules.takeoff.schemas import PointSchema
from app.modules.takeoff.service import (
    _polyline_length,
    _shoelace_area,
    recompute_measurement_value,
)


def _pts(*tuples: tuple[float, float]) -> list[PointSchema]:
    """Build a list of PointSchema from raw tuples."""
    return [PointSchema(x=x, y=y) for x, y in tuples]


# ── Distance --------------------------------------------------------------


def test_distance_two_points_unit_scale() -> None:
    """100px line at scale=1px/m = 100m."""
    result = recompute_measurement_value(
        measurement_type="distance",
        points=_pts((0.0, 0.0), (100.0, 0.0)),
        scale_pixels_per_unit=1.0,
        count_value=None,
        client_value=99999.0,  # malicious — must be ignored
    )
    assert result == pytest.approx(100.0)


def test_distance_diagonal_uses_euclidean() -> None:
    """3-4-5 right triangle hypotenuse at scale=1 = 5m."""
    result = recompute_measurement_value(
        measurement_type="distance",
        points=_pts((0.0, 0.0), (3.0, 4.0)),
        scale_pixels_per_unit=1.0,
        count_value=None,
        client_value=None,
    )
    assert result == pytest.approx(5.0)


def test_distance_scale_divides() -> None:
    """100px at scale=10px/m = 10m."""
    result = recompute_measurement_value(
        measurement_type="distance",
        points=_pts((0.0, 0.0), (100.0, 0.0)),
        scale_pixels_per_unit=10.0,
        count_value=None,
        client_value=None,
    )
    assert result == pytest.approx(10.0)


# ── Polyline --------------------------------------------------------------


def test_polyline_sums_segments() -> None:
    """L-shaped path: 3 + 4 = 7m at scale=1."""
    result = recompute_measurement_value(
        measurement_type="polyline",
        points=_pts((0.0, 0.0), (3.0, 0.0), (3.0, 4.0)),
        scale_pixels_per_unit=1.0,
        count_value=None,
        client_value=None,
    )
    assert result == pytest.approx(7.0)


# ── Area ------------------------------------------------------------------


def test_area_unit_square() -> None:
    """1px square at scale=1px/m = 1m² (shoelace closes loop automatically)."""
    result = recompute_measurement_value(
        measurement_type="area",
        points=_pts((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
        scale_pixels_per_unit=1.0,
        count_value=None,
        client_value=99999.0,  # client lying — server must overwrite
    )
    assert result == pytest.approx(1.0)


def test_area_scales_squared() -> None:
    """100x100px square at scale=10px/m = (100*100)/100 = 100m²."""
    result = recompute_measurement_value(
        measurement_type="area",
        points=_pts((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)),
        scale_pixels_per_unit=10.0,
        count_value=None,
        client_value=None,
    )
    assert result == pytest.approx(100.0)


def test_area_triangle() -> None:
    """3-4-5 right triangle area = 6 at scale=1."""
    result = recompute_measurement_value(
        measurement_type="area",
        points=_pts((0.0, 0.0), (3.0, 0.0), (3.0, 4.0)),
        scale_pixels_per_unit=1.0,
        count_value=None,
        client_value=None,
    )
    assert result == pytest.approx(6.0)


# ── Volume (base area only — depth multiplies elsewhere) ------------------


def test_volume_returns_base_area() -> None:
    """Volume recompute returns the base area; depth is its own field."""
    result = recompute_measurement_value(
        measurement_type="volume",
        points=_pts((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        scale_pixels_per_unit=1.0,
        count_value=None,
        client_value=None,
    )
    assert result == pytest.approx(100.0)


# ── Count -----------------------------------------------------------------


def test_count_uses_count_value() -> None:
    """Count measurements ignore points entirely; trust count_value."""
    result = recompute_measurement_value(
        measurement_type="count",
        points=_pts((0.0, 0.0), (1.0, 1.0)),  # arbitrary, must not affect result
        scale_pixels_per_unit=1.0,
        count_value=7,
        client_value=99999.0,
    )
    assert result == pytest.approx(7.0)


def test_count_falls_back_to_client_when_count_value_missing() -> None:
    """If neither count_value nor client_value is given, we get None."""
    assert (
        recompute_measurement_value(
            measurement_type="count",
            points=[],
            scale_pixels_per_unit=None,
            count_value=None,
            client_value=None,
        )
        is None
    )


# ── Annotation pass-through ----------------------------------------------


@pytest.mark.parametrize("annotation_type", ["cloud", "arrow", "text", "rectangle", "highlight"])
def test_annotation_types_pass_through_client_value(annotation_type: str) -> None:
    """Pure annotations don't have a "real" measurement — preserve the
    client-supplied value verbatim so labels with numeric tags survive.
    """
    result = recompute_measurement_value(
        measurement_type=annotation_type,
        points=_pts((0.0, 0.0), (1.0, 1.0)),
        scale_pixels_per_unit=1.0,
        count_value=None,
        client_value=42.0,
    )
    assert result == pytest.approx(42.0)


# ── Degradation paths -----------------------------------------------------


def test_missing_scale_returns_client_value() -> None:
    """No scale = can't convert pixels to units; trust client (legacy data)."""
    result = recompute_measurement_value(
        measurement_type="distance",
        points=_pts((0.0, 0.0), (100.0, 0.0)),
        scale_pixels_per_unit=None,
        count_value=None,
        client_value=12.5,
    )
    assert result == pytest.approx(12.5)


def test_single_point_returns_client_value() -> None:
    """A single point isn't a line/polygon — degrade rather than throw."""
    result = recompute_measurement_value(
        measurement_type="distance",
        points=_pts((5.0, 5.0)),
        scale_pixels_per_unit=1.0,
        count_value=None,
        client_value=99.0,
    )
    assert result == pytest.approx(99.0)


def test_unknown_type_returns_client_value() -> None:
    """Forward-compat: don't drop measurements with new types we don't know yet."""
    result = recompute_measurement_value(
        measurement_type="future_type_v2",
        points=_pts((0.0, 0.0), (1.0, 0.0)),
        scale_pixels_per_unit=1.0,
        count_value=None,
        client_value=7.0,
    )
    assert result == pytest.approx(7.0)


# ── Helpers (white-box) ---------------------------------------------------


def test_shoelace_handles_open_polygon() -> None:
    """Shoelace should close the loop automatically — open and closed inputs match."""
    open_pts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    closed_pts = [*open_pts, (0.0, 0.0)]
    assert _shoelace_area(open_pts) == pytest.approx(_shoelace_area(closed_pts))


def test_shoelace_under_three_points_is_zero() -> None:
    """A 'polygon' with <3 points has zero area by definition."""
    assert _shoelace_area([(0.0, 0.0), (1.0, 1.0)]) == 0.0


def test_polyline_length_zero_for_empty_or_singleton() -> None:
    """No segments = zero length."""
    assert _polyline_length([]) == 0.0
    assert _polyline_length([(0.0, 0.0)]) == 0.0


def test_polyline_length_matches_hypot() -> None:
    """Two-point polyline length equals math.hypot of the delta."""
    assert _polyline_length([(0.0, 0.0), (3.0, 4.0)]) == pytest.approx(math.hypot(3, 4))
