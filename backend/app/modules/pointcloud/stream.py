# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Chunked point reading for E57, LAS and LAZ: one bounded buffer at a time.

Every consumer here (gridding to a surface, scan-vs-design deviation, the
heatmap sample for the viewer) walks the cloud once or twice and keeps only
running sums, so memory is the chunk plus the consumer's grid, never the
cloud. A 1 M point chunk is about 32 MB (xyz float64 plus class).

E57 needs the optional ``pye57`` reader (``openconstructionerp[pointcloud]``).
Scans are read through libE57's ``CompressedVectorReader`` with buffers of
``chunk_points`` records, each scan's pose is applied, spherical scans are
converted, and invalid returns are dropped. E57 carries no ASPRS
classification, so ``cls`` is ``None`` for it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

CHUNK_POINTS = 1_000_000
E57 = "e57"
LAS_FORMATS = ("las", "laz", "copc")


class CloudReaderMissing(RuntimeError):
    """The reader for ``fmt`` is not installed."""

    def __init__(self, fmt: str, reader: str) -> None:
        self.fmt = fmt
        self.reader = reader
        super().__init__(f"Reading {fmt.upper()} needs the optional {reader} reader")


class CloudReadError(ValueError):
    """The file is there and the reader is installed, but the points cannot be read."""


@dataclass
class Chunk:
    """World coordinates of one chunk; ``cls`` is the LAS class or None."""

    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    cls: np.ndarray | None = None


@dataclass
class CloudInfo:
    """What the header says, plus the plan extent (read in a pass when the header has none)."""

    fmt: str
    version: str
    declared_points: int
    has_classes: bool
    compressed: bool = False
    min_x: float = 0.0
    min_y: float = 0.0
    max_x: float = 0.0
    max_y: float = 0.0


def _pye57():  # noqa: ANN202 - optional native module
    try:
        import pye57  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as exc:
        raise CloudReaderMissing(E57, "pye57") from exc
    return pye57


def _laspy():  # noqa: ANN202
    try:
        import laspy  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - laspy is a base dependency
        raise CloudReaderMissing("las", "laspy") from exc
    return laspy


def normal_format(fmt: str) -> str:
    """Lower-case format; COPC reads as LAZ."""
    f = (fmt or "").lower().strip().lstrip(".")
    if f not in (E57, *LAS_FORMATS):
        raise CloudReadError(f"{f or 'This'} is not a point cloud format read here: use E57, LAS or LAZ")
    return f


# ── E57 ────────────────────────────────────────────────────────────────────


def _e57_open(path: Path):  # noqa: ANN202
    pye57 = _pye57()
    try:
        return pye57, pye57.E57(str(path))
    except Exception as exc:  # noqa: BLE001 - libE57 raises bare RuntimeError
        raise CloudReadError(f"This is not a readable E57 file: {exc}") from exc


def spherical_to_xyz(
    rng: np.ndarray, azimuth: np.ndarray, elevation: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """E57 spherical coordinates (range, azimuth from +X, elevation from the XY plane) to x, y, z."""
    cos_el = np.cos(elevation)
    return rng * cos_el * np.cos(azimuth), rng * cos_el * np.sin(azimuth), rng * np.sin(elevation)


def _e57_chunks(path: Path, chunk_points: int) -> Iterator[Chunk]:
    _mod, handle = _e57_open(path)
    try:
        for index in range(int(handle.scan_count)):
            header = handle.get_header(index)
            fields = set(header.point_fields)
            if {"cartesianX", "cartesianY", "cartesianZ"} <= fields:
                names = ["cartesianX", "cartesianY", "cartesianZ"]
                invalid = "cartesianInvalidState"
            elif {"sphericalRange", "sphericalAzimuth", "sphericalElevation"} <= fields:
                names = ["sphericalRange", "sphericalAzimuth", "sphericalElevation"]
                invalid = "sphericalInvalidState"
            else:
                continue
            if invalid in fields:
                names.append(invalid)
            rot = np.asarray(header.rotation_matrix, dtype=np.float64) if header.has_pose() else None
            shift = np.asarray(header.translation, dtype=np.float64) if header.has_pose() else None
            data, buffers = handle.make_buffers(names, chunk_points)
            reader = header.points.reader(buffers)
            try:
                while True:
                    k = int(reader.read())
                    if k <= 0:
                        break
                    a = np.asarray(data[names[0]][:k], dtype=np.float64)
                    b = np.asarray(data[names[1]][:k], dtype=np.float64)
                    c = np.asarray(data[names[2]][:k], dtype=np.float64)
                    if names[0] == "sphericalRange":
                        a, b, c = spherical_to_xyz(a, b, c)
                    if invalid in data:
                        ok = np.asarray(data[invalid][:k]) == 0
                        a, b, c = a[ok], b[ok], c[ok]
                    if rot is not None and shift is not None:
                        xyz = np.column_stack([a, b, c]) @ rot.T + shift
                        a, b, c = xyz[:, 0], xyz[:, 1], xyz[:, 2]
                    if len(a):
                        yield Chunk(a.copy(), b.copy(), c.copy(), None)
            except CloudReadError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise CloudReadError(f"Could not read E57 scan {index + 1}: {exc}") from exc
            finally:
                reader.close()
    finally:
        handle.close()


def _e57_info(path: Path, chunk_points: int) -> CloudInfo:
    _mod, handle = _e57_open(path)
    try:
        declared = sum(int(handle.get_header(i).point_count) for i in range(int(handle.scan_count)))
    finally:
        handle.close()
    lo = np.array([np.inf, np.inf])
    hi = np.array([-np.inf, -np.inf])
    for ch in _e57_chunks(path, chunk_points):
        lo = np.minimum(lo, [ch.x.min(), ch.y.min()])
        hi = np.maximum(hi, [ch.x.max(), ch.y.max()])
    if not np.isfinite(lo).all():
        raise CloudReadError("The point cloud has no points")
    return CloudInfo(E57, "E57 1.0", declared, False, True, float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1]))


# ── LAS / LAZ ──────────────────────────────────────────────────────────────


def _las_open(path: Path):  # noqa: ANN202
    laspy = _laspy()
    try:
        return laspy.open(str(path))
    except Exception as exc:  # noqa: BLE001 - laspy raises several error types for a bad header
        raise CloudReadError("This is not a LAS or LAZ file") from exc


def _las_chunks(path: Path, chunk_points: int) -> Iterator[Chunk]:
    with _las_open(path) as reader:
        for chunk in reader.chunk_iterator(chunk_points):
            yield Chunk(
                np.asarray(chunk.x, dtype=np.float64),
                np.asarray(chunk.y, dtype=np.float64),
                np.asarray(chunk.z, dtype=np.float64),
                np.asarray(chunk.classification, dtype=np.uint8),
            )


def _las_info(path: Path) -> CloudInfo:
    with _las_open(path) as reader:
        h = reader.header
        return CloudInfo(
            fmt="las",
            version=f"LAS {h.version.major}.{h.version.minor}",
            declared_points=int(h.point_count),
            has_classes=True,
            compressed=bool(getattr(h, "are_points_compressed", False)),
            min_x=float(h.mins[0]),
            min_y=float(h.mins[1]),
            max_x=float(h.maxs[0]),
            max_y=float(h.maxs[1]),
        )


# ── Public ─────────────────────────────────────────────────────────────────


def cloud_info(path: Path | str, fmt: str, chunk_points: int = CHUNK_POINTS) -> CloudInfo:
    """Header facts and plan extent; for E57 the extent costs one streamed pass."""
    f = normal_format(fmt)
    return _e57_info(Path(path), chunk_points) if f == E57 else _las_info(Path(path))


def quick_info(path: Path | str, fmt: str) -> tuple[int, float | None]:
    """Declared point count and plan area from the header alone (E57 headers carry no usable area)."""
    f = normal_format(fmt)
    if f == E57:
        _mod, handle = _e57_open(Path(path))
        try:
            return sum(int(handle.get_header(i).point_count) for i in range(int(handle.scan_count))), None
        finally:
            handle.close()
    info = _las_info(Path(path))
    return info.declared_points, max(info.max_x - info.min_x, 0.0) * max(info.max_y - info.min_y, 0.0)


def iter_chunks(path: Path | str, fmt: str, chunk_points: int = CHUNK_POINTS) -> Iterator[Chunk]:
    """Yield the cloud in chunks of at most ``chunk_points`` points, world coordinates."""
    f = normal_format(fmt)
    if f == E57:
        yield from _e57_chunks(Path(path), chunk_points)
    else:
        yield from _las_chunks(Path(path), chunk_points)


__all__ = [
    "CHUNK_POINTS",
    "Chunk",
    "CloudInfo",
    "CloudReadError",
    "CloudReaderMissing",
    "cloud_info",
    "iter_chunks",
    "normal_format",
    "quick_info",
]
