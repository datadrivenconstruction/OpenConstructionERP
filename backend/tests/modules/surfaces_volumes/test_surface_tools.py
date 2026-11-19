# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Point cloud gridding, breaklines kept as TIN edges, and staged volumes (DOMAIN_V2 P1 examples)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.modules.surfaces_volumes.pointcloud import read_cloud_grid
from app.modules.surfaces_volumes.staged import Factors, staged_volumes, strip
from app.modules.surfaces_volumes.tin import Tin


def _write_las(path: Path, x: np.ndarray, y: np.ndarray, z: np.ndarray, cls: np.ndarray) -> Path:
    import laspy

    header = laspy.LasHeader(point_format=1, version="1.2")
    header.offsets = [float(x.min()), float(y.min()), 0.0]
    header.scales = [0.001, 0.001, 0.001]
    las = laspy.LasData(header)
    las.x, las.y, las.z = x, y, z
    las.classification = cls.astype(np.uint8)
    las.write(str(path))
    return path


def _flat(e0: float, n0: float, size: float, z: float, step: float = 1.0) -> Tin:
    g = np.arange(0.0, size + step / 2, step)
    gx, gy = np.meshgrid(e0 + g, n0 + g)
    return Tin.from_points(gx.ravel(), gy.ravel(), np.full(gx.size, z))


# ── Point cloud ────────────────────────────────────────────────────────────


def test_domain_example_1_2_million_points_on_half_metre_cells_give_40000_cells(tmp_path: Path) -> None:
    """1.2 M points over 100 x 100 m on a 0.5 m grid is 40,000 cells, read in 1 M point chunks."""
    rng = np.random.default_rng(7)
    n = 1_200_000
    x = 389000.0 + rng.uniform(0, 99.999, n)
    y = 5819000.0 + rng.uniform(0, 99.999, n)
    z = 30.0 + 0.01 * (x - 389000.0)
    x[:4], y[:4] = [389000.0, 389099.999, 389000.0, 389099.999], [5819000.0, 5819000.0, 5819099.999, 5819099.999]
    path = _write_las(tmp_path / "drone.las", x, y, z, np.full(n, 2))
    grid = read_cloud_grid(str(path), 0.5, "mean")
    assert grid.points_read == n
    assert grid.cells == 40_000
    assert not grid.used_all_classes
    assert grid.las_version == "1.2"


def test_ground_class_only_and_the_cell_statistic(tmp_path: Path) -> None:
    # Four points per 1 m cell: two ground at 10.00/10.20 and two vegetation (class 5) at 12.0.
    xs, ys, zs, cs = [], [], [], []
    for i in range(4):
        for j in range(4):
            for dx, dz, c in ((0.2, 10.0, 2), (0.4, 10.2, 2), (0.6, 12.0, 5), (0.8, 12.0, 5)):
                xs.append(i + dx)
                ys.append(j + 0.5)
                zs.append(dz)
                cs.append(c)
    path = _write_las(tmp_path / "site.las", *(np.array(v, dtype=float) for v in (xs, ys, zs, cs)))
    low = read_cloud_grid(str(path), 1.0, "min", chunk_points=7)
    assert low.cells == 16
    assert low.points_used == 32
    assert np.allclose(low.z, 10.0)
    mean = read_cloud_grid(str(path), 1.0, "mean")
    assert np.allclose(mean.z, 10.1)
    everything = read_cloud_grid(str(path), 1.0, "max", ground_only=False)
    assert np.allclose(everything.z, 12.0)
    assert everything.points_used == 64
    assert not everything.used_all_classes


def test_no_ground_class_uses_all_points_and_says_so(tmp_path: Path) -> None:
    x = np.array([0.1, 1.1, 2.1, 0.1, 1.1, 2.1])
    y = np.array([0.1, 0.1, 0.1, 1.1, 1.1, 1.1])
    path = _write_las(tmp_path / "raw.las", x, y, np.full(6, 5.0), np.ones(6))
    grid = read_cloud_grid(str(path), 1.0)
    assert grid.used_all_classes
    assert grid.warnings == ["no_ground_class"]
    assert grid.cells == 6


def test_laz_is_read_through_the_lazrs_backend(tmp_path: Path) -> None:
    import laspy

    x = np.array([0.1, 1.1, 0.1, 1.1])
    y = np.array([0.1, 0.1, 1.1, 1.1])
    las_path = _write_las(tmp_path / "a.las", x, y, np.full(4, 3.0), np.full(4, 2))
    las = laspy.read(str(las_path))
    laz_path = tmp_path / "a.laz"
    las.write(str(laz_path), laz_backend=laspy.LazBackend.Lazrs)
    grid = read_cloud_grid(str(laz_path), 1.0)
    assert grid.cells == 4
    assert grid.compressed


def test_a_file_that_is_not_las_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "x.las"
    bad.write_bytes(b"not a point cloud")
    with pytest.raises(ValueError, match="not a LAS"):
        read_cloud_grid(str(bad), 1.0)


# ── Breaklines ─────────────────────────────────────────────────────────────


def _edges(tin: Tin) -> set[tuple[int, int]]:
    out = set()
    for a, b, c in tin.tri:
        for i, j in ((a, b), (b, c), (c, a)):
            out.add((min(int(i), int(j)), max(int(i), int(j))))
    return out


def _index(tin: Tin, e: float, n: float) -> int:
    return int(np.argmin((tin.e - e) ** 2 + (tin.n - n) ** 2))


def test_a_ridge_breakline_becomes_an_edge_and_carries_its_height() -> None:
    # A short pair of low points straddles the ridge, so plain Delaunay bridges it.
    e = [0, 10, 10, 0, 5, 5]
    n = [0, 0, 10, 10, 4.9, 5.1]
    z = [0, 0, 0, 0, 0, 0]
    plain = Tin.from_points(e, n, z)
    ridge = [(1.0, 5.0, 2.0), (9.0, 5.0, 2.0)]
    with_ridge = Tin.from_points_with_breaklines(e, n, z, [ridge])
    assert with_ridge.missed_segments == 0
    a, b = _index(with_ridge, 1, 5), _index(with_ridge, 9, 5)
    # The ridge may be split at no vertex here, so the whole segment is one edge.
    assert (min(a, b), max(a, b)) in _edges(with_ridge)
    assert with_ridge.sample(np.array([5.0]), np.array([5.0]))[0] == pytest.approx(2.0)
    assert plain.sample(np.array([5.0]), np.array([5.0]))[0] == pytest.approx(0.0)


def test_a_long_breakline_across_a_grid_keeps_every_segment() -> None:
    g = np.arange(0.0, 21.0, 1.0)
    gx, gy = np.meshgrid(g, g)
    line = [(0.5, 0.3, 5.0), (7.2, 6.9, 6.0), (13.7, 12.4, 7.0), (19.7, 18.2, 8.0)]
    tin = Tin.from_points_with_breaklines(gx.ravel(), gy.ravel(), np.zeros(gx.size), [line])
    assert tin.missed_segments == 0
    edges = _edges(tin)
    for (e0, n0, _), (e1, n1, _) in zip(line[:-1], line[1:], strict=True):
        assert (min(_index(tin, e0, n0), _index(tin, e1, n1)), max(_index(tin, e0, n0), _index(tin, e1, n1))) in edges
    assert tin.area() == pytest.approx(400.0)


def test_a_breakline_through_an_existing_vertex_is_split_there() -> None:
    g = np.arange(0.0, 5.0, 1.0)
    gx, gy = np.meshgrid(g, g)
    tin = Tin.from_points_with_breaklines(
        gx.ravel(), gy.ravel(), np.zeros(gx.size), [[(0.0, 0.0, 1.0), (4.0, 4.0, 1.0)]]
    )
    assert tin.missed_segments == 0
    edges = _edges(tin)
    for k in range(4):
        a, b = _index(tin, k, k), _index(tin, k + 1, k + 1)
        assert (min(a, b), max(a, b)) in edges


def test_a_boundary_drops_the_triangles_outside_it() -> None:
    g = np.arange(0.0, 11.0, 1.0)
    gx, gy = np.meshgrid(g, g)
    tin = Tin.from_points_with_breaklines(
        gx.ravel(), gy.ravel(), np.zeros(gx.size), [], boundary=[(0, 0), (5, 0), (5, 10), (0, 10)]
    )
    assert tin.area() == pytest.approx(50.0)


# ── Staged volumes ─────────────────────────────────────────────────────────


def test_staged_topsoil_strip_then_bulk_cut_then_fill() -> None:
    """20 x 20 m at 10.00: strip 0.30 m (120 m3), cut to 8.00 (680 m3), fill back to 8.50 (200 m3)."""
    ground = _flat(0, 0, 20, 10.0)
    stripped = strip(ground, 0.3)
    formation = _flat(0, 0, 20, 8.0)
    filled = _flat(0, 0, 20, 8.5)
    steps = staged_volumes(
        [("Ground", ground), ("Stripped", stripped), ("Formation", formation), ("Fill", filled)],
        ["topsoil", "clay", "granular"],
        {"topsoil": Factors(loose=1.25), "granular": Factors(compacted=0.9)},
        cell=1.0,
    )
    assert [round(s.cut, 3) for s in steps] == [120.0, 680.0, 0.0]
    assert [round(s.fill, 3) for s in steps] == [0.0, 0.0, 200.0]
    assert steps[0].cut_loose == pytest.approx(150.0)
    assert steps[1].cut_loose is None
    assert steps[2].fill_bank_needed == pytest.approx(222.222, abs=1e-3)
    assert sum(s.cut for s in steps) == pytest.approx(800.0)


def test_staged_needs_two_stages() -> None:
    with pytest.raises(ValueError, match="two stages"):
        staged_volumes([("Only", _flat(0, 0, 5, 1.0))], [], {})
