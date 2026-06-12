# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Server-side point-cloud decode and decimation.

The viewer follows the lightweight path: instead of streaming a full COPC
octree to the browser, the backend decodes the raw upload (E57 / LAS / LAZ),
decimates it to a render-friendly cap, and hands the browser a compact binary
buffer it can drop straight into a ``THREE.Points`` geometry.

Decoding leans on optional native readers so the rest of the platform stays
lightweight:

* ``pye57``        - E57 (the dominant terrestrial-scanner exchange format)
* ``laspy`` (+lazrs) - LAS and LAZ

Both are optional. When a reader is missing the decode raises
``PointDecodeUnavailable`` so the API can answer with a clear 501 instead of a
crash, and the platform still installs and runs without the point-cloud extra.

This module is intentionally pure and synchronous: it takes a local file path,
returns numpy arrays, and never touches the database, the session or storage.
The service layer wraps it in ``asyncio.to_thread`` and owns I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


class PointDecodeUnavailable(RuntimeError):
    """Raised when no installed reader can decode the requested format.

    Carries the offending format so the API can surface a precise, translatable
    message ("install the pointcloud extra to view E57 scans") rather than a
    generic 500.
    """

    def __init__(self, fmt: str, reader: str) -> None:
        self.fmt = fmt
        self.reader = reader
        super().__init__(f"No reader available for {fmt!r} (needs {reader})")


class PointDecodeError(RuntimeError):
    """Raised when a file is present and the reader is installed but the bytes
    cannot be decoded (truncated upload, wrong extension, empty scan)."""


@dataclass(slots=True)
class DecodedPoints:
    """Decimated point payload, ready to pack for the wire.

    ``xyz`` is centred on ``center`` (float64 origin subtracted) and stored as
    float32 so large georeferenced coordinates keep millimetre precision in the
    browser. ``rgb`` is uint8 0-255 or ``None``; ``intensity`` is float32
    normalised 0-1 or ``None``. ``bbox_min`` / ``bbox_max`` are in the original
    (un-centred) coordinate frame so the UI can show real extents.
    """

    xyz: np.ndarray  # (N, 3) float32, centred
    rgb: np.ndarray | None  # (N, 3) uint8 or None
    intensity: np.ndarray | None  # (N,) float32 0-1 or None
    center: tuple[float, float, float]  # subtracted origin (world frame)
    bbox_min: tuple[float, float, float]  # world frame
    bbox_max: tuple[float, float, float]  # world frame
    returned_count: int
    total_count: int  # valid points before decimation


_E57_FORMATS = {"e57"}
_LAS_FORMATS = {"las", "laz", "copc"}


def _decimate_indices(n: int, max_points: int) -> np.ndarray | None:
    """Pick a stable, evenly-spread subset of ``n`` points capped at
    ``max_points``. Returns ``None`` when no decimation is needed.

    Uses a deterministic stride rather than random sampling so repeated reads of
    the same scan return the same points (stable selection, no flicker on
    re-fetch) and so the spread stays spatially uniform for files whose points
    are stored in scan order.
    """
    if max_points <= 0 or n <= max_points:
        return None
    stride = n / float(max_points)
    idx = (np.arange(max_points, dtype=np.float64) * stride).astype(np.int64)
    return np.clip(idx, 0, n - 1)


def _finalise(
    xyz: np.ndarray,
    rgb: np.ndarray | None,
    intensity: np.ndarray | None,
    *,
    total_count: int,
) -> DecodedPoints:
    """Compute bbox + centre, centre the coordinates, cast to wire dtypes."""
    if xyz.shape[0] == 0:
        raise PointDecodeError("Scan contains no valid points")

    bbox_min = xyz.min(axis=0)
    bbox_max = xyz.max(axis=0)
    center = ((bbox_min + bbox_max) * 0.5).astype(np.float64)

    centred = (xyz - center).astype(np.float32, copy=False)

    rgb_out = None
    if rgb is not None and rgb.shape[0] == xyz.shape[0]:
        rgb_out = np.ascontiguousarray(rgb.astype(np.uint8, copy=False))

    inten_out = None
    if intensity is not None and intensity.shape[0] == xyz.shape[0]:
        inten = intensity.astype(np.float32, copy=False)
        lo = float(inten.min())
        hi = float(inten.max())
        if hi > lo:
            inten = (inten - lo) / (hi - lo)
        else:
            inten = np.zeros_like(inten)
        inten_out = np.ascontiguousarray(inten)

    return DecodedPoints(
        xyz=np.ascontiguousarray(centred),
        rgb=rgb_out,
        intensity=inten_out,
        center=(float(center[0]), float(center[1]), float(center[2])),
        bbox_min=(float(bbox_min[0]), float(bbox_min[1]), float(bbox_min[2])),
        bbox_max=(float(bbox_max[0]), float(bbox_max[1]), float(bbox_max[2])),
        returned_count=int(xyz.shape[0]),
        total_count=int(total_count),
    )


def _decode_e57(path: Path, max_points: int) -> DecodedPoints:
    try:
        import pye57  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised via API 501 path
        raise PointDecodeUnavailable("e57", "pye57") from exc

    try:
        handle = pye57.E57(str(path))
    except Exception as exc:  # noqa: BLE001 - pye57 raises bare RuntimeError
        raise PointDecodeError(f"Could not open E57: {exc}") from exc

    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    zs: list[np.ndarray] = []
    rs: list[np.ndarray] = []
    gs: list[np.ndarray] = []
    bs: list[np.ndarray] = []
    insts: list[np.ndarray] = []
    have_rgb = True
    have_int = True
    total = 0

    scan_count = max(1, int(getattr(handle, "scan_count", 1)))
    for scan_idx in range(scan_count):
        try:
            data = handle.read_scan(scan_idx, ignore_missing_fields=True, colors=True, intensity=True)
        except Exception as exc:  # noqa: BLE001
            raise PointDecodeError(f"Could not read E57 scan {scan_idx}: {exc}") from exc

        x = np.asarray(data.get("cartesianX"), dtype=np.float64)
        if x.size == 0:
            continue
        y = np.asarray(data["cartesianY"], dtype=np.float64)
        z = np.asarray(data["cartesianZ"], dtype=np.float64)

        # E57 marks dropped returns via cartesianInvalidState (0 == valid).
        state = data.get("cartesianInvalidState")
        if state is not None:
            mask = np.asarray(state) == 0
            if mask.shape[0] == x.shape[0] and not mask.all():
                x, y, z = x[mask], y[mask], z[mask]
        else:
            mask = None

        total += x.shape[0]
        xs.append(x)
        ys.append(y)
        zs.append(z)

        if have_rgb and "colorRed" in data:
            r = np.asarray(data["colorRed"])
            g = np.asarray(data["colorGreen"])
            b = np.asarray(data["colorBlue"])
            if mask is not None and mask.shape[0] == r.shape[0]:
                r, g, b = r[mask], g[mask], b[mask]
            rs.append(r)
            gs.append(g)
            bs.append(b)
        else:
            have_rgb = False

        if have_int and "intensity" in data:
            it = np.asarray(data["intensity"])
            if mask is not None and mask.shape[0] == it.shape[0]:
                it = it[mask]
            insts.append(it)
        else:
            have_int = False

    if not xs:
        raise PointDecodeError("E57 contains no point data")

    xyz = np.column_stack([np.concatenate(xs), np.concatenate(ys), np.concatenate(zs)])
    rgb = None
    if have_rgb and rs:
        rgb = np.column_stack([np.concatenate(rs), np.concatenate(gs), np.concatenate(bs)])
        if float(rgb.max()) <= 1.0:  # some writers emit 0-1 floats
            rgb = rgb * 255.0
        rgb = np.clip(rgb, 0, 255)
    intensity = np.concatenate(insts) if (have_int and insts) else None

    idx = _decimate_indices(xyz.shape[0], max_points)
    if idx is not None:
        xyz = xyz[idx]
        if rgb is not None:
            rgb = rgb[idx]
        if intensity is not None:
            intensity = intensity[idx]

    return _finalise(xyz, rgb, intensity, total_count=total)


def _decode_las(path: Path, max_points: int) -> DecodedPoints:
    try:
        import laspy  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised via API 501 path
        raise PointDecodeUnavailable("las", "laspy[lazrs]") from exc

    try:
        las = laspy.read(str(path))
    except Exception as exc:  # noqa: BLE001 - laspy raises various errors
        raise PointDecodeError(f"Could not read LAS/LAZ: {exc}") from exc

    xyz = np.column_stack(
        [np.asarray(las.x, dtype=np.float64), np.asarray(las.y, dtype=np.float64), np.asarray(las.z, dtype=np.float64)]
    )
    total = xyz.shape[0]
    if total == 0:
        raise PointDecodeError("LAS/LAZ contains no point data")

    dims = set(las.point_format.dimension_names)
    rgb = None
    if {"red", "green", "blue"} <= dims:
        r = np.asarray(las.red, dtype=np.float64)
        g = np.asarray(las.green, dtype=np.float64)
        b = np.asarray(las.blue, dtype=np.float64)
        # LAS stores 16-bit colour; scale to 8-bit when the range demands it.
        if max(float(r.max()), float(g.max()), float(b.max())) > 255.0:
            r, g, b = r / 257.0, g / 257.0, b / 257.0
        rgb = np.clip(np.column_stack([r, g, b]), 0, 255)

    intensity = np.asarray(las.intensity, dtype=np.float64) if "intensity" in dims else None
    classification = np.asarray(las.classification) if "classification" in dims else None

    idx = _decimate_indices(total, max_points)
    if idx is not None:
        xyz = xyz[idx]
        if rgb is not None:
            rgb = rgb[idx]
        if intensity is not None:
            intensity = intensity[idx]
        if classification is not None:
            classification = classification[idx]

    decoded = _finalise(xyz, rgb, intensity, total_count=total)
    return decoded


def decode_points(path: Path, fmt: str, *, max_points: int = 1_500_000) -> DecodedPoints:
    """Decode and decimate a raw point-cloud file to a render-friendly payload.

    ``fmt`` is the normalised upload format (``e57`` / ``las`` / ``laz`` / ...).
    Raises :class:`PointDecodeUnavailable` (map to 501) when the reader for the
    format is not installed, :class:`PointDecodeError` (map to 422) when the file
    is present but undecodable.
    """
    fmt = (fmt or "").lower().strip()
    if fmt in _E57_FORMATS:
        return _decode_e57(path, max_points)
    if fmt in _LAS_FORMATS:
        return _decode_las(path, max_points)
    raise PointDecodeUnavailable(fmt or "unknown", "a supported reader (E57 or LAS/LAZ)")
