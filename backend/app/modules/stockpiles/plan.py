# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A stockpile survey on the plan: toe and crest outlines and the height map over the base.

The pile height above the base is gridded; the toe is the line where the pile
rises :data:`TOE_HEIGHT_M` above the base, and the crest is the contour at
:data:`CREST_SHARE` of the pile's height, where the side slope gives way to the top.
The volume shown is the survey's own stored volume, never recomputed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.modules.surfaces_volumes.contours import contour_at
from app.modules.surfaces_volumes.dh_grid import dh_grid
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
    heat, dh = dh_grid(pile, base, MAX_CELLS)
    if heat is None or dh is None:
        return PileOutline()
    ok = np.isfinite(dh)
    if not ok.any():
        return PileOutline()
    x0, y0, cell, nx, ny = heat["origin_e"], heat["origin_n"], heat["cell"], heat["nx"], heat["ny"]
    x1, y1 = x0 + nx * cell, y0 + ny * cell
    dh_clip = np.where(ok, np.maximum(dh, 0.0), np.nan)
    top = float(np.nanmax(dh_clip))
    gx, gy = np.meshgrid(x0 + (np.arange(nx) + 0.5) * cell, y0 + (np.arange(ny) + 0.5) * cell)
    # A zero rim round the field closes the toe even where the pile meets the survey edge.
    field_tin = Tin.from_points(
        np.concatenate([gx[ok], [x0 - cell, x1 + cell, x1 + cell, x0 - cell]]),
        np.concatenate([gy[ok], [y0 - cell, y0 - cell, y1 + cell, y1 + cell]]),
        np.concatenate([dh_clip[ok], [0.0, 0.0, 0.0, 0.0]]),
    )
    toe_lines = contour_at(field_tin, TOE_HEIGHT_M) if top > TOE_HEIGHT_M else []
    crest_lines = contour_at(field_tin, top * CREST_SHARE) if top > TOE_HEIGHT_M else []
    toe = list(toe_lines[0].coords) if toe_lines else []
    crest = list(crest_lines[0].coords) if crest_lines else []
    return PileOutline(
        toe=toe,
        crest=crest,
        max_height_m=round(top, 3),
        footprint_m2=round(_ring_area(toe), 2) if len(toe) >= 3 else 0.0,
        heat=heat,
    )


__all__ = ["CREST_SHARE", "TOE_HEIGHT_M", "PileOutline", "pile_outline"]
