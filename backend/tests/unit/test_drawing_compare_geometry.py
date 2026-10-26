# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure geometry of the drawing revision compare: transforms, region merge, containment."""

from __future__ import annotations

import math

import pytest

from app.modules.drawing_compare.geometry import (
    IDENTITY,
    Rect,
    affine_scale_rotation,
    apply_affine,
    invert_affine,
    merge_rects,
    points_of,
    shape_in_region,
    similarity_from_two_points,
    transform_rect,
)


def test_two_point_similarity_recovers_shift_scale_rotation() -> None:
    # Old sheet plotted at half size, rotated 90 degrees and shifted.
    old = [(0.0, 0.0), (100.0, 0.0)]
    new = [(10.0, 20.0), (10.0, 70.0)]
    m = similarity_from_two_points(old, new)
    scale, rot = affine_scale_rotation(m)
    assert scale == pytest.approx(0.5)
    assert rot == pytest.approx(90.0)
    for (ox, oy), (nx, ny) in zip(old, new, strict=True):
        assert apply_affine(m, ox, oy) == pytest.approx((nx, ny))
    # A third point follows the same transform.
    assert apply_affine(m, 0.0, 100.0) == pytest.approx((-40.0, 20.0))


def test_two_point_similarity_refuses_coincident_points() -> None:
    with pytest.raises(ValueError, match="coincide"):
        similarity_from_two_points([(1, 1), (1, 1)], [(0, 0), (5, 5)])


def test_invert_affine_round_trips_and_refuses_singular() -> None:
    m = (2.0, 0.0, 0.0, 2.0, 5.0, -3.0)
    inv = invert_affine(m)
    x, y = apply_affine(m, 7.0, 11.0)
    assert apply_affine(inv, x, y) == pytest.approx((7.0, 11.0))
    with pytest.raises(ValueError):
        invert_affine((1.0, 2.0, 2.0, 4.0, 0.0, 0.0))


def test_transform_rect_is_bounding_box_of_corners() -> None:
    rotated = similarity_from_two_points([(0, 0), (1, 0)], [(0, 0), (0, 1)])
    box = transform_rect(rotated, Rect(0, 0, 10, 4))
    assert (box.x, box.y, box.w, box.h) == pytest.approx((-4.0, 0.0, 4.0, 10.0))


def test_merge_rects_groups_neighbours_within_gap_only() -> None:
    rects = [Rect(0, 0, 10, 10), Rect(12, 0, 10, 10), Rect(100, 100, 5, 5), Rect(24, 0, 2, 2)]
    assert merge_rects(rects, gap=0) == [[0], [1], [2], [3]]
    # A gap of 4 bridges 0-1 (2 apart) and 1-3 (2 apart), not the far box.
    assert merge_rects(rects, gap=4) == [[0, 1, 3], [2]]


def test_merge_rects_handles_chains_out_of_x_order() -> None:
    rects = [Rect(40, 0, 5, 5), Rect(0, 0, 5, 5), Rect(20, 0, 5, 5), Rect(10, 0, 5, 5), Rect(30, 0, 5, 5)]
    assert merge_rects(rects, gap=6) == [[0, 1, 2, 3, 4]]


@pytest.mark.parametrize(
    ("geometry", "expected"),
    [
        ([{"x": 1, "y": 2}, {"x": 3, "y": 4}], [(1.0, 2.0), (3.0, 4.0)]),
        ({"points": [[1, 2], [3, 4]]}, [(1.0, 2.0), (3.0, 4.0)]),
        ({"start": {"x": 0, "y": 0}, "end": {"x": 5, "y": 0}}, [(0.0, 0.0), (5.0, 0.0)]),
        ({"center": {"x": 10, "y": 10}, "radius": 2}, [(8.0, 8.0), (12.0, 12.0)]),
        ({"x": 1, "y": 1, "width": 4, "height": 2}, [(1.0, 1.0), (5.0, 3.0)]),
        ({"points": [{"x": "nan", "y": 1}, {"x": 1, "y": "bad"}]}, []),
        (None, []),
    ],
)
def test_points_of_reads_every_stored_shape(geometry: object, expected: list[tuple[float, float]]) -> None:
    assert points_of(geometry) == expected


def test_shape_in_region_uses_overlap_and_maps_old_revision() -> None:
    region = Rect(100, 100, 50, 50)
    inside = [(110.0, 110.0), (120.0, 120.0)]
    straddling = [(90.0, 90.0), (105.0, 105.0)]
    outside = [(0.0, 0.0), (10.0, 10.0)]
    assert shape_in_region(inside, region)
    assert shape_in_region(straddling, region)
    assert not shape_in_region(outside, region)
    assert not shape_in_region([], region)
    # Drawn on the old sheet, which sits 100 units up-left of the new one.
    shift = (1.0, 0.0, 0.0, 1.0, 100.0, 100.0)
    assert shape_in_region(outside, region, matrix=shift)
    assert shape_in_region([(-5.0, -5.0)], region, matrix=shift, margin=6)
    assert not shape_in_region([(-5.0, -5.0)], region, matrix=shift, margin=1)


def test_identity_is_noop() -> None:
    assert apply_affine(IDENTITY, 3.5, -2.0) == (3.5, -2.0)
    assert affine_scale_rotation(IDENTITY) == (1.0, 0.0)
    assert math.isclose(Rect(0, 0, 3, 4).area, 12.0)
