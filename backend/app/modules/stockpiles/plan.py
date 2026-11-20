# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A stockpile survey on the plan: toe and crest outlines and the height map over the base.

The pile height above the base is gridded; the toe is the line where the pile
rises :data:`TOE_HEIGHT_M` above the base, and the crest is the contour at
:data:`CREST_SHARE` of the pile's height, where the side slope gives way to the top.
The volume shown is the survey's own stored volume, never recomputed here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from app.modules.surfaces_volumes.contours import contour_at
from app.modules.surfaces_volumes.tin import Tin

TOE_HEIGHT_M = 0.1
CREST_SHARE = 0.75
#: The height map never carries more cells than this; the cell grows instead.
MAX_CELLS = 40_000


@dataclass
class PileOutline:
    toe: list[tuple[float, float]] = field(default_factory=list)
    crest: list[tuple[float, float]] = field(default_factory=list)
    max_height_m: float = 0.0
    footprint_m2: float = 0.0
    heat: dict | None = None


def _ring_area(ring: list[tuple[float, float]]) -> float:
    s = 0.0
    for i, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(i + 1) % len(ring)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def pile_outline(pile: Tin, base: Tin) -> PileOutline:
    """Toe, crest and the height map of ``pile`` above ``base``."""
    if not len(pile.tri) or not len(base.tri):
        return PileOutline()
    x0, y0, x1, y1 = pile.bbox()
    span = max(x1 - x0, y1 - y0, 1e-6)
    cell = max(span / 200.0, math.sqrt((x1 - x0) * (y1 - y0) / MAX_CELLS) if (x1 - x0) * (y1 - y0) > 0 else 0.0, 0.05)
    nx, ny = max(int(math.ceil((x1 - x0) / cell)), 1), max(int(math.ceil((y1 - y0) / cell)), 1)
    zp = pile.sample_grid(x0, y0, cell, nx, ny)
    zb = base.sample_grid(x0, y0, cell, nx, ny)
    dh = zp - zb
    ok = np.isfinite(dh)
    if not ok.any():
        return PileOutline()
    dh_clip = np.where(ok, np.maximum(dh, 0.0), np.nan)
    top = float(np.nanmax(dh_clip))
    gx, gy = np.meshgrid(x0 + (np.arange(nx) + 0.5) * cell, y0 + (np.arange(ny) + 0.5) * cell)
    # Pad the field with a zero rim so the toe closes even where the pile meets the survey edge.
    field_tin = Tin.from_points(
        np.concatenate([gx[ok], [x0 - cell, x1 + cell, x1 + cell, x0 - cell]]),
        np.concatenate([gy[ok], [y0 - cell, y0 - cell, y1 + cell, y1 + cell]]),
        np.concatenate([dh_clip[ok], [0.0, 0.0, 0.0, 0.0]]),
    )
    toe_lines = contour_at(field_tin, TOE_HEIGHT_M) if top > TOE_HEIGHT_M else []
    crest_lines = contour_at(field_tin, top * CREST_SHARE) if top > TOE_HEIGHT_M else []
    toe = toe_lines[0].coords if toe_lines else []
    crest = crest_lines[0].coords if crest_lines else []
    values = [None if not math.isfinite(v) else round(float(v), 3) for v in np.where(ok, dh, np.nan).ravel()]
    return PileOutline(
        toe=list(toe),
        crest=list(crest),
        max_height_m=round(top, 3),
        footprint_m2=round(_ring_area(list(toe)), 2) if len(toe) >= 3 else 0.0,
        heat={"origin_e": x0, "origin_n": y0, "cell": cell, "nx": nx, "ny": ny, "dh": values},
    )


__all__ = ["CREST_SHARE", "TOE_HEIGHT_M", "PileOutline", "pile_outline"]
