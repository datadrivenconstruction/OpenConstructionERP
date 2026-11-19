# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Ground surface from a classified LAS/LAZ point cloud, streamed.

laspy (LAS 1.0-1.4) with the lazrs backend (LAZ) are base dependencies, so no
reader is added. The cloud is never loaded whole: it is read in chunks of
``CHUNK_POINTS`` (1 M points, 24 MB as float64 xyz), each point drops into a
square cell, and each cell keeps one height (min, mean or max of its points).
Memory is the cell grid, not the cloud: three float64 arrays per kept class.

Ground is ASPRS class 2. When the file has no class-2 point at all, every point
is used and SRV-080 says so; the cloud must come classified, we do not classify.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import BinaryIO, Literal

import numpy as np

CHUNK_POINTS = 1_000_000
#: Grid cells one import may hold: 4 arrays x 8 B x 2 accumulators = 64 B per cell, ~96 MB at the cap.
MAX_CELLS = 1_500_000
GROUND_CLASS = 2
Stat = Literal["min", "mean", "max"]
STATS: tuple[str, ...] = ("min", "mean", "max")


@dataclass
class CloudGrid:
    """One height per occupied cell, as cell-centre points."""

    e: np.ndarray
    n: np.ndarray
    z: np.ndarray
    points_read: int = 0
    points_used: int = 0
    ground_points: int = 0
    used_all_classes: bool = False
    cells: int = 0
    cell_size: float = 0.0
    las_version: str = ""
    compressed: bool = False
    warnings: list[str] = field(default_factory=list)


class _Acc:
    """Running min, max, sum and count per cell."""

    def __init__(self, size: int) -> None:
        self.lo = np.full(size, np.inf)
        self.hi = np.full(size, -np.inf)
        self.total = np.zeros(size)
        self.count = np.zeros(size, dtype=np.int64)

    def add(self, cell: np.ndarray, z: np.ndarray) -> None:
        if not len(cell):
            return
        np.minimum.at(self.lo, cell, z)
        np.maximum.at(self.hi, cell, z)
        self.total += np.bincount(cell, weights=z, minlength=len(self.total))
        self.count += np.bincount(cell, minlength=len(self.count))

    def value(self, stat: str) -> tuple[np.ndarray, np.ndarray]:
        occupied = np.nonzero(self.count)[0]
        if stat == "min":
            return occupied, self.lo[occupied]
        if stat == "max":
            return occupied, self.hi[occupied]
        return occupied, self.total[occupied] / self.count[occupied]


def grid_shape(min_x: float, min_y: float, max_x: float, max_y: float, cell: float) -> tuple[int, int]:
    """Columns and rows of the cell grid over the header extent."""
    nx = max(int(math.floor((max_x - min_x) / cell)) + 1, 1)
    ny = max(int(math.floor((max_y - min_y) / cell)) + 1, 1)
    return nx, ny


def read_cloud_grid(
    source: BinaryIO | str,
    cell: float,
    stat: str = "min",
    ground_only: bool = True,
    chunk_points: int = CHUNK_POINTS,
) -> CloudGrid:
    """Stream a LAS/LAZ file into one height per ``cell`` metres.

    Raises:
        ValueError: not a LAS/LAZ file, no points, or more cells than ``MAX_CELLS``.
    """
    if cell <= 0:
        raise ValueError("The cell size must be positive")
    if stat not in STATS:
        raise ValueError(f"Unknown cell statistic {stat!r}")
    import laspy  # noqa: PLC0415 - only when a cloud comes in

    try:
        reader = laspy.open(source)
    except Exception as exc:  # noqa: BLE001 - laspy raises several error types for a bad header
        raise ValueError("This is not a LAS or LAZ file") from exc
    with reader:
        h = reader.header
        total = int(h.point_count)
        if total == 0:
            raise ValueError("The point cloud has no points")
        min_x, min_y = float(h.mins[0]), float(h.mins[1])
        nx, ny = grid_shape(min_x, min_y, float(h.maxs[0]), float(h.maxs[1]), cell)
        if nx * ny > MAX_CELLS:
            raise ValueError(f"{nx * ny} cells is more than {MAX_CELLS}: choose a larger cell size")
        ground = _Acc(nx * ny)
        every = _Acc(nx * ny) if ground_only else None
        acc_all = every if every is not None else ground
        read = n_ground = 0
        for chunk in reader.chunk_iterator(chunk_points):
            x = np.asarray(chunk.x, dtype=np.float64)
            y = np.asarray(chunk.y, dtype=np.float64)
            z = np.asarray(chunk.z, dtype=np.float64)
            ix = np.clip(((x - min_x) / cell).astype(np.int64), 0, nx - 1)
            iy = np.clip(((y - min_y) / cell).astype(np.int64), 0, ny - 1)
            cells = iy * nx + ix
            read += len(x)
            if ground_only:
                is_ground = np.asarray(chunk.classification) == GROUND_CLASS
                n_ground += int(is_ground.sum())
                ground.add(cells[is_ground], z[is_ground])
            acc_all.add(cells, z)
        used_all = not ground_only or n_ground == 0
        acc = acc_all if used_all else ground
        occupied, heights = acc.value(stat)
        out = CloudGrid(
            e=min_x + (occupied % nx + 0.5) * cell,
            n=min_y + (occupied // nx + 0.5) * cell,
            z=heights,
            points_read=read,
            points_used=read if used_all else n_ground,
            ground_points=n_ground,
            used_all_classes=ground_only and n_ground == 0,
            cells=len(occupied),
            cell_size=cell,
            las_version=f"{h.version.major}.{h.version.minor}",
            compressed=bool(getattr(h, "are_points_compressed", False)),
        )
    if out.used_all_classes:
        out.warnings.append("no_ground_class")
    return out


__all__ = ["CHUNK_POINTS", "GROUND_CLASS", "MAX_CELLS", "STATS", "CloudGrid", "grid_shape", "read_cloud_grid"]
