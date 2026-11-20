# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""E57 on the same path as LAS: chunked reading, pose, spherical scans, gridding, and the missing reader."""

from __future__ import annotations

import builtins
from pathlib import Path

import numpy as np
import pytest

from app.modules.pointcloud import stream
from app.modules.pointcloud.grid import cloud_grid
from app.modules.pointcloud.scan_design_service import run_deviation
from app.modules.pointcloud.survey_demo import build_pad_scan, pad_points
from app.modules.surfaces_volumes.tin import Tin

pye57 = pytest.importorskip("pye57")

SHIFT = np.array([389000.0, 5819000.0, 30.0])


def _write_e57(path: Path, x: np.ndarray, y: np.ndarray, z: np.ndarray) -> None:
    """Points stored in the scanner frame, with the scan pose moving them to the project grid."""
    with pye57.E57(str(path), mode="w") as w:
        w.write_scan_raw(
            {"cartesianX": x - SHIFT[0], "cartesianY": y - SHIFT[1], "cartesianZ": z - SHIFT[2]},
            rotation=np.array([1.0, 0.0, 0.0, 0.0]),
            translation=SHIFT,
        )


@pytest.fixture(scope="module")
def pad_e57(tmp_path_factory: pytest.TempPathFactory) -> Path:
    x, y, z, cls = pad_points()
    ground = cls == 2
    path = tmp_path_factory.mktemp("e57") / "pad.e57"
    _write_e57(path, x[ground], y[ground], z[ground])
    return path


@pytest.fixture(scope="module")
def pad() -> Tin:
    return Tin.from_points([389000, 389100, 389100, 389000], [5819000, 5819000, 5819060, 5819060], [34.3] * 4)


def test_chunks_carry_the_pose_and_every_point(pad_e57: Path) -> None:
    chunks = list(stream.iter_chunks(pad_e57, "e57", chunk_points=5000))
    assert len(chunks) == 5  # 24321 points in chunks of 5000
    total = sum(len(c.x) for c in chunks)
    assert total == 24321
    assert chunks[0].cls is None
    assert min(c.x.min() for c in chunks) == pytest.approx(389000.0, abs=1e-6)
    assert max(c.y.max() for c in chunks) == pytest.approx(5819060.0, abs=1e-6)
    assert stream.quick_info(pad_e57, "e57") == (24321, None)


def test_e57_grid_matches_the_las_grid(pad_e57: Path, tmp_path: Path) -> None:
    las = tmp_path / "pad.las"
    las.write_bytes(build_pad_scan())
    a = cloud_grid(pad_e57, "e57", 0.5, "min", ground_only=False, chunk_points=7000)
    b = cloud_grid(las, "las", 0.5, "min", ground_only=True)
    assert a.cells == b.cells == 24321
    assert a.las_version.startswith("E57")
    assert np.allclose(np.sort(a.z), np.sort(b.z), atol=1e-6)


def test_e57_ground_only_falls_back_to_every_point_and_says_so(pad_e57: Path) -> None:
    g = cloud_grid(pad_e57, "e57", 1.0, "mean", ground_only=True)
    assert g.used_all_classes is True
    assert g.warnings == ["no_ground_class"]


def test_e57_deviation_equals_las_deviation(pad_e57: Path, pad: Tin, tmp_path: Path) -> None:
    las = tmp_path / "pad.las"
    las.write_bytes(build_pad_scan())
    e, used_all = run_deviation(str(pad_e57), "e57", pad, 10.0, True)
    lv, _ = run_deviation(str(las), "las", pad, 10.0, True)
    assert used_all is True
    assert (e.points_compared, e.out_count, e.rms_mm, e.p95_mm) == (
        lv.points_compared,
        lv.out_count,
        lv.rms_mm,
        lv.p95_mm,
    )


def test_spherical_coordinates_are_converted() -> None:
    rng_ = np.array([10.0, 10.0, 5.0])
    az = np.array([0.0, np.pi / 2, 0.0])
    el = np.array([0.0, 0.0, np.pi / 2])
    x, y, z = stream.spherical_to_xyz(rng_, az, el)
    assert np.allclose(np.column_stack([x, y, z]), [[10, 0, 0], [0, 10, 0], [0, 0, 5]], atol=1e-9)


def test_missing_reader_is_named(monkeypatch: pytest.MonkeyPatch, pad_e57: Path) -> None:
    real = builtins.__import__

    def deny(name: str, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        if name == "pye57":
            raise ImportError("no pye57")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny)
    with pytest.raises(stream.CloudReaderMissing) as err:
        next(stream.iter_chunks(pad_e57, "e57"))
    assert err.value.reader == "pye57"


def test_unknown_format_is_refused() -> None:
    with pytest.raises(stream.CloudReadError):
        stream.normal_format("rcp")
