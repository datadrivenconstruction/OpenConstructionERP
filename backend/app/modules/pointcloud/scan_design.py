# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Scan against design: per-point height deviation from a design surface (no database, no I/O).

``dz = scan z - design z`` at the point's plan position: positive is high (material
still to remove, or built too high), negative is low. The design TIN is first
sampled onto a node grid and each point is read off it bilinearly, which is exact
on planar faces (pads, slopes) and keeps the per-point cost constant however many
triangles the design has. Points whose four grid nodes are not all on the
design fall back to the TIN itself, so the edges are exact too.

Everything is accumulated chunk by chunk: running sums for mean and RMS, a
0.01 mm histogram of ``|dz|`` for P95 (nearest rank), band counts, and a coarse
plan grid of mean ``dz`` for the heatmap. Memory is fixed by the grids, not by
the number of points.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.modules.surfaces_volumes.tin import Tin

#: Node grid of the sampled design; 1.5 M float64 nodes is 12 MB.
MAX_DESIGN_NODES = 1_500_000
#: Plan heatmap cells kept in the report.
MAX_HEAT_CELLS = 20_000
HIST_STEP_MM = 0.01
HIST_MAX_MM = 2000.0
_NICE = (0.05, 0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 2.5, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0)

#: Band colours of the heatmap (also the viewer legend): low, within, high, no design.
BAND_RGB: dict[str, tuple[int, int, int]] = {
    "far_low": (37, 99, 235),
    "low": (56, 189, 248),
    "within": (16, 185, 129),
    "high": (245, 158, 11),
    "far_high": (239, 68, 68),
    "none": (148, 163, 184),
}


def nice_up(value: float) -> float:
    """The smallest round size not below ``value``."""
    for c in _NICE:
        if c >= value - 1e-12:
            return c
    return _NICE[-1] * math.ceil(value / _NICE[-1])


@dataclass
class DesignGrid:
    """Design heights at grid nodes ``(x0 + i * cell, y0 + j * cell)``; NaN off the design."""

    tin: Tin
    x0: float
    y0: float
    cell: float
    nx: int
    ny: int
    z: np.ndarray

    def sample(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Design height under each point; NaN off the design."""
        fx = (x - self.x0) / self.cell
        fy = (y - self.y0) / self.cell
        i = np.floor(fx).astype(np.int64)
        j = np.floor(fy).astype(np.int64)
        inside = (i >= 0) & (j >= 0) & (i < self.nx - 1) & (j < self.ny - 1)
        out = np.full(len(x), np.nan)
        if inside.any():
            ii, jj = i[inside], j[inside]
            tx, ty = fx[inside] - ii, fy[inside] - jj
            z00 = self.z[jj, ii]
            z10 = self.z[jj, ii + 1]
            z01 = self.z[jj + 1, ii]
            z11 = self.z[jj + 1, ii + 1]
            out[inside] = (z00 * (1 - tx) + z10 * tx) * (1 - ty) + (z01 * (1 - tx) + z11 * tx) * ty
        miss = np.isnan(out)
        if miss.any():
            e0, n0, e1, n1 = self.tin.bbox()
            near = miss & (x >= e0 - 1e-6) & (x <= e1 + 1e-6) & (y >= n0 - 1e-6) & (y <= n1 + 1e-6)
            if near.any():
                out[near] = self.tin.sample(x[near], y[near])
        return out


def heat_cell_floor(design_area_m2: float, declared_points: int) -> float:
    """Twice the mean point spacing over the design: the finest heat cell that is not mostly empty."""
    if declared_points <= 0 or design_area_m2 <= 0:
        return 0.0
    return 2.0 * math.sqrt(design_area_m2 / declared_points)


def design_grid(tin: Tin, cell: float | None = None) -> DesignGrid:
    """Sample ``tin`` at grid nodes; the cell is the finest round size within ``MAX_DESIGN_NODES``."""
    e0, n0, e1, n1 = tin.bbox()
    w, h = max(e1 - e0, 1e-6), max(n1 - n0, 1e-6)
    if cell is None or cell <= 0:
        cell = nice_up(max(math.sqrt(w * h / MAX_DESIGN_NODES), _NICE[0]))
    nx = int(math.ceil(w / cell - 1e-9)) + 1
    ny = int(math.ceil(h / cell - 1e-9)) + 1
    while nx * ny > MAX_DESIGN_NODES:
        cell = nice_up(cell * 1.5)
        nx = int(math.ceil(w / cell - 1e-9)) + 1
        ny = int(math.ceil(h / cell - 1e-9)) + 1
    z = tin.sample_grid(e0 - cell / 2, n0 - cell / 2, cell, nx, ny)
    return DesignGrid(tin, e0, n0, cell, nx, ny, z)


def band_of(dz_mm: np.ndarray, tol_mm: float) -> np.ndarray:
    """Band index per point: 0 far low, 1 low, 2 within, 3 high, 4 far high, 5 no design."""
    out = np.full(len(dz_mm), 5, dtype=np.int8)
    ok = ~np.isnan(dz_mm)
    d = dz_mm[ok]
    b = np.full(len(d), 2, dtype=np.int8)
    b[d < -tol_mm] = 1
    b[d < -2 * tol_mm] = 0
    b[d > tol_mm] = 3
    b[d > 2 * tol_mm] = 4
    out[ok] = b
    return out


_BAND_KEYS = ("far_low", "low", "within", "high", "far_high", "none")
_BAND_TABLE = np.array([BAND_RGB[k] for k in _BAND_KEYS], dtype=np.uint8)


def heat_rgb(dz_mm: np.ndarray, tol_mm: float) -> np.ndarray:
    """``(N, 3)`` uint8 band colours for the viewer."""
    return _BAND_TABLE[band_of(dz_mm, tol_mm)]


@dataclass
class DeviationStats:
    """The numbers of one comparison; lengths in mm, shares in percent."""

    points_read: int
    points_compared: int
    points_outside: int
    tolerance_mm: float
    mean_mm: float | None
    rms_mm: float | None
    std_mm: float | None
    p95_mm: float | None
    min_mm: float | None
    max_mm: float | None
    within_pct: float | None
    high_pct: float | None
    low_pct: float | None
    out_count: int
    coverage_pct: float
    bands: dict[str, int] = field(default_factory=dict)
    heat: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready copy."""
        return dict(self.__dict__)


class DeviationAccumulator:
    """Fold chunks of scan points into deviation statistics against one design."""

    def __init__(self, design: DesignGrid, tol_mm: float, min_cell: float = 0.0) -> None:
        if tol_mm <= 0:
            raise ValueError("The tolerance must be positive")
        self.design = design
        self.tol = float(tol_mm)
        self.read = 0
        self.n = 0
        self.total = 0.0
        self.total_sq = 0.0
        self.lo = math.inf
        self.hi = -math.inf
        self.bands = np.zeros(6, dtype=np.int64)
        self.hist = np.zeros(int(HIST_MAX_MM / HIST_STEP_MM) + 1, dtype=np.int64)
        self.max_abs = 0.0
        e0, n0, e1, n1 = design.tin.bbox()
        w, h = max(e1 - e0, 1e-6), max(n1 - n0, 1e-6)
        # A heat cell finer than the point spacing would read empty cells as missing coverage.
        hc = nice_up(max(math.sqrt(w * h / MAX_HEAT_CELLS), min_cell))
        while math.ceil(w / hc) * math.ceil(h / hc) > MAX_HEAT_CELLS:
            hc = nice_up(hc * 1.01)
        self.hx0, self.hy0, self.hc = e0, n0, hc
        self.hnx, self.hny = max(math.ceil(w / hc - 1e-9), 1), max(math.ceil(h / hc - 1e-9), 1)
        self.heat_sum = np.zeros(self.hnx * self.hny)
        self.heat_count = np.zeros(self.hnx * self.hny, dtype=np.int64)

    def add(self, x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
        """Fold one chunk in; returns ``dz`` in mm per point (NaN off the design)."""
        self.read += len(x)
        dz = (z - self.design.sample(x, y)) * 1000.0
        ok = ~np.isnan(dz)
        d = dz[ok]
        self.bands += np.bincount(band_of(dz, self.tol), minlength=6)
        if len(d):
            self.n += len(d)
            self.total += float(d.sum())
            self.total_sq += float((d * d).sum())
            self.lo = min(self.lo, float(d.min()))
            self.hi = max(self.hi, float(d.max()))
            a = np.abs(d)
            self.max_abs = max(self.max_abs, float(a.max()))
            idx = np.minimum((a / HIST_STEP_MM + 1e-6).astype(np.int64), len(self.hist) - 1)
            self.hist += np.bincount(idx, minlength=len(self.hist))
            ix = np.clip(((x[ok] - self.hx0) / self.hc).astype(np.int64), 0, self.hnx - 1)
            iy = np.clip(((y[ok] - self.hy0) / self.hc).astype(np.int64), 0, self.hny - 1)
            cell = iy * self.hnx + ix
            self.heat_sum += np.bincount(cell, weights=d, minlength=len(self.heat_sum))
            self.heat_count += np.bincount(cell, minlength=len(self.heat_count))
        return dz

    def _p95(self) -> float | None:
        if self.n == 0:
            return None
        rank = math.ceil(0.95 * self.n)
        k = int(np.searchsorted(np.cumsum(self.hist), rank))
        if k >= len(self.hist) - 1:
            return round(self.max_abs, 1)
        return round(k * HIST_STEP_MM, 1)

    def _heat(self) -> tuple[dict[str, Any], float]:
        gx = self.hx0 + (np.arange(self.hnx) + 0.5) * self.hc
        gy = self.hy0 + (np.arange(self.hny) + 0.5) * self.hc
        mx, my = np.meshgrid(gx, gy)
        on_design = ~np.isnan(self.design.sample(mx.ravel(), my.ravel()))
        hit = self.heat_count > 0
        with np.errstate(all="ignore"):
            mean = np.where(hit, self.heat_sum / np.maximum(self.heat_count, 1), np.nan)
        values = [None if not math.isfinite(v) else round(float(v), 1) for v in mean]
        covered = int((on_design & hit).sum())
        coverage = 100.0 * covered / int(on_design.sum()) if on_design.any() else 0.0
        heat = {
            "origin_e": self.hx0,
            "origin_n": self.hy0,
            "cell": self.hc,
            "nx": self.hnx,
            "ny": self.hny,
            "dz_mm": values,
        }
        return heat, coverage

    def result(self) -> DeviationStats:
        """Statistics of everything folded in so far."""
        heat, coverage = self._heat()
        names = dict(zip(_BAND_KEYS, (int(v) for v in self.bands), strict=True))
        n = self.n
        if n == 0:
            return DeviationStats(
                self.read, 0, self.read, self.tol, None, None, None, None, None, None, None, None, None, 0,
                round(coverage, 2), names, heat,
            )  # fmt: skip
        mean = self.total / n
        rms = math.sqrt(self.total_sq / n)
        std = math.sqrt(max(self.total_sq / n - mean * mean, 0.0))
        within = names["within"]
        high = names["high"] + names["far_high"]
        low = names["low"] + names["far_low"]
        return DeviationStats(
            points_read=self.read,
            points_compared=n,
            points_outside=names["none"],
            tolerance_mm=self.tol,
            mean_mm=round(mean, 2),
            rms_mm=round(rms, 2),
            std_mm=round(std, 2),
            p95_mm=self._p95(),
            min_mm=round(self.lo, 1),
            max_mm=round(self.hi, 1),
            within_pct=round(100.0 * within / n, 2),
            high_pct=round(100.0 * high / n, 2),
            low_pct=round(100.0 * low / n, 2),
            out_count=high + low,
            coverage_pct=round(coverage, 2),
            bands=names,
            heat=heat,
        )


class SampleCollector:
    """Every ``stride``-th point with its deviation, for the viewer heatmap."""

    def __init__(self, declared_points: int, max_points: int) -> None:
        self.stride = max(1, math.ceil(max(declared_points, 1) / max(max_points, 1)))
        self.max_points = max_points
        self.seen = 0
        self.parts: list[np.ndarray] = []
        self.kept = 0

    def add(self, x: np.ndarray, y: np.ndarray, z: np.ndarray, dz_mm: np.ndarray) -> None:
        """Keep the points whose running index falls on the stride."""
        n = len(x)
        first = (-self.seen) % self.stride
        idx = np.arange(first, n, self.stride)
        self.seen += n
        room = self.max_points - self.kept
        if room <= 0 or not len(idx):
            return
        idx = idx[:room]
        self.parts.append(np.column_stack([x[idx], y[idx], z[idx], dz_mm[idx]]))
        self.kept += len(idx)

    def arrays(self) -> tuple[np.ndarray, np.ndarray]:
        """``(xyz float64 (N, 3), dz_mm (N,))``."""
        if not self.parts:
            return np.zeros((0, 3)), np.zeros(0)
        block = np.concatenate(self.parts)
        return block[:, :3], block[:, 3]


__all__ = [
    "BAND_RGB",
    "MAX_DESIGN_NODES",
    "DesignGrid",
    "DeviationAccumulator",
    "DeviationStats",
    "SampleCollector",
    "band_of",
    "design_grid",
    "heat_cell_floor",
    "heat_rgb",
    "nice_up",
]
