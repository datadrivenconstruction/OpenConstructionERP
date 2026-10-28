# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Coordinate validation pin for ``PointSchema`` on takeoff measurements.

Round-6 audit (2026-05-22) — pre-fix the schema accepted unbounded ``x``
/ ``y`` floats. A malicious client could send ``{"x": 1e30, "y": 1e30}``
and the server-side recompute (``_shoelace_area``) produced absurd
``area`` values that flowed into BOQ totals via ``link-to-boq``.

These tests fail on the pre-fix schema (the request would be accepted
and stored) and pass after we add ``Field(..., ge=-1e6, le=1e6)`` plus
NaN/Inf rejection, plus a hard cap on the point-list length.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.modules.takeoff.schemas import PointSchema, TakeoffMeasurementCreate


def _make_create_payload(points: list[dict]) -> dict:
    return {
        "project_id": "00000000-0000-0000-0000-000000000001",
        "page": 1,
        "type": "area",
        "points": points,
    }


def test_point_rejects_x_above_max_coord() -> None:
    with pytest.raises(ValidationError):
        PointSchema(x=1e30, y=0)


def test_point_rejects_y_above_max_coord() -> None:
    with pytest.raises(ValidationError):
        PointSchema(x=0, y=1e30)


def test_point_rejects_negative_below_max() -> None:
    with pytest.raises(ValidationError):
        PointSchema(x=-1_000_001.0, y=0)


def test_point_rejects_nan() -> None:
    with pytest.raises(ValidationError):
        PointSchema(x=math.nan, y=0)


def test_point_rejects_inf() -> None:
    with pytest.raises(ValidationError):
        PointSchema(x=math.inf, y=0)


def test_point_accepts_inside_bounds() -> None:
    p = PointSchema(x=500_000.0, y=-500_000.0)
    assert p.x == 500_000.0
    assert p.y == -500_000.0


def test_measurement_rejects_polygon_with_unbounded_point() -> None:
    """Whole-payload integration: a polygon with a single bad vertex must
    fail validation, never reaching the persistence layer.
    """
    points = [
        {"x": 0, "y": 0},
        {"x": 10, "y": 0},
        {"x": 1e25, "y": 1e25},  # bad
        {"x": 0, "y": 10},
    ]
    with pytest.raises(ValidationError):
        TakeoffMeasurementCreate(**_make_create_payload(points))


def test_measurement_rejects_too_many_points() -> None:
    """Polygon length is capped at 5000 — beyond that, payload is rejected."""
    points = [{"x": i % 100, "y": i // 100} for i in range(5001)]
    with pytest.raises(ValidationError):
        TakeoffMeasurementCreate(**_make_create_payload(points))


def test_measurement_accepts_normal_polygon() -> None:
    """A reasonably-sized polygon inside bounds must still go through."""
    points = [
        {"x": 0, "y": 0},
        {"x": 100, "y": 0},
        {"x": 100, "y": 50},
        {"x": 0, "y": 50},
    ]
    obj = TakeoffMeasurementCreate(**_make_create_payload(points))
    assert len(obj.points) == 4
