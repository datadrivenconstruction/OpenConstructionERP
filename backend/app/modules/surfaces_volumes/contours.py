# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contours of a TIN and the automatic interval.

Each triangle is cut by every level it spans; the pieces are joined end to end
into polylines through shared triangle edges, so a contour is continuous across
the surface and closes on itself where it does not leave the outline.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from app.modules.surfaces_volumes.tin import Tin

#: Intervals a surveyor would pick; the automatic one gives about :data:`TARGET_LINES` lines.
NICE_INTERVALS = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0)
TARGET_LINES = 20
INDEX_EVERY = 5
#: A request never builds more levels than this (a 1 cm interval over a mountain).
MAX_LEVELS = 500


@dataclass
class ContourLine:
    """One contour polyline at height ``z``; ``closed`` when it returns to its start."""

    z: float
    index: bool
    coords: list[tuple[float, float]] = field(default_factory=list)
    closed: bool = False


def auto_interval(z_min: float, z_max: float, target: int = TARGET_LINES) -> float:
    """The nice interval whose line count is closest to ``target`` for this height range."""
    span = max(z_max - z_min, 0.0)
    if span <= 0:
        return NICE_INTERVALS[0]
    return min(NICE_INTERVALS, key=lambda i: (abs(span / i - target), i))


def levels(z_min: float, z_max: float, interval: float) -> list[float]:
    """Multiples of ``interval`` strictly inside the height range (a level at the very top or bottom is a point)."""
    if interval <= 0 or not math.isfinite(z_min) or not math.isfinite(z_max):
        return []
    first = math.ceil(z_min / interval - 1e-9)
    last = math.floor(z_max / interval + 1e-9)
    out = [round(k * interval, 6) for k in range(first, last + 1)]
    out = [z for z in out if z_min + 1e-9 < z < z_max - 1e-9]
    return out[:MAX_LEVELS]


def is_index(z: float, interval: float, every: int = INDEX_EVERY) -> bool:
    """Whether ``z`` is an index contour (every ``every``-th multiple of the interval)."""
    k = round(z / interval)
    return k % every == 0


def _edge_point(tin: Tin, a: int, b: int, z: float) -> tuple[float, float]:
    za, zb = float(tin.z[a]), float(tin.z[b])
    t = (z - za) / (zb - za)
    return (
        float(tin.e[a] + t * (tin.e[b] - tin.e[a])),
        float(tin.n[a] + t * (tin.n[b] - tin.n[a])),
    )


def _segments(tin: Tin, z: float) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Per triangle crossing ``z``: the two crossed edges (as sorted vertex pairs)."""
    # Nudge vertex heights that sit exactly on the level so every crossing is a clean edge cut.
    out = []
    zz = np.where(np.abs(tin.z - z) < 1e-9, tin.z + 1e-7, tin.z)
    above = zz > z
    for tri in tin.tri:
        flags = above[tri]
        if flags.all() or not flags.any():
            continue
        crossed = [
            (min(int(tri[i]), int(tri[(i + 1) % 3])), max(int(tri[i]), int(tri[(i + 1) % 3])))
            for i in range(3)
            if flags[i] != flags[(i + 1) % 3]
        ]
        if len(crossed) == 2:
            out.append((crossed[0], crossed[1]))
    return out


def _chain(segments: list[tuple[tuple[int, int], tuple[int, int]]]) -> list[tuple[list[tuple[int, int]], bool]]:
    """Join segments that share an edge into ordered edge chains; ``True`` when a chain closes."""
    by_edge: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (a, b) in enumerate(segments):
        by_edge[a].append(i)
        by_edge[b].append(i)
    used = [False] * len(segments)
    chains: list[tuple[list[tuple[int, int]], bool]] = []

    def walk(start_seg: int, from_edge: tuple[int, int]) -> list[tuple[int, int]]:
        path: list[tuple[int, int]] = []
        seg, edge = start_seg, from_edge
        while True:
            used[seg] = True
            a, b = segments[seg]
            nxt = b if a == edge else a
            path.append(nxt)
            following = [s for s in by_edge[nxt] if not used[s]]
            if not following:
                return path
            seg, edge = following[0], nxt

    for i in range(len(segments)):
        if used[i]:
            continue
        a, b = segments[i]
        forward = walk(i, a)
        closed = forward[-1] == a
        if closed:
            chains.append(([a, *forward[:-1], a], True))
            continue
        # Open: extend backwards from ``a`` too, then stitch.
        back = (
            []
            if len([s for s in by_edge[a] if not used[s]]) == 0
            else walk(next(s for s in by_edge[a] if not used[s]), a)
        )
        chains.append(([*reversed(back), a, *forward], False))
    return chains


def contour_at(tin: Tin, z: float) -> list[ContourLine]:
    """The contour polylines of ``tin`` at one height ``z``, longest first."""
    out = []
    for edges, closed in _chain(_segments(tin, z)):
        coords = [_edge_point(tin, a, b, z) for a, b in edges]
        if len(coords) >= 2:
            out.append(
                ContourLine(z=z, index=False, coords=[(round(e, 4), round(n, 4)) for e, n in coords], closed=closed)
            )
    return sorted(out, key=lambda c: -len(c.coords))


def contour_lines(tin: Tin, interval: float, every: int = INDEX_EVERY) -> list[ContourLine]:
    """All contours of ``tin`` at multiples of ``interval``."""
    if not len(tin.tri) or interval <= 0:
        return []
    out: list[ContourLine] = []
    for z in levels(float(tin.z.min()), float(tin.z.max()), interval):
        for edges, closed in _chain(_segments(tin, z)):
            coords = [_edge_point(tin, a, b, z) for a, b in edges]
            if len(coords) < 2:
                continue
            out.append(
                ContourLine(
                    z=z,
                    index=is_index(z, interval, every),
                    coords=[(round(e, 4), round(n, 4)) for e, n in coords],
                    closed=closed,
                )
            )
    return out


__all__ = [
    "INDEX_EVERY",
    "NICE_INTERVALS",
    "ContourLine",
    "auto_interval",
    "contour_at",
    "contour_lines",
    "is_index",
    "levels",
]
