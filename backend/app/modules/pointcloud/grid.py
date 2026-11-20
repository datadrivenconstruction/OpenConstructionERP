# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Any stored cloud (E57, LAS, LAZ) gridded to one height per cell, streamed.

LAS and LAZ go through the surfaces module's own reader unchanged, so a cloud
uploaded on the Volumes page and one picked from the scan register give the
same surface. E57 is read in chunks (:mod:`app.modules.pointcloud.stream`)
into the same :class:`CloudGrid`, with the same options: cell size (the
thinning), lowest, mean or highest point per cell, and ground only. E57 has no
classification, so "ground only" falls back to every point and says so (SRV-080),
exactly as an unclassified LAS file does.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from app.modules.pointcloud.stream import CHUNK_POINTS, E57, CloudReadError, cloud_info, iter_chunks, normal_format
from app.modules.surfaces_volumes.pointcloud import MAX_CELLS, STATS, CloudGrid, grid_shape, read_cloud_grid


class CellAccumulator:
    """Running min, max, sum and count per grid cell."""

    def __init__(self, size: int) -> None:
        self.lo = np.full(size, np.inf)
        self.hi = np.full(size, -np.inf)
        self.total = np.zeros(size)
        self.count = np.zeros(size, dtype=np.int64)

    def add(self, cell: np.ndarray, z: np.ndarray) -> None:
        """Fold one chunk of (cell index, height) pairs in."""
        if not len(cell):
            return
        np.minimum.at(self.lo, cell, z)
        np.maximum.at(self.hi, cell, z)
        self.total += np.bincount(cell, weights=z, minlength=len(self.total))
        self.count += np.bincount(cell, minlength=len(self.count))

    def value(self, stat: str) -> tuple[np.ndarray, np.ndarray]:
        """Occupied cell indices and their height by ``stat``."""
        occupied = np.nonzero(self.count)[0]
        if stat == "min":
            return occupied, self.lo[occupied]
        if stat == "max":
            return occupied, self.hi[occupied]
        return occupied, self.total[occupied] / self.count[occupied]


def _e57_grid(path: Path, cell: float, stat: str, ground_only: bool, chunk_points: int) -> CloudGrid:
    info = cloud_info(path, E57, chunk_points)
    nx, ny = grid_shape(info.min_x, info.min_y, info.max_x, info.max_y, cell)
    if nx * ny > MAX_CELLS:
        raise CloudReadError(f"{nx * ny} cells is more than {MAX_CELLS}: choose a larger cell size")
    acc = CellAccumulator(nx * ny)
    read = 0
    for ch in iter_chunks(path, E57, chunk_points):
        ix = np.clip(((ch.x - info.min_x) / cell).astype(np.int64), 0, nx - 1)
        iy = np.clip(((ch.y - info.min_y) / cell).astype(np.int64), 0, ny - 1)
        acc.add(iy * nx + ix, ch.z)
        read += len(ch.x)
    if read == 0:
        raise CloudReadError("The point cloud has no points")
    occupied, heights = acc.value(stat)
    out = CloudGrid(
        e=info.min_x + (occupied % nx + 0.5) * cell,
        n=info.min_y + (occupied // nx + 0.5) * cell,
        z=heights,
        points_read=read,
        points_used=read,
        ground_points=0,
        used_all_classes=ground_only,
        cells=len(occupied),
        cell_size=cell,
        las_version=info.version,
        compressed=True,
    )
    if ground_only:
        out.warnings.append("no_ground_class")
    return out


def cloud_grid(
    path: Path | str,
    fmt: str,
    cell: float,
    stat: str = "min",
    ground_only: bool = True,
    chunk_points: int = CHUNK_POINTS,
) -> CloudGrid:
    """Stream ``path`` into one height per ``cell`` metres.

    Raises:
        CloudReaderMissing: E57 without the optional pye57 reader.
        ValueError: bad options, an unreadable file, no points, or too many cells.
    """
    if cell <= 0:
        raise ValueError("The cell size must be positive")
    if stat not in STATS:
        raise ValueError(f"Unknown cell statistic {stat!r}")
    f = normal_format(fmt)
    if f == E57:
        return _e57_grid(Path(path), cell, stat, ground_only, chunk_points)
    return read_cloud_grid(str(path), cell, stat, ground_only, chunk_points)


__all__ = ["CellAccumulator", "cloud_grid"]
