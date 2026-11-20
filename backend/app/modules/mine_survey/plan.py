# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mine geometry for the plan: the outline of a blast block from its design collars.

The block outline is the convex hull of the collars pushed out by half the hole
spacing, so the outline sits where the rock that each edge row breaks ends.
"""

from __future__ import annotations

import math
import statistics

from app.modules.surfaces_volumes.pad import mitre_directions

Pt = tuple[float, float]


def convex_hull(points: list[Pt]) -> list[Pt]:
    """Counter-clockwise convex hull (monotone chain); fewer than three distinct points come back as given."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o: Pt, a: Pt, b: Pt) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Pt] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Pt] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def hole_spacing(points: list[Pt]) -> float:
    """Median distance from each collar to its nearest neighbour, m; 0 for fewer than two holes."""
    if len(points) < 2:
        return 0.0
    nearest = []
    for i, (x, y) in enumerate(points):
        nearest.append(min(math.hypot(x - a, y - b) for j, (a, b) in enumerate(points) if j != i))
    return float(statistics.median(nearest))


def block_outline(collars: list[Pt]) -> tuple[list[Pt], float]:
    """The block outline and the hole spacing it was offset by."""
    hull = convex_hull(collars)
    spacing = hole_spacing(collars)
    if len(hull) < 3:
        return hull, spacing
    half = spacing / 2.0
    ring = [
        (round(x + dx * half, 4), round(y + dy * half, 4))
        for (x, y), (dx, dy) in zip(hull, mitre_directions(hull), strict=True)
    ]
    return ring, spacing


__all__ = ["block_outline", "convex_hull", "hole_spacing"]
