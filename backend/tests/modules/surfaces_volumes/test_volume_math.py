# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cut and fill against solids whose volume is known in closed form, and the DOMAIN examples."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from app.modules.surfaces_volumes.landxml import parse_landxml
from app.modules.surfaces_volumes.tin import Tin
from app.modules.surfaces_volumes.volumes import (
    END_AREA,
    GRID,
    TIN,
    auto_cell_size,
    compute,
    grid_volume,
    nice_cell,
    polygon_area,
    tin_volume,
)

DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside"
REL = 1e-3  # 0.1 %


def _flat(x0: float, y0: float, x1: float, y1: float, z: float) -> Tin:
    return Tin.from_points([x0, x1, x1, x0], [y0, y0, y1, y1], [z, z, z, z])


def test_domain_example_grid_four_cells() -> None:
    # DOMAIN example 3: 10 m cells with dh +0.40, +0.25, -0.10, -0.30 -> cut 65, fill 40, net 25 cut.
    base = _flat(0, 0, 40, 10, 0.0)
    xs = [5.0, 15.0, 25.0, 35.0]
    dh = [0.40, 0.25, -0.10, -0.30]
    compare = Tin.from_points(xs + xs, [0.0] * 4 + [10.0] * 4, [-d for d in dh] * 2)
    r = grid_volume(base, compare, 10.0)
    assert r.cut == pytest.approx(65.0)
    assert r.fill == pytest.approx(40.0)
    assert r.net == pytest.approx(25.0)
    assert r.coverage_pct == pytest.approx(100.0)


@pytest.mark.parametrize("method", [GRID, TIN, END_AREA])
def test_prism_is_exact(method: str) -> None:
    # A 20 x 20 m block 2 m deep: 800 m3 of cut and nothing to fill.
    r = compute(_flat(0, 0, 20, 20, 0.0), _flat(0, 0, 20, 20, -2.0), method, 1.0)
    assert r.cut == pytest.approx(800.0, rel=REL)
    assert r.fill == pytest.approx(0.0, abs=1e-6)
    assert r.coverage_pct == pytest.approx(100.0, rel=REL)


def _frustum(h: float = 5.0) -> Tin:
    # Mound on a 30 x 30 m base with a 10 x 10 m top, 5 m high.
    e = [0, 30, 30, 0, 10, 20, 20, 10]
    n = [0, 0, 30, 30, 10, 10, 20, 20]
    z = [0, 0, 0, 0, h, h, h, h]
    return Tin.from_points(e, n, z)


@pytest.mark.parametrize(("method", "cell"), [(GRID, 0.25), (TIN, None), (END_AREA, 0.25)])
def test_pyramid_frustum_within_a_tenth_of_a_percent(method: str, cell: float | None) -> None:
    a1, a2, h = 900.0, 100.0, 5.0
    exact = h / 3.0 * (a1 + a2 + (a1 * a2) ** 0.5)  # 2,166.667 m3
    r = compute(_flat(0, 0, 30, 30, 0.0), _frustum(h), method, cell)
    assert r.fill == pytest.approx(exact, rel=REL)
    assert r.cut == pytest.approx(0.0, abs=exact * REL)


def test_tin_splits_a_sloped_plane_at_zero() -> None:
    # dh = x - 3 over 0..10 x 0..10: cut = 10 * 7^2 / 2 = 245, fill = 10 * 3^2 / 2 = 45.
    base = Tin.from_points([0, 10, 10, 0], [0, 0, 10, 10], [0, 10, 10, 0])
    compare = _flat(0, 0, 10, 10, 3.0)
    r = tin_volume(base, compare)
    assert r.cut == pytest.approx(245.0, rel=1e-9)
    assert r.fill == pytest.approx(45.0, rel=1e-9)


def test_surfaces_that_do_not_meet_have_no_coverage() -> None:
    r = grid_volume(_flat(0, 0, 10, 10, 0.0), _flat(100, 100, 110, 110, 1.0), 1.0)
    assert r.coverage_pct == 0.0
    assert r.cut == r.fill == 0.0


def test_half_covered_boundary() -> None:
    boundary = [(0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)]
    r = grid_volume(_flat(0, 0, 10, 10, 1.0), _flat(0, 0, 10, 10, 0.0), 1.0, boundary)
    assert r.coverage_pct == pytest.approx(50.0)
    assert r.cut == pytest.approx(100.0)


def test_nice_cell_and_polygon_area() -> None:
    assert nice_cell(8.8) == 10.0
    assert nice_cell(4.0) == 5.0
    assert nice_cell(0.0) == 1.0
    # DOMAIN example 1 parcel: 1,202.67 m2 by the shoelace formula.
    ring = [(389000.0, 5819000.0), (389042.5, 5819003.2), (389045.1, 5819031.8), (389002.6, 5819028.4)]
    assert polygon_area(ring) == pytest.approx(1202.67, abs=0.005)


# ── Riverside Yard, computed from the shipped files ──────────────────────────


def _existing_ground() -> Tin:
    seen: set[str] = set()
    e: list[float] = []
    n: list[float] = []
    z: list[float] = []
    with (DEMO / "existing_ground.csv").open(encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row or row[0] in seen:
                continue  # lesson 3: keep the first EG-045
            seen.add(row[0])
            n.append(float(row[1]))
            e.append(float(row[2]))
            z.append(float(row[3]))
    assert len(e) == 77
    return Tin.from_points(e, n, z)


def _pad() -> Tin:
    surf = parse_landxml((DEMO / "design_pad.xml").read_text(encoding="utf-8")).surfaces[0]
    return Tin.from_faces(surf.e, surf.n, surf.z, surf.faces)


def test_riverside_numbers_match_expected_json() -> None:
    expected = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["volumes"]
    eg, pad = _existing_ground(), _pad()
    assert eg.area() == pytest.approx(expected["lesson_1"]["area_m2"])
    assert pad.area() == pytest.approx(expected["lesson_2"]["area_m2"])
    assert float(pad.z.max()) == pytest.approx(expected["lesson_2"]["z"])
    lesson = expected["lesson_3"]
    assert auto_cell_size(eg, pad) == lesson["cell_size_m"]
    for method in (GRID, TIN, END_AREA):
        r = compute(eg, pad, method)
        assert round(r.cut, 1) == lesson["cut_m3"], method
        assert round(r.fill, 1) == lesson["fill_m3"], method
        assert round(r.net, 1) == lesson["net_m3"], method
        assert round(r.coverage_pct) == lesson["coverage_pct"], method
    assert round(compute(eg, pad).cut * expected["lesson_6"]["swell_factor"], 1) == expected["lesson_6"]["loose_cut_m3"]


def test_riverside_cut_by_an_independent_integral() -> None:
    # Z = 34.00 + 0.010 * E over 100 x 60 m against a pad at 34.30: integrate dh = 0.01x - 0.3 exactly.
    width = 60.0
    cut = width * (0.005 * (100**2 - 30**2) - 0.3 * 70)
    fill = width * (0.3 * 30 - 0.005 * 30**2)
    assert (round(cut, 1), round(fill, 1)) == (1470.0, 270.0)
    grid = np.linspace(0, 100, 100_001)
    dh = 0.01 * grid - 0.3
    step = grid[1] - grid[0]
    assert width * float(np.clip(dh, 0, None).sum() * step) == pytest.approx(cut, rel=1e-4)
