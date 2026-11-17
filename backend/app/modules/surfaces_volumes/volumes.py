# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cut and fill between two surfaces (no database, no I/O).

``dh = base - compare``: where the existing ground (base) stands above the
design (compare) earth is removed, so ``dh > 0`` is cut and ``dh < 0`` is fill.

Three methods, all returning bank volumes in m3:

* grid: square cells sampled at their centres, ``V = sum(cell_area * dh)``;
* tin: one triangulation of both surfaces' points, ``dh`` linear in each
  triangle and split exactly at ``dh = 0``;
* end area: sections across the E axis, ``V = L * (A1 + A2) / 2`` per pair.

Coverage is the share of the calculation area where both surfaces have data.
The calculation area is the boundary polygon when one is given, otherwise the
base surface.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from app.modules.surfaces_volumes.tin import Tin

GRID = "grid"
TIN = "tin"
END_AREA = "end_area"
METHODS = (GRID, TIN, END_AREA)

#: Above this a grid belongs in a background job, not a request (3 GB RAM rule).
MAX_GRID_CELLS = 2_000_000
#: The plan view gets at most this many heat cells; finer grids are pooled.
MAX_HEAT_CELLS = 20_000
_NICE = (0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 2.5, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0)

Ring = list[tuple[float, float]]


@dataclass
class VolumeResult:
    """One cut/fill computation. Volumes in m3, areas in m2."""

    method: str
    cell_size: float
    cut: float
    fill: float
    calc_area: float
    covered_area: float
    heat: dict | None = None
    sections: list[dict] = field(default_factory=list)

    @property
    def net(self) -> float:
        """Cut minus fill: positive means surplus (net cut)."""
        return self.cut - self.fill

    @property
    def coverage_pct(self) -> float:
        return 100.0 * self.covered_area / self.calc_area if self.calc_area > 0 else 0.0


# ── Plane geometry ─────────────────────────────────────────────────────────


def polygon_area(ring: Ring) -> float:
    """Shoelace area of a ring (closed or not), m2."""
    if len(ring) < 3:
        return 0.0
    x = np.array([p[0] for p in ring], dtype=np.float64)
    y = np.array([p[1] for p in ring], dtype=np.float64)
    x, y = x - x.mean(), y - y.mean()
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def in_polygon(x: np.ndarray, y: np.ndarray, ring: Ring) -> np.ndarray:
    """Even-odd point-in-polygon test, vectorised over the points."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    inside = np.zeros(x.shape, dtype=bool)
    pts = list(ring)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    m = len(pts)
    for i in range(m):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % m]
        if y1 == y2:
            continue
        crosses = (y1 > y) != (y2 > y)
        xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        inside ^= crosses & (x < xi)
    return inside


def nice_cell(value: float) -> float:
    """The round cell size (1, 2, 2.5, 5, 10 ...) nearest to ``value`` on a log scale."""
    if value <= 0 or not math.isfinite(value):
        return 1.0
    return min(_NICE, key=lambda c: abs(math.log(c / value)))


def auto_cell_size(base: Tin, compare: Tin) -> float:
    """A cell about as large as the point spacing of the denser surface."""
    spacings = [s for s in (base.spacing(), compare.spacing()) if s > 0]
    return nice_cell(min(spacings)) if spacings else 1.0


def _extent(base: Tin, boundary: Ring | None) -> tuple[float, float, float, float]:
    if boundary:
        xs = [p[0] for p in boundary]
        ys = [p[1] for p in boundary]
        return min(xs), min(ys), max(xs), max(ys)
    return base.bbox()


def _grid_shape(extent: tuple[float, float, float, float], cell: float) -> tuple[int, int]:
    w, h = extent[2] - extent[0], extent[3] - extent[1]
    nx = max(int(math.ceil(w / cell - 1e-9)), 1)
    ny = max(int(math.ceil(h / cell - 1e-9)), 1)
    if nx * ny > MAX_GRID_CELLS:
        raise ValueError(f"{nx * ny} grid cells is more than {MAX_GRID_CELLS}: choose a larger cell size")
    return nx, ny


# ── Grid ───────────────────────────────────────────────────────────────────


def grid_volume(base: Tin, compare: Tin, cell: float, boundary: Ring | None = None) -> VolumeResult:
    """Cut and fill on square cells of ``cell`` metres, sampled at the cell centres."""
    if cell <= 0:
        raise ValueError("cell size must be positive")
    ext = _extent(base, boundary)
    nx, ny = _grid_shape(ext, cell)
    x0, y0 = ext[0], ext[1]
    zb = base.sample_grid(x0, y0, cell, nx, ny)
    zc = compare.sample_grid(x0, y0, cell, nx, ny)
    if boundary:
        gx, gy = np.meshgrid(x0 + (np.arange(nx) + 0.5) * cell, y0 + (np.arange(ny) + 0.5) * cell)
        in_area = in_polygon(gx, gy, boundary)
    else:
        in_area = ~np.isnan(zb)
    dh = zb - zc
    covered = in_area & ~np.isnan(dh)
    a = cell * cell
    d = np.where(covered, dh, 0.0)
    cut = float(a * d[d > 0].sum())
    fill = float(-a * d[d < 0].sum())
    heat = _heat(dh, covered, x0, y0, cell)
    return VolumeResult(GRID, cell, cut, fill, float(in_area.sum() * a), float(covered.sum() * a), heat)


def _heat(dh: np.ndarray, covered: np.ndarray, x0: float, y0: float, cell: float) -> dict:
    """Per-cell ``dh`` for the plan view, pooled to at most ``MAX_HEAT_CELLS`` cells."""
    ny, nx = dh.shape
    k = 1
    while (math.ceil(nx / k) * math.ceil(ny / k)) > MAX_HEAT_CELLS:
        k += 1
    if k > 1:
        pny, pnx = math.ceil(ny / k), math.ceil(nx / k)
        pad = np.full((pny * k, pnx * k), np.nan)
        pad[:ny, :nx] = np.where(covered, dh, np.nan)
        blocks = pad.reshape(pny, k, pnx, k)
        with np.errstate(all="ignore"):
            pooled = np.nanmean(blocks, axis=(1, 3))
        dh, ny, nx = pooled, pny, pnx
    else:
        dh = np.where(covered, dh, np.nan)
    values = [None if not math.isfinite(v) else round(float(v), 3) for v in dh.ravel()]
    return {"origin_e": x0, "origin_n": y0, "cell": cell * k, "nx": nx, "ny": ny, "dh": values}


# ── TIN ────────────────────────────────────────────────────────────────────


def _split_triangle(area: float, d: np.ndarray) -> tuple[float, float]:
    """Exact cut and fill of a triangle where ``dh`` is linear between vertex values ``d``."""
    net = area * float(d.sum()) / 3.0
    pos = d > 0
    if pos.all():
        return net, 0.0
    if not pos.any():
        return 0.0, -net
    if pos.sum() == 1:
        i = int(np.argmax(pos))
        d1 = float(d[i])
        o = [float(v) for j, v in enumerate(d) if j != i]
        cut = area * d1**3 / (3.0 * (d1 - o[0]) * (d1 - o[1]))
        return cut, cut - net
    i = int(np.argmin(pos))
    d3 = float(d[i])
    o = [float(v) for j, v in enumerate(d) if j != i]
    neg = area * d3**3 / (3.0 * (d3 - o[0]) * (d3 - o[1]))
    return net - neg, -neg


def tin_volume(base: Tin, compare: Tin, boundary: Ring | None = None) -> VolumeResult:
    """Cut and fill on one triangulation of both surfaces' points (and the boundary corners)."""
    e = [base.e, compare.e]
    n = [base.n, compare.n]
    if boundary:
        e.append(np.array([p[0] for p in boundary]))
        n.append(np.array([p[1] for p in boundary]))
    ea, na = np.concatenate(e), np.concatenate(n)
    merged = Tin.from_points(ea, na, np.zeros(len(ea)))
    zb = base.sample(merged.e, merged.n)
    zc = compare.sample(merged.e, merged.n)
    t = merged.tri
    areas = merged.triangle_areas()
    cx = merged.e[t].mean(axis=1) if len(t) else np.zeros(0)
    cy = merged.n[t].mean(axis=1) if len(t) else np.zeros(0)
    if boundary:
        in_area = in_polygon(cx, cy, boundary)
        calc_area = polygon_area(boundary)
    else:
        in_area = ~np.isnan(base.sample(cx, cy))
        calc_area = base.area()
    both = in_area & ~np.isnan(compare.sample(cx, cy)) & ~np.isnan(base.sample(cx, cy))
    dh = zb - zc
    cut = fill = covered = 0.0
    for k in np.nonzero(both)[0]:
        d = dh[t[k]]
        if np.isnan(d).any():
            continue
        c, f = _split_triangle(float(areas[k]), d)
        cut += c
        fill += f
        covered += float(areas[k])
    return VolumeResult(TIN, 0.0, cut, fill, calc_area, min(covered, calc_area) if calc_area else covered)


# ── End area ───────────────────────────────────────────────────────────────


def end_area_volume(base: Tin, compare: Tin, spacing: float, boundary: Ring | None = None) -> VolumeResult:
    """Average end area over sections across the E axis, ``spacing`` metres apart."""
    if spacing <= 0:
        raise ValueError("section spacing must be positive")
    ext = _extent(base, boundary)
    width = ext[2] - ext[0]
    k = max(int(math.ceil(width / spacing - 1e-9)), 1)
    stations = ext[0] + np.arange(k + 1) * (width / k)
    step = spacing / 2.0
    ny = max(int(math.ceil((ext[3] - ext[1]) / step - 1e-9)), 1)
    if (k + 1) * ny > MAX_GRID_CELLS:
        raise ValueError("too many section samples: choose a larger spacing")
    ys = ext[1] + (np.arange(ny) + 0.5) * ((ext[3] - ext[1]) / ny)
    dy = (ext[3] - ext[1]) / ny
    sections: list[dict] = []
    for x in stations:
        xs = np.full(ny, x)
        zb, zc = base.sample(xs, ys), compare.sample(xs, ys)
        inside = in_polygon(xs, ys, boundary) if boundary else ~np.isnan(zb)
        d = np.where(inside & ~np.isnan(zb - zc), zb - zc, 0.0)
        sections.append(
            {
                "station": round(float(x - ext[0]), 3),
                "cut_area": float(dy * d[d > 0].sum()),
                "fill_area": float(-dy * d[d < 0].sum()),
                "width": float(dy * inside.sum()),
                "covered": float(dy * (inside & ~np.isnan(zb - zc)).sum()),
            }
        )
    seg = width / k
    cut = sum(seg * (a["cut_area"] + b["cut_area"]) / 2.0 for a, b in zip(sections, sections[1:], strict=False))
    fill = sum(seg * (a["fill_area"] + b["fill_area"]) / 2.0 for a, b in zip(sections, sections[1:], strict=False))
    calc = sum(seg * (a["width"] + b["width"]) / 2.0 for a, b in zip(sections, sections[1:], strict=False))
    cov = sum(seg * (a["covered"] + b["covered"]) / 2.0 for a, b in zip(sections, sections[1:], strict=False))
    return VolumeResult(END_AREA, seg, cut, fill, calc, cov, sections=sections)


def compute(
    base: Tin, compare: Tin, method: str = GRID, cell: float | None = None, boundary: Ring | None = None
) -> VolumeResult:
    """Run one method; ``cell`` (or section spacing) defaults to :func:`auto_cell_size`."""
    size = cell if cell and cell > 0 else auto_cell_size(base, compare)
    if method == GRID:
        return grid_volume(base, compare, size, boundary)
    if method == TIN:
        return tin_volume(base, compare, boundary)
    if method == END_AREA:
        return end_area_volume(base, compare, size, boundary)
    raise ValueError(f"unknown method {method!r}")


def is_coarse(tier: str | None) -> bool:
    """The pointcloud ``coarse`` tier (USIBD LOA10, phone LiDAR): never a BOQ quantity alone (VOL-003)."""
    return bool(tier) and str(tier).strip().lower() in ("coarse", "loa10")


def confidence(coverage_pct: float, tier: str | None, crs_declared: bool) -> float:
    """How far to trust a result before a surveyor confirms it, 0..1.

    Coverage drives it; a coarse scan tier and a surface without a declared
    coordinate system each pull it down. It is advice for the reviewer, never a gate.
    """
    score = max(min(coverage_pct / 100.0, 1.0), 0.0)
    if is_coarse(tier):
        score *= 0.6
    if not crs_declared:
        score *= 0.5
    return round(score, 2)


__all__ = [
    "END_AREA",
    "GRID",
    "MAX_GRID_CELLS",
    "METHODS",
    "TIN",
    "VolumeResult",
    "auto_cell_size",
    "compute",
    "confidence",
    "end_area_volume",
    "grid_volume",
    "in_polygon",
    "nice_cell",
    "polygon_area",
    "tin_volume",
]
