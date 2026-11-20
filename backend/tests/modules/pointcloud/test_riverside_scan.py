# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Riverside Yard pad scan: the numbers in demo/riverside/expected.json, and why they are right."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.pointcloud.deviation import classify_deviation
from app.modules.pointcloud.grid import cloud_grid
from app.modules.pointcloud.scan_design_service import run_deviation, run_sample
from app.modules.pointcloud.survey_demo import PATCH_DZ, build_pad_scan, expected
from app.modules.surfaces_volumes import volumes as vol
from app.modules.surfaces_volumes.tin import Tin

EXP = expected()


@pytest.fixture(scope="module")
def scan_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("riverside") / "pad.las"
    path.write_bytes(build_pad_scan())
    return path


@pytest.fixture(scope="module")
def pad() -> Tin:
    z = EXP["scan"]["design_z"]
    return Tin.from_points([389000, 389100, 389100, 389000], [5819000, 5819000, 5819060, 5819060], [z] * 4)


def test_the_demo_cloud_is_small(scan_path: Path) -> None:
    assert scan_path.stat().st_size < 5 * 1024 * 1024


def test_deviation_matches_expected(scan_path: Path, pad: Tin) -> None:
    exp = EXP["deviation"]
    stats, used_all = run_deviation(str(scan_path), "las", pad, exp["tolerance_mm"], exp["ground_only"])
    assert used_all is False
    assert stats.points_read == EXP["scan"]["points"]
    for key in ("points_compared", "mean_mm", "rms_mm", "p95_mm", "min_mm", "max_mm", "within_pct", "high_pct"):
        assert getattr(stats, key) == exp[key], key
    assert stats.out_count == exp["out_count"]
    assert stats.coverage_pct == exp["coverage_pct"]
    assert classify_deviation(rms_mm=stats.rms_mm, tolerance_mm=exp["tolerance_mm"]) == exp["severity"]


def test_why_the_numbers_are_right(scan_path: Path, pad: Tin) -> None:
    stats, _ = run_deviation(str(scan_path), "las", pad, 10.0, True)
    patch_points = 41 * 41  # 20 m at 0.5 m, both ends included
    assert stats.out_count == patch_points
    # The noise pattern averages out; the mean is the high spot spread over the pad.
    assert stats.mean_mm == pytest.approx(patch_points * PATCH_DZ * 1000 / stats.points_compared, abs=0.01)
    assert stats.within_pct == pytest.approx(100 * (1 - patch_points / stats.points_compared), abs=0.01)


def test_the_high_spot_is_where_the_heatmap_is_red(scan_path: Path, pad: Tin) -> None:
    stats, _ = run_deviation(str(scan_path), "las", pad, 10.0, True)
    heat = stats.heat
    nx, cell = heat["nx"], heat["cell"]

    def at(e: float, n: float) -> float | None:
        i = int((e - heat["origin_e"]) / cell)
        j = int((n - heat["origin_n"]) / cell)
        return heat["dz_mm"][j * nx + i]

    assert at(389070.2, 5819030.2) == pytest.approx(45, abs=2.5)
    assert abs(at(389010.2, 5819050.2)) <= 2.0


def test_ground_only_leaves_the_excavator_out(scan_path: Path, pad: Tin) -> None:
    every, _ = run_deviation(str(scan_path), "las", pad, 10.0, False)
    exp = EXP["deviation_all_classes"]
    assert (every.points_compared, every.out_count, every.max_mm) == (
        exp["points_compared"],
        exp["out_count"],
        exp["max_mm"],
    )


def test_cut_and_fill_match_expected(scan_path: Path, pad: Tin) -> None:
    exp = EXP["cutfill"]
    grid = cloud_grid(scan_path, "las", exp["cell_size_m"], exp["stat"], True)
    assert grid.cells == exp["cells"]
    r = vol.compute(Tin.from_points(grid.e, grid.n, grid.z), pad, exp["method"], exp["cell_size_m"])
    assert (round(r.cut, 3), round(r.fill, 3), round(r.net, 3)) == (exp["cut_m3"], exp["fill_m3"], exp["net_m3"])
    assert round(r.coverage_pct, 2) == exp["coverage_pct"]
    # Net is the high spot: 45 mm over the 20.5 m square its cells cover; the noise cancels.
    assert r.net == pytest.approx(PATCH_DZ * 20.5 * 20.5, abs=0.05)


def test_viewer_sample_is_coloured_and_capped(scan_path: Path, pad: Tin) -> None:
    xyz, rgb, total = run_sample(str(scan_path), "las", pad, 10.0, True, 10_000)
    assert total == EXP["scan"]["points"]
    assert 0 < len(xyz) <= 10_000
    assert rgb.shape == (len(xyz), 3)
    red = (rgb[:, 0] == 239) & (rgb[:, 1] == 68)
    assert red.any()
    assert xyz[red, 0].min() >= 389060.0
    assert xyz[red, 0].max() <= 389080.0
