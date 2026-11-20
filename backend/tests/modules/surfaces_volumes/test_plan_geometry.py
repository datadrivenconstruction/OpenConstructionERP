# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan-editor surface maths: contours, design pads with batters, section samples, SRV-083."""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.core.validation.engine import ValidationContext
from app.modules.surfaces_volumes import contours as cl
from app.modules.surfaces_volumes import pad as pl
from app.modules.surfaces_volumes import volumes as vol
from app.modules.surfaces_volumes.geometry_service import pad_context
from app.modules.surfaces_volumes.pad_validators import PadRingValidRule
from app.modules.surfaces_volumes.sampling import sample_polyline, stations
from app.modules.surfaces_volumes.tin import Tin


def _plane(slope_e: float = 0.0, slope_n: float = 0.0, z0: float = 0.0, size: float = 100.0, step: float = 10.0) -> Tin:
    xs = np.arange(0.0, size + step / 2, step)
    e, n = np.meshgrid(xs, xs)
    e, n = e.ravel(), n.ravel()
    return Tin.from_points(e, n, z0 + slope_e * e + slope_n * n)


# ── Contours ──────────────────────────────────────────────────────────────


def test_contours_on_a_plane_are_straight_and_evenly_spaced() -> None:
    # z = 0.1 * e over 0..100 m: a 1 m interval gives lines at e = 10, 20, ... 90; the edges carry none.
    tin = _plane(slope_e=0.1)
    lines = cl.contour_lines(tin, 1.0)
    levels = sorted({ln.z for ln in lines})
    assert levels == [float(k) for k in range(1, 10)]
    for ln in lines:
        es = [c[0] for c in ln.coords]
        assert max(es) - min(es) < 1e-6, "a contour on an east-dipping plane runs due north"
        assert es[0] == pytest.approx(ln.z * 10.0, abs=1e-6)
        ns = sorted(c[1] for c in ln.coords)
        assert ns[0] == pytest.approx(0.0, abs=1e-6) and ns[-1] == pytest.approx(100.0, abs=1e-6)
    inner = sorted(ln.coords[0][0] for ln in lines)
    gaps = {round(b - a, 6) for a, b in zip(inner, inner[1:], strict=False)}
    assert gaps == {10.0}


def test_each_contour_is_one_continuous_polyline() -> None:
    tin = _plane(slope_e=0.1)
    per_level: dict[float, int] = {}
    for ln in cl.contour_lines(tin, 2.0):
        per_level[ln.z] = per_level.get(ln.z, 0) + 1
    assert all(v == 1 for z, v in per_level.items() if 0 < z < 10)


def test_index_contours_every_fifth() -> None:
    assert cl.is_index(5.0, 1.0) and cl.is_index(10.0, 2.0) and not cl.is_index(4.0, 1.0)
    assert cl.is_index(2.5, 0.5) and not cl.is_index(3.0, 0.5)


def test_contour_closes_round_a_hill() -> None:
    xs = np.linspace(-50, 50, 21)
    e, n = np.meshgrid(xs, xs)
    e, n = e.ravel(), n.ravel()
    tin = Tin.from_points(e, n, 20.0 - (e**2 + n**2) / 250.0)
    ring = [ln for ln in cl.contour_lines(tin, 5.0) if ln.z == 15.0]
    assert len(ring) == 1 and ring[0].closed
    r = [math.hypot(x, y) for x, y in ring[0].coords]
    assert min(r) == pytest.approx(math.sqrt(1250), rel=0.05)


@pytest.mark.parametrize(
    ("z_min", "z_max", "expected"),
    [(0.0, 20.0, 1.0), (100.0, 110.0, 0.5), (0.0, 5.0, 0.25), (0.0, 100.0, 5.0), (50.0, 50.0, 0.1)],
)
def test_auto_interval_gives_about_twenty_lines(z_min: float, z_max: float, expected: float) -> None:
    assert cl.auto_interval(z_min, z_max) == expected


# ── Pads ──────────────────────────────────────────────────────────────────


def test_pad_without_ground_is_the_level_top() -> None:
    res = pl.build_pad([(0, 0), (20, 0), (20, 20), (0, 20)], 10.0)
    assert res.daylight == [] and res.unresolved == 0
    assert res.tin.area() == pytest.approx(400.0)
    assert float(res.tin.z.min()) == float(res.tin.z.max()) == 10.0


def test_pad_batter_meets_flat_ground_at_one_in_two() -> None:
    ground = _plane(z0=9.0, size=60.0, step=10.0)
    ground = Tin(ground.e - 20.0, ground.n - 20.0, ground.z, ground.tri)
    res = pl.build_pad([(0, 0), (20, 0), (20, 20), (0, 20)], 10.0, batter_n=2.0, ground=ground)
    assert res.unresolved == 0
    xs = sorted(round(p[0], 3) for p in res.daylight)
    ys = sorted(round(p[1], 3) for p in res.daylight)
    assert xs[0] == pytest.approx(-2.0, abs=1e-3) and xs[-1] == pytest.approx(22.0, abs=1e-3)
    assert ys[0] == pytest.approx(-2.0, abs=1e-3) and ys[-1] == pytest.approx(22.0, abs=1e-3)
    assert all(p[2] == pytest.approx(9.0, abs=1e-3) for p in res.daylight)


def test_pad_fill_volume_matches_the_frustum_hand_calc() -> None:
    # 20 x 20 m pad 1 m above flat ground, batter 1:2: a frustum 20x20 on 24x24, h = 1.
    # V = h/3 (A1 + A2 + sqrt(A1 A2)) = (400 + 576 + 480) / 3 = 485.333 m3 of fill.
    ground = _plane(z0=9.0, size=60.0, step=10.0)
    ground = Tin(ground.e - 20.0, ground.n - 20.0, ground.z, ground.tri)
    res = pl.build_pad([(0, 0), (20, 0), (20, 20), (0, 20)], 10.0, batter_n=2.0, ground=ground)
    r = vol.compute(ground, res.tin, vol.GRID, 0.05)
    assert r.fill == pytest.approx(1456.0 / 3.0, rel=0.003)
    assert r.cut == pytest.approx(0.0, abs=0.5)


def test_pad_cut_batter_slopes_up_to_higher_ground() -> None:
    ground = _plane(z0=12.0, size=60.0, step=10.0)
    ground = Tin(ground.e - 20.0, ground.n - 20.0, ground.z, ground.tri)
    res = pl.build_pad([(0, 0), (20, 0), (20, 20), (0, 20)], 10.0, batter_n=1.5, ground=ground)
    assert all(p[2] == pytest.approx(12.0, abs=1e-3) for p in res.daylight)
    assert min(p[0] for p in res.daylight) == pytest.approx(-3.0, abs=1e-3)


def test_cross_fall_tilts_the_top() -> None:
    # 2 % fall due east (bearing 90): 10 m east of the centroid is 0.2 m lower.
    assert pl.top_height(20, 10, (10, 10), 50.0, 2.0, 90.0) == pytest.approx(49.8)
    assert pl.top_height(0, 10, (10, 10), 50.0, 2.0, 90.0) == pytest.approx(50.2)


def test_clockwise_outline_is_accepted() -> None:
    res = pl.build_pad([(0, 0), (0, 20), (20, 20), (20, 0)], 5.0)
    assert res.tin.area() == pytest.approx(400.0)


# ── SRV-083 ───────────────────────────────────────────────────────────────


def test_ring_check_finds_a_bow_tie() -> None:
    check = pl.check_ring([(0, 0), (10, 10), (10, 0), (0, 10)])
    assert check.self_intersections == 1 and not check.valid
    assert pl.check_ring([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]).valid


async def _run(data: dict) -> list:
    ctx = ValidationContext(data=data, metadata={"locale": "en"})
    return [r for r in await PadRingValidRule().validate(ctx) if not r.passed]


async def test_srv083_passes_a_good_pad() -> None:
    assert await _run(pad_context("P1", [(0, 0), (10, 0), (10, 10)], 5.0)) == []


async def test_srv083_flags_open_crossing_and_no_level() -> None:
    open_ = await _run(pad_context("P1", [(0, 0), (10, 0)], 5.0))
    assert [r.details for r in open_] and "P1" in open_[0].message
    crossed = await _run(pad_context("P2", [(0, 0), (10, 10), (10, 0), (0, 10)], 5.0))
    assert any("crosses itself" in r.message for r in crossed)
    no_level = await _run(pad_context("P3", [(0, 0), (10, 0), (10, 10)], None))
    assert any("no level" in r.message for r in no_level)


async def test_srv083_warns_when_a_batter_never_reaches_ground() -> None:
    res = await _run(pad_context("P4", [(0, 0), (10, 0), (10, 10)], 5.0, unresolved=2))
    assert len(res) == 1 and str(res[0].severity.value) == "warning"


# ── Sampling ──────────────────────────────────────────────────────────────


def test_stations_include_interval_vertices_and_end() -> None:
    chs = [s[0] for s in stations([(0, 0), (25, 0), (25, 12)], 10.0)]
    assert chs == [0.0, 10.0, 20.0, 25.0, 30.0, 37.0]


def test_sample_offsets_are_right_of_travel() -> None:
    tin = _plane(slope_n=0.1)
    rows = sample_polyline(tin, [(10, 50), (90, 50)], 40.0, [-5.0, 0.0, 5.0])
    first = [r for r in rows if r.ch == 0.0]
    by_off = {r.offset: r for r in first}
    assert by_off[5.0].n == pytest.approx(45.0) and by_off[-5.0].n == pytest.approx(55.0)
    assert by_off[0.0].z == pytest.approx(5.0) and by_off[5.0].z == pytest.approx(4.5)


def test_sample_off_the_surface_is_none() -> None:
    rows = sample_polyline(_plane(), [(50, 50), (150, 50)], 50.0)
    assert rows[0].z == 0.0 and rows[-1].z is None
