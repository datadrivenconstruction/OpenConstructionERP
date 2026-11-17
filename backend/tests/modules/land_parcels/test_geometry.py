# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Parcel geometry: shoelace area, ring validity, overlaps and gaps between neighbours.

The first test is DOMAIN worked example 1 (EPSG 25833, offsets from E 389000 / N 5819000).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.land_parcels.geometry import (
    boundary_gap,
    intersection_area,
    open_ring,
    ring_closed,
    round_area,
    self_intersections,
    shoelace_area,
)

E0, N0 = 389000, 5819000
P1 = [(0, 0), (42.50, 3.20), (45.10, 31.80), (2.60, 28.40)]


def _abs(ring: list[tuple[float, float]]) -> list[tuple[Decimal, Decimal]]:
    return [(Decimal(str(E0 + x)), Decimal(str(N0 + y))) for x, y in ring]


def _rect(e1: float, n1: float, e2: float, n2: float) -> list[tuple[float, float]]:
    return [(e1, n1), (e2, n1), (e2, n2), (e1, n2)]


def test_worked_example_1_shoelace_sum_and_area() -> None:
    area = shoelace_area(_abs(P1))
    assert area == Decimal("1202.67")
    assert round_area(area, 2) == Decimal("1202.67")
    assert abs(area - Decimal("1203")) == Decimal("0.33")


def test_area_does_not_depend_on_orientation_or_closing_vertex() -> None:
    ring = _abs(P1)
    assert shoelace_area(list(reversed(ring))) == Decimal("1202.67")
    assert shoelace_area([*ring, ring[0]]) == Decimal("1202.67")


def test_round_area_follows_pack_decimals_half_up() -> None:
    assert round_area(Decimal("1202.675"), 2) == Decimal("1202.68")
    assert round_area(Decimal("1202.5"), 0) == Decimal("1203")


def test_ring_closed_and_open_ring() -> None:
    ring = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 0.0)]
    assert ring_closed(ring)
    assert open_ring(ring) == ring[:-1]
    assert not ring_closed(ring[:-1])


def test_self_intersection_bow_tie() -> None:
    assert self_intersections([(0, 0), (10, 10), (10, 0), (0, 10)])
    assert not self_intersections(_rect(0, 0, 10, 10))
    assert not self_intersections(P1)


def test_overlap_of_two_squares() -> None:
    assert intersection_area(_rect(0, 0, 10, 10), _rect(5, 5, 15, 15)) == pytest.approx(25.0)


def test_neighbours_sharing_an_edge_do_not_overlap() -> None:
    assert intersection_area(_rect(0, 0, 10, 10), _rect(10, 0, 20, 10)) == pytest.approx(0.0, abs=1e-9)


def test_overlap_of_concave_with_rectangle() -> None:
    l_shape = [(0, 0), (20, 0), (20, 10), (10, 10), (10, 20), (0, 20)]
    assert intersection_area(l_shape, _rect(5, 5, 15, 15)) == pytest.approx(75.0)


def test_identical_parcels_overlap_fully() -> None:
    assert intersection_area(_rect(0, 0, 10, 10), _rect(0, 0, 10, 10)) == pytest.approx(100.0)


def test_contained_parcel() -> None:
    assert intersection_area(_rect(0, 0, 10, 10), _rect(2, 2, 4, 4)) == pytest.approx(4.0)


def test_sliver_gap_between_neighbours() -> None:
    assert boundary_gap(_rect(0, 0, 10, 10), _rect(10.03, 0, 20, 10)) == pytest.approx(0.03)
    assert boundary_gap(_rect(0, 0, 10, 10), _rect(10, 0, 20, 10)) == pytest.approx(0.0)


def test_riverside_work_zone_overlaps_only_p003() -> None:
    zone = _rect(100, 10, 160, 20)
    p002 = _rect(50, 0, 80, 40)
    p003 = _rect(120, 0, 145, 40)
    assert intersection_area(zone, p002) == 0.0
    assert intersection_area(zone, p003) == pytest.approx(250.0)
