# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Triangulated ground surfaces (TIN) in plain numpy.

The Delaunay triangulation comes from OpenCV's ``Subdiv2D``: opencv-python-headless
is already a base dependency (raster recognition), it is C++ and fast, and it
spares the platform scipy. ``Subdiv2D`` works in float32, so coordinates are
shifted to a local origin first; UTM eastings in float32 would lose half a metre.

Heights are interpolated linearly inside each triangle; outside the triangles a
surface has no data (NaN), which is what coverage counts.

Breaklines (toe, crest, kerb) are kept as triangle edges: their vertices are
inserted, then every segment the Delaunay triangulation crossed is recovered by
edge flips (Sloan 1993), so no triangle bridges a slope change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Points closer than this (metres) in plan are one point; the first one wins.
SAME_XY_M = 0.0005
#: Barycentric slack so a sample exactly on a triangle edge is inside.
_EDGE_EPS = 1e-9


def _triangulate(local_xy: np.ndarray) -> np.ndarray:
    """Delaunay triangles of ``local_xy`` (n, 2) as vertex indices (m, 3)."""
    import cv2  # noqa: PLC0415 - heavy import, only when a surface is built

    n = len(local_xy)
    if n < 3:
        return np.zeros((0, 3), dtype=np.int64)
    xy32 = local_xy.astype(np.float32)
    lo = xy32.min(axis=0) - 1.0
    hi = xy32.max(axis=0) + 1.0
    subdiv = cv2.Subdiv2D((float(lo[0]), float(lo[1]), float(hi[0] - lo[0]) + 1.0, float(hi[1] - lo[1]) + 1.0))
    index: dict[tuple[float, float], int] = {}
    for i, (x, y) in enumerate(xy32):
        key = (float(x), float(y))
        if key in index:
            continue
        index[key] = i
        subdiv.insert(key)
    tris: list[tuple[int, int, int]] = []
    for t in subdiv.getTriangleList():
        a = index.get((float(t[0]), float(t[1])))
        b = index.get((float(t[2]), float(t[3])))
        c = index.get((float(t[4]), float(t[5])))
        if a is None or b is None or c is None:
            continue  # a triangle on OpenCV's virtual outer vertices
        tris.append((a, b, c))
    out = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    if len(out) == 0:
        return out
    p = local_xy
    area2 = (p[out[:, 1], 0] - p[out[:, 0], 0]) * (p[out[:, 2], 1] - p[out[:, 0], 1]) - (
        p[out[:, 2], 0] - p[out[:, 0], 0]
    ) * (p[out[:, 1], 1] - p[out[:, 0], 1])
    keep = np.abs(area2) > 1e-9
    out = out[keep]
    # Counter-clockwise, so signed areas are positive everywhere downstream.
    flip = area2[keep] < 0
    out[flip] = out[flip][:, [0, 2, 1]]
    return out


def dedupe_xy(e: np.ndarray, n: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Drop later points that sit on an earlier point in plan (first one wins)."""
    keys = np.round(np.column_stack([e, n]) / SAME_XY_M).astype(np.int64)
    _, first = np.unique(keys, axis=0, return_index=True)
    first.sort()
    return e[first], n[first], z[first]


Polyline = list[tuple[float, float, float]]


def _orient(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _crosses(p: np.ndarray, a: int, b: int, u: int, v: int) -> bool:
    """True when segment u-v crosses segment a-b in both interiors."""
    if len({a, b, u, v}) < 4:
        return False
    ax, ay = p[a]
    bx, by = p[b]
    ux, uy = p[u]
    vx, vy = p[v]
    d1 = _orient(ax, ay, bx, by, ux, uy)
    d2 = _orient(ax, ay, bx, by, vx, vy)
    d3 = _orient(ux, uy, vx, vy, ax, ay)
    d4 = _orient(ux, uy, vx, vy, bx, by)
    return d1 * d2 < 0 and d3 * d4 < 0


def _split_on_vertices(p: np.ndarray, a: int, b: int, eps: float = 1e-6) -> list[tuple[int, int]]:
    """Segment a-b as sub-segments between the vertices lying on it (a constraint cannot jump a vertex)."""
    d = p[b] - p[a]
    length2 = float(d @ d)
    if length2 == 0:
        return []
    rel = p - p[a]
    t = (rel @ d) / length2
    off = np.abs(rel[:, 0] * d[1] - rel[:, 1] * d[0]) / np.sqrt(length2)
    on = np.nonzero((off < eps) & (t > 1e-9) & (t < 1 - 1e-9))[0]
    chain = [a, *[int(i) for i in on[np.argsort(t[on])]], b]
    return list(zip(chain[:-1], chain[1:], strict=True))


def _key(i: int, j: int) -> tuple[int, int]:
    return (i, j) if i < j else (j, i)


def enforce_edges(local_xy: np.ndarray, tri: np.ndarray, segments: list[tuple[int, int]]) -> tuple[np.ndarray, int]:
    """Flip edges until every constraint segment is an edge of the triangulation.

    Returns the triangles (CCW) and how many segments could not be recovered
    (a segment that leaves the hull, or a chain of quads that never turns convex).
    """
    tris: list[list[int]] = [[int(x) for x in t] for t in tri]
    edges: dict[tuple[int, int], set[int]] = {}
    for k, (a, b, c) in enumerate(tris):
        for i, j in ((a, b), (b, c), (c, a)):
            edges.setdefault(_key(i, j), set()).add(k)

    def third(k: int, i: int, j: int) -> int:
        return next(x for x in tris[k] if x not in (i, j))

    # The original edges are tested in one vectorised pass per segment; edges made by flips are few.
    static = np.array(sorted(edges), dtype=np.int64).reshape(-1, 2)
    added: set[tuple[int, int]] = set()

    def crossing_edges(a: int, b: int) -> list[tuple[int, int]]:
        (ax, ay), (bx, by) = local_xy[a], local_xy[b]
        u, v = local_xy[static[:, 0]], local_xy[static[:, 1]]
        d1 = (bx - ax) * (u[:, 1] - ay) - (by - ay) * (u[:, 0] - ax)
        d2 = (bx - ax) * (v[:, 1] - ay) - (by - ay) * (v[:, 0] - ax)
        d3 = (v[:, 0] - u[:, 0]) * (ay - u[:, 1]) - (v[:, 1] - u[:, 1]) * (ax - u[:, 0])
        d4 = (v[:, 0] - u[:, 0]) * (by - u[:, 1]) - (v[:, 1] - u[:, 1]) * (bx - u[:, 0])
        hit = static[(d1 * d2 < 0) & (d3 * d4 < 0)]
        out = [(int(i), int(j)) for i, j in hit if (int(i), int(j)) in edges]
        out.extend(k for k in added if k in edges and _crosses(local_xy, a, b, k[0], k[1]))
        return out

    missed = 0
    for seg_a, seg_b in segments:
        for a, b in _split_on_vertices(local_xy, seg_a, seg_b):
            if _key(a, b) in edges:
                continue
            crossing = crossing_edges(a, b)
            budget = 50 * len(crossing) + 100
            while crossing and budget > 0:
                budget -= 1
                u, v = crossing.pop(0)
                owners = edges.get((u, v))
                if not owners or len(owners) != 2:
                    break  # an edge on the hull: the segment leaves the surface
                t1, t2 = owners
                p, q = third(t1, u, v), third(t2, u, v)
                if not _crosses(local_xy, p, q, u, v):
                    crossing.append((u, v))  # quad not convex yet; revisit after its neighbours flip
                    continue
                # Orient so that t1 = (u, v, p) and t2 = (v, u, q) run counter-clockwise.
                if _orient(*local_xy[u], *local_xy[v], *local_xy[p]) < 0:
                    p, q, t1, t2 = q, p, t2, t1
                tris[t1] = [u, q, p]
                tris[t2] = [q, v, p]
                del edges[(u, v)]
                edges[_key(v, p)].discard(t1)
                edges[_key(v, p)].add(t2)
                edges[_key(u, q)].discard(t2)
                edges[_key(u, q)].add(t1)
                edges[_key(p, q)] = {t1, t2}
                added.add(_key(p, q))
                if _crosses(local_xy, a, b, p, q):
                    crossing.append(_key(p, q))
            if _key(a, b) not in edges:
                missed += 1
    return np.asarray(tris, dtype=np.int64).reshape(-1, 3), missed


@dataclass
class Tin:
    """A triangulated surface: absolute E/N/Z vertices and CCW triangles."""

    e: np.ndarray
    n: np.ndarray
    z: np.ndarray
    tri: np.ndarray
    origin: tuple[float, float] = field(default=(0.0, 0.0))
    #: Breakline segments that could not be kept as edges (SRV-081).
    missed_segments: int = 0

    @classmethod
    def from_points(cls, e: list[float] | np.ndarray, n: list[float] | np.ndarray, z: list[float] | np.ndarray) -> Tin:
        """Delaunay TIN of scattered points (duplicates in plan dropped)."""
        ea, na, za = (np.asarray(v, dtype=np.float64) for v in (e, n, z))
        ok = np.isfinite(ea) & np.isfinite(na) & np.isfinite(za)
        ea, na, za = dedupe_xy(ea[ok], na[ok], za[ok])
        origin = (float(ea.min()), float(na.min())) if len(ea) else (0.0, 0.0)
        local = np.column_stack([ea - origin[0], na - origin[1]])
        return cls(ea, na, za, _triangulate(local), origin)

    @classmethod
    def from_points_with_breaklines(
        cls,
        e: list[float] | np.ndarray,
        n: list[float] | np.ndarray,
        z: list[float] | np.ndarray,
        breaklines: list[Polyline],
        boundary: list[tuple[float, float]] | None = None,
    ) -> Tin:
        """Delaunay TIN whose breakline segments are triangle edges; triangles outside ``boundary`` dropped.

        A breakline vertex wins over a scattered point at the same plan position,
        because its height is the one the surveyor strung on purpose.
        """
        lines = [[(float(x), float(y), float(h)) for x, y, h in line] for line in breaklines if len(line) >= 2]
        flat = [v for line in lines for v in line]
        ea, na, za = (np.asarray(v, dtype=np.float64) for v in (e, n, z))
        ok = np.isfinite(ea) & np.isfinite(na) & np.isfinite(za)
        ea = np.concatenate([np.array([v[0] for v in flat]), ea[ok]])
        na = np.concatenate([np.array([v[1] for v in flat]), na[ok]])
        za = np.concatenate([np.array([v[2] for v in flat]), za[ok]])
        ea, na, za = dedupe_xy(ea, na, za)
        origin = (float(ea.min()), float(na.min())) if len(ea) else (0.0, 0.0)
        local = np.column_stack([ea - origin[0], na - origin[1]])
        tri = _triangulate(local)
        grid = np.round(np.column_stack([ea, na]) / SAME_XY_M).astype(np.int64)
        index = {(int(a), int(b)): i for i, (a, b) in enumerate(grid)}
        segments: list[tuple[int, int]] = []
        for line in lines:
            ids = [index.get((round(x / SAME_XY_M), round(y / SAME_XY_M))) for x, y, _ in line]
            segments.extend(
                (i, j) for i, j in zip(ids[:-1], ids[1:], strict=True) if i is not None and j is not None and i != j
            )
        missed = 0
        if segments and len(tri):
            tri, missed = enforce_edges(local, tri, segments)
        if boundary and len(tri):
            from app.modules.surfaces_volumes.volumes import in_polygon  # noqa: PLC0415 - volumes imports tin

            keep = in_polygon(ea[tri].mean(axis=1), na[tri].mean(axis=1), boundary)
            tri = tri[keep]
        return cls(ea, na, za, tri, origin, missed)

    @classmethod
    def from_faces(
        cls,
        e: list[float] | np.ndarray,
        n: list[float] | np.ndarray,
        z: list[float] | np.ndarray,
        faces: list[tuple[int, int, int]] | np.ndarray,
    ) -> Tin:
        """A TIN whose triangles were given (LandXML ``Faces``)."""
        ea, na, za = (np.asarray(v, dtype=np.float64) for v in (e, n, z))
        tri = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
        origin = (float(ea.min()), float(na.min())) if len(ea) else (0.0, 0.0)
        if len(tri):
            x, y = ea - origin[0], na - origin[1]
            a2 = (x[tri[:, 1]] - x[tri[:, 0]]) * (y[tri[:, 2]] - y[tri[:, 0]]) - (x[tri[:, 2]] - x[tri[:, 0]]) * (
                y[tri[:, 1]] - y[tri[:, 0]]
            )
            tri = tri[np.abs(a2) > 1e-9]
            flip = a2[np.abs(a2) > 1e-9] < 0
            tri[flip] = tri[flip][:, [0, 2, 1]]
        return cls(ea, na, za, tri, origin)

    # ── Measures ──────────────────────────────────────────────────────────

    @property
    def point_count(self) -> int:
        return len(self.e)

    @property
    def triangle_count(self) -> int:
        return len(self.tri)

    def triangle_areas(self) -> np.ndarray:
        t = self.tri
        if len(t) == 0:
            return np.zeros(0)
        x, y = self.e, self.n
        return 0.5 * np.abs(
            (x[t[:, 1]] - x[t[:, 0]]) * (y[t[:, 2]] - y[t[:, 0]])
            - (x[t[:, 2]] - x[t[:, 0]]) * (y[t[:, 1]] - y[t[:, 0]])
        )

    def area(self) -> float:
        """Plan area covered by the triangles, m2."""
        return float(self.triangle_areas().sum())

    def bbox(self) -> tuple[float, float, float, float]:
        """``(min_e, min_n, max_e, max_n)`` of the vertices."""
        if not len(self.e):
            return (0.0, 0.0, 0.0, 0.0)
        return (float(self.e.min()), float(self.n.min()), float(self.e.max()), float(self.n.max()))

    def spacing(self) -> float:
        """Mean point spacing ``sqrt(area / points)``, m; 0 for an empty surface."""
        a = self.area()
        return float(np.sqrt(a / self.point_count)) if a > 0 and self.point_count else 0.0

    def outline(self) -> list[tuple[int, int]]:
        """Edges used by one triangle only: the surface's outer and hole boundaries."""
        if len(self.tri) == 0:
            return []
        edges = np.sort(np.concatenate([self.tri[:, [0, 1]], self.tri[:, [1, 2]], self.tri[:, [2, 0]]]), axis=1)
        uniq, counts = np.unique(edges, axis=0, return_counts=True)
        return [(int(a), int(b)) for a, b in uniq[counts == 1]]

    # ── Interpolation ─────────────────────────────────────────────────────

    def sample(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Heights at arbitrary plan positions; NaN outside the triangles."""
        x = np.asarray(x, dtype=np.float64).ravel()
        y = np.asarray(y, dtype=np.float64).ravel()
        out = np.full(len(x), np.nan)
        if not len(self.tri) or not len(x):
            return out
        order = np.argsort(x, kind="stable")
        xs = x[order]
        for a, b, c in self.tri:
            xa, xb, xc = self.e[a], self.e[b], self.e[c]
            lo, hi = np.searchsorted(xs, [min(xa, xb, xc) - 1e-9, max(xa, xb, xc) + 1e-9], side="left")
            if hi <= lo:
                continue
            idx = order[lo:hi]
            idx = idx[np.isnan(out[idx])]
            if not len(idx):
                continue
            w = self._bary(a, b, c, x[idx], y[idx])
            if w is None:
                continue
            inside, za = w
            out[idx[inside]] = za[inside]
        return out

    def sample_grid(self, x0: float, y0: float, cell: float, nx: int, ny: int) -> np.ndarray:
        """Heights at the centres of an ``ny`` x ``nx`` grid of square cells; NaN outside."""
        out = np.full((ny, nx), np.nan)
        if not len(self.tri) or nx <= 0 or ny <= 0:
            return out
        for a, b, c in self.tri:
            xs = (self.e[a], self.e[b], self.e[c])
            ys = (self.n[a], self.n[b], self.n[c])
            i0 = max(int(np.ceil((min(xs) - x0) / cell - 0.5 - 1e-9)), 0)
            i1 = min(int(np.floor((max(xs) - x0) / cell - 0.5 + 1e-9)), nx - 1)
            j0 = max(int(np.ceil((min(ys) - y0) / cell - 0.5 - 1e-9)), 0)
            j1 = min(int(np.floor((max(ys) - y0) / cell - 0.5 + 1e-9)), ny - 1)
            if i1 < i0 or j1 < j0:
                continue
            gx, gy = np.meshgrid(x0 + (np.arange(i0, i1 + 1) + 0.5) * cell, y0 + (np.arange(j0, j1 + 1) + 0.5) * cell)
            w = self._bary(a, b, c, gx.ravel(), gy.ravel())
            if w is None:
                continue
            inside, za = w
            block = out[j0 : j1 + 1, i0 : i1 + 1].reshape(-1)
            take = inside & np.isnan(block)
            block[take] = za[take]
            out[j0 : j1 + 1, i0 : i1 + 1] = block.reshape(j1 - j0 + 1, i1 - i0 + 1)
        return out

    def _bary(self, a: int, b: int, c: int, px: np.ndarray, py: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
        x1, y1, x2, y2, x3, y3 = self.e[a], self.n[a], self.e[b], self.n[b], self.e[c], self.n[c]
        det = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
        if abs(det) < 1e-12:
            return None
        l1 = ((y2 - y3) * (px - x3) + (x3 - x2) * (py - y3)) / det
        l2 = ((y3 - y1) * (px - x3) + (x1 - x3) * (py - y3)) / det
        l3 = 1.0 - l1 - l2
        inside = (l1 >= -_EDGE_EPS) & (l2 >= -_EDGE_EPS) & (l3 >= -_EDGE_EPS)
        return inside, l1 * self.z[a] + l2 * self.z[b] + l3 * self.z[c]


__all__ = ["SAME_XY_M", "Polyline", "Tin", "dedupe_xy", "enforce_edges"]
