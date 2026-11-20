# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Scan-vs-design arithmetic on hand-checkable clouds (no database)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.modules.pointcloud import scan_design as sd
from app.modules.surfaces_volumes.tin import Tin


def _pad(z0: float = 10.0, slope_e: float = 0.0) -> Tin:
    e = [0.0, 40.0, 40.0, 0.0]
    n = [0.0, 0.0, 20.0, 20.0]
    return Tin.from_points(e, n, [z0 + slope_e * x for x in e])


def test_bilinear_sampling_is_exact_on_a_sloped_plane() -> None:
    tin = _pad(slope_e=0.02)
    grid = sd.design_grid(tin)
    x = np.array([0.0, 13.37, 39.99, 40.0, 25.0])
    y = np.array([0.0, 7.21, 19.99, 20.0, 10.0])
    assert np.allclose(grid.sample(x, y), 10.0 + 0.02 * x, atol=1e-9)
    assert np.isnan(grid.sample(np.array([41.0]), np.array([5.0])))[0]


def test_worked_example_ten_points_one_high() -> None:
    # Nine points 2 mm high, one 30 mm high, tolerance 10 mm.
    grid = sd.design_grid(_pad())
    acc = sd.DeviationAccumulator(grid, 10.0)
    x = np.linspace(1.0, 39.0, 10)
    y = np.full(10, 10.0)
    z = np.full(10, 10.002)
    z[4] = 10.030
    acc.add(x, y, z)
    s = acc.result()
    assert s.points_compared == 10
    assert s.mean_mm == pytest.approx(4.8, abs=1e-6)  # (9*2 + 30) / 10
    assert s.rms_mm == pytest.approx(round(math.sqrt((9 * 4 + 900) / 10), 2))  # 9.67
    assert s.within_pct == 90.0
    assert s.high_pct == 10.0
    assert s.out_count == 1
    assert s.p95_mm == 30.0  # nearest rank 10 of 10
    assert s.bands["far_high"] == 1  # 30 mm is past twice the tolerance
    assert s.max_mm == 30.0


def test_points_off_the_design_are_counted_not_compared() -> None:
    grid = sd.design_grid(_pad())
    acc = sd.DeviationAccumulator(grid, 5.0)
    acc.add(np.array([5.0, 50.0]), np.array([5.0, 5.0]), np.array([10.0, 10.0]))
    s = acc.result()
    assert (s.points_read, s.points_compared, s.points_outside) == (2, 1, 1)
    assert s.within_pct == 100.0


def test_no_overlap_gives_empty_numbers() -> None:
    acc = sd.DeviationAccumulator(sd.design_grid(_pad()), 5.0)
    acc.add(np.array([100.0]), np.array([100.0]), np.array([1.0]))
    s = acc.result()
    assert s.points_compared == 0
    assert s.rms_mm is None
    assert s.coverage_pct == 0.0


def test_chunks_give_the_same_answer_as_one_pass() -> None:
    rng = np.random.default_rng(7)
    x, y = rng.uniform(0, 40, 5000), rng.uniform(0, 20, 5000)
    z = 10.0 + rng.normal(0, 0.006, 5000)
    grid = sd.design_grid(_pad())
    one, many = sd.DeviationAccumulator(grid, 10.0), sd.DeviationAccumulator(grid, 10.0)
    one.add(x, y, z)
    for k in range(0, 5000, 700):
        many.add(x[k : k + 700], y[k : k + 700], z[k : k + 700])
    a, b = one.result(), many.result()
    assert (a.mean_mm, a.rms_mm, a.p95_mm, a.within_pct) == (b.mean_mm, b.rms_mm, b.p95_mm, b.within_pct)
    assert a.p95_mm == pytest.approx(float(np.percentile(np.abs(z - 10.0) * 1000, 95)), abs=0.15)


def test_heat_grid_marks_the_high_corner() -> None:
    grid = sd.design_grid(_pad())
    floor = sd.heat_cell_floor(800.0, 3200)  # 0.5 m spacing -> 1 m heat cells
    assert floor == pytest.approx(1.0)
    acc = sd.DeviationAccumulator(grid, 10.0, floor)
    gx, gy = np.meshgrid(np.arange(0.25, 40, 0.5), np.arange(0.25, 20, 0.5))
    x, y = gx.ravel(), gy.ravel()
    acc.add(x, y, np.where((x > 30) & (y > 10), 10.05, 10.0))
    heat = acc.result().heat
    values = heat["dz_mm"]
    nx = heat["nx"]
    corner = values[(heat["ny"] - 1) * nx + nx - 1]
    assert corner == pytest.approx(50.0, abs=0.01)
    assert values[0] == pytest.approx(0.0, abs=0.01)
    assert acc.result().coverage_pct == 100.0


def test_band_colours() -> None:
    rgb = sd.heat_rgb(np.array([-25.0, -15.0, 0.0, 15.0, 25.0, np.nan]), 10.0)
    assert [tuple(c) for c in rgb] == [sd.BAND_RGB[k] for k in ("far_low", "low", "within", "high", "far_high", "none")]


def test_sample_collector_keeps_every_nth_across_chunks() -> None:
    keep = sd.SampleCollector(declared_points=1000, max_points=100)
    assert keep.stride == 10
    for k in range(0, 1000, 333):
        n = min(333, 1000 - k)
        x = np.arange(k, k + n, dtype=float)
        keep.add(x, x, x, x)
    xyz, _dz = keep.arrays()
    assert len(xyz) == 100
    assert np.array_equal(xyz[:, 0], np.arange(0, 1000, 10, dtype=float))
