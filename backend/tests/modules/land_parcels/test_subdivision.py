# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Subdivision, merge, setback and corner rules from the worked examples (SRV-100/101/102)."""

from __future__ import annotations

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.land_parcels import subdivision as sub
from app.modules.land_parcels.calc_validators import CornerPrecisionRule, SetbackRule, SubdivisionAreaRule
from app.modules.survey_core.closure_classes import find_corner

TRAPEZOID = [(0.0, 0.0), (50.0, 0.0), (50.0, 32.0), (0.0, 28.0)]


async def _failed(rule, data: dict) -> list:
    return [r for r in await rule.validate(ValidationContext(data=data, metadata={"locale": "en"})) if not r.passed]


def test_trapezoid_area() -> None:
    assert sub.area(TRAPEZOID) == pytest.approx(1500.0)


def test_west_part_of_600_cuts_at_x_20_810() -> None:
    # The west side runs (0,28)-(0,0): corner 3 to corner 0.
    res = sub.split_parallel(TRAPEZOID, 3, 600.0)
    xs = {round(p[0], 3) for p in res.cut}
    assert xs == {20.81}
    assert res.position == pytest.approx(20.810, abs=5e-4)
    assert res.cut_length == pytest.approx(29.665, abs=5e-4)
    assert sub.area(res.part) == pytest.approx(600.0, abs=1e-3)
    assert sub.area(res.rest) == pytest.approx(900.0, abs=1e-3)


def test_split_by_line_keeps_the_total() -> None:
    cut = sub.split_by_line(TRAPEZOID, (25.0, -1.0), (25.0, 40.0))
    assert sub.area(cut.left) + sub.area(cut.right) == pytest.approx(1500.0)


def test_rotating_cut_about_a_corner_hits_the_target() -> None:
    res = sub.split_rotating(TRAPEZOID, (0.0, 0.0), 500.0)
    assert sub.area(res.part) == pytest.approx(500.0, abs=1e-3)
    assert sub.area(res.part) + sub.area(res.rest) == pytest.approx(1500.0, abs=1e-3)


def test_target_outside_the_parcel_is_refused() -> None:
    with pytest.raises(sub.SubdivisionError):
        sub.split_parallel(TRAPEZOID, 3, 1600.0)


def test_merge_of_the_two_parts_gives_the_parent_back() -> None:
    res = sub.split_parallel(TRAPEZOID, 3, 600.0)
    merged = sub.merge(res.part, res.rest)
    assert sub.area(merged) == pytest.approx(1500.0, abs=1e-3)
    assert len(merged) == 4


async def test_srv100_flags_children_that_do_not_add_up() -> None:
    ok = {"subdivisions": [{"ref": "p", "parent_area": 1500.0, "a": 600.0, "b": 900.0}]}
    bad = {"subdivisions": [{"ref": "p", "parent_area": 1500.0, "a": 600.0, "b": 899.5}]}
    assert await _failed(SubdivisionAreaRule(), ok) == []
    [hit] = await _failed(SubdivisionAreaRule(), bad)
    assert hit.rule_id == "SRV-100"
    assert "-0.50" in hit.message


def test_corner_2_65_from_boundary() -> None:
    boundary = [(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)]
    footprint = [(2.65, 5.0), (20.0, 5.0), (20.0, 20.0), (2.65, 20.0)]
    edges = sub.setback_distances(footprint, boundary)
    assert min(e.distance for e in edges) == pytest.approx(2.65)
    assert not any(e.encroaches for e in edges)


async def test_srv102_setback_2_65_against_3_00() -> None:
    data = {"setbacks": [{"ref": "p", "footprint": "B1", "boundary": "P-4-P-1", "distance": 2.65, "setback": 3.0}]}
    [hit] = await _failed(SetbackRule(), data)
    assert hit.rule_id == "SRV-102"
    assert "2.65" in hit.message and "3.00" in hit.message
    data["setbacks"][0]["distance"] = 3.0
    assert await _failed(SetbackRule(), data) == []


def test_alta_rpp_allowance_is_2_cm_plus_50_ppm() -> None:
    cls = find_corner("us_alta_nsps_2021_rpp", ["US"])
    assert cls is not None
    assert sub.rpp_allowance(cls.base_m, cls.ppm, 100.0) == pytest.approx(0.021336 + 0.005)


def test_corner_classes_follow_the_market() -> None:
    assert find_corner("us_alta_nsps_2021_rpp", ["DE"]) is None


async def test_srv101_corner_over_its_allowance() -> None:
    data = {"corners": [{"id": "p", "label": "C7", "accuracy_m": 0.05, "limit_m": 0.026}]}
    [hit] = await _failed(CornerPrecisionRule(), data)
    assert hit.rule_id == "SRV-101"
    assert "C7" in hit.message
    data["corners"][0]["accuracy_m"] = 0.02
    assert await _failed(CornerPrecisionRule(), data) == []
