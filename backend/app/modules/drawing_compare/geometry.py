# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure geometry for drawing revision compare.

No database, no I/O: rectangles, affine transforms between two sheets, the
merge of nearby change boxes into regions, and the test of whether a takeoff
measurement or markup sits inside a changed region. Coordinates are the frame
of the newer revision (PDF units with a top-left origin for sheets, drawing
units for DWG/DXF).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

# Affine as six numbers in the PDF order: x' = a*x + c*y + e, y' = b*x + d*y + f.
IDENTITY: tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle given by its top-left corner and size."""

    x: float
    y: float
    w: float
    h: float

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    @property
    def area(self) -> float:
        return max(self.w, 0.0) * max(self.h, 0.0)

    def expanded(self, margin: float) -> Rect:
        """The rectangle grown by ``margin`` on every side."""
        return Rect(self.x - margin, self.y - margin, self.w + 2 * margin, self.h + 2 * margin)

    def intersects(self, other: Rect) -> bool:
        """Whether the two rectangles overlap or touch."""
        return not (other.x > self.x2 or other.x2 < self.x or other.y > self.y2 or other.y2 < self.y)

    def union(self, other: Rect) -> Rect:
        """The smallest rectangle holding both."""
        x = min(self.x, other.x)
        y = min(self.y, other.y)
        return Rect(x, y, max(self.x2, other.x2) - x, max(self.y2, other.y2) - y)

    def contains_point(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x2 and self.y <= py <= self.y2


def rect_from_points(points: Iterable[tuple[float, float]]) -> Rect | None:
    """Bounding box of points, ``None`` when there are none."""
    xs: list[float] = []
    ys: list[float] = []
    for px, py in points:
        xs.append(px)
        ys.append(py)
    if not xs:
        return None
    return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def apply_affine(matrix: Sequence[float], px: float, py: float) -> tuple[float, float]:
    """Map one point through ``matrix``."""
    a, b, c, d, e, f = matrix
    return a * px + c * py + e, b * px + d * py + f


def invert_affine(matrix: Sequence[float]) -> tuple[float, float, float, float, float, float]:
    """Inverse of an affine; raises ``ValueError`` when it is singular."""
    a, b, c, d, e, f = matrix
    det = a * d - b * c
    if abs(det) < 1e-12:
        raise ValueError("singular transform")
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return ia, ib, ic, id_, -(ia * e + ic * f), -(ib * e + id_ * f)


def affine_scale_rotation(matrix: Sequence[float]) -> tuple[float, float]:
    """Uniform scale and rotation (degrees) a similarity transform applies."""
    a, b, _c, _d, _e, _f = matrix
    return math.hypot(a, b), math.degrees(math.atan2(b, a))


def similarity_from_two_points(
    old_points: Sequence[tuple[float, float]],
    new_points: Sequence[tuple[float, float]],
) -> tuple[float, float, float, float, float, float]:
    """Similarity transform taking two old points onto two new points.

    The manual two-point alignment: the user clicks the same two marks
    (grid intersections, frame corners) on both revisions.
    """
    (ox1, oy1), (ox2, oy2) = old_points
    (nx1, ny1), (nx2, ny2) = new_points
    vox, voy = ox2 - ox1, oy2 - oy1
    vnx, vny = nx2 - nx1, ny2 - ny1
    old_len = math.hypot(vox, voy)
    if old_len < 1e-9 or math.hypot(vnx, vny) < 1e-9:
        raise ValueError("alignment points coincide")
    scale = math.hypot(vnx, vny) / old_len
    angle = math.atan2(vny, vnx) - math.atan2(voy, vox)
    a = scale * math.cos(angle)
    b = scale * math.sin(angle)
    # Rotation part maps (x, y) to (a*x - b*y, b*x + a*y), so c = -b, d = a.
    e = nx1 - (a * ox1 - b * oy1)
    f = ny1 - (b * ox1 + a * oy1)
    return a, b, -b, a, e, f


def transform_rect(matrix: Sequence[float], rect: Rect) -> Rect:
    """Bounding box of a rectangle after the transform."""
    corners = [(rect.x, rect.y), (rect.x2, rect.y), (rect.x, rect.y2), (rect.x2, rect.y2)]
    box = rect_from_points(apply_affine(matrix, px, py) for px, py in corners)
    assert box is not None  # noqa: S101 - four corners always give a box
    return box


def merge_rects(rects: Sequence[Rect], gap: float = 0.0) -> list[list[int]]:
    """Group rectangles that overlap once each is grown by ``gap`` / 2.

    Returns groups of input indexes, each group sorted, groups ordered by
    their first index. Union-find over a sweep on x keeps it near linear for
    the few thousand boxes a drawing produces.
    """
    n = len(rects)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    half = gap / 2.0
    grown = [r.expanded(half) for r in rects]
    order = sorted(range(n), key=lambda i: grown[i].x)
    active: list[int] = []
    for i in order:
        gi = grown[i]
        active = [j for j in active if grown[j].x2 >= gi.x]
        for j in active:
            if gi.intersects(grown[j]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[max(ri, rj)] = min(ri, rj)
        active.append(i)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])


def union_of(rects: Iterable[Rect]) -> Rect | None:
    """Union box of rectangles, ``None`` for none."""
    out: Rect | None = None
    for r in rects:
        out = r if out is None else out.union(r)
    return out


def _as_xy(value: Any) -> tuple[float, float] | None:
    if isinstance(value, dict):
        x, y = value.get("x"), value.get("y")
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        x, y = value[0], value[1]
    else:
        return None
    try:
        fx, fy = float(x), float(y)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(fx) and math.isfinite(fy)):
        return None
    return fx, fy


def points_of(geometry: Any) -> list[tuple[float, float]]:
    """Every point a stored shape carries, whatever shape it is stored in.

    Takeoff measurements store ``[{x, y}, ...]``; markups and DWG annotations
    store a dict with ``points`` (dicts or pairs), ``start``/``end``,
    ``center``/``radius`` or ``x``/``y``/``width``/``height``.
    """
    if isinstance(geometry, list):
        return [p for p in (_as_xy(v) for v in geometry) if p is not None]
    if not isinstance(geometry, dict):
        return []
    out: list[tuple[float, float]] = []
    for key in ("points", "vertices", "control_points"):
        seq = geometry.get(key)
        if isinstance(seq, list):
            out.extend(p for p in (_as_xy(v) for v in seq) if p is not None)
    for key in ("start", "end", "insert", "position"):
        p = _as_xy(geometry.get(key))
        if p is not None:
            out.append(p)
    center = _as_xy(geometry.get("center"))
    if center is not None:
        try:
            radius = abs(float(geometry.get("radius") or 0.0))
        except (TypeError, ValueError):
            radius = 0.0
        cx, cy = center
        out.extend([(cx - radius, cy - radius), (cx + radius, cy + radius)])
    if not out and "x" in geometry and "y" in geometry:
        p = _as_xy(geometry)
        if p is not None:
            out.append(p)
            try:
                w = float(geometry.get("width") or 0.0)
                h = float(geometry.get("height") or 0.0)
            except (TypeError, ValueError):
                w = h = 0.0
            if w or h:
                out.append((p[0] + w, p[1] + h))
    return out


def shape_in_region(
    points: Sequence[tuple[float, float]],
    region: Rect,
    *,
    matrix: Sequence[float] | None = None,
    margin: float = 0.0,
) -> bool:
    """Whether a shape touches a changed region.

    A measurement half inside a changed area is as stale as one wholly
    inside it, so the test is overlap of the shape's box with the region
    (grown by ``margin``), after mapping the shape through ``matrix`` when it
    was drawn on the older revision.
    """
    if not points:
        return False
    mapped = [apply_affine(matrix, px, py) for px, py in points] if matrix is not None else list(points)
    box = rect_from_points(mapped)
    if box is None:
        return False
    return box.intersects(region.expanded(margin))
