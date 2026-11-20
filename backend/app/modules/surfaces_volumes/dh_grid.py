# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Height difference of two surfaces on a regular grid in project metres, for plan heat maps.

``dh = upper - lower`` at each cell centre; cells where either surface is
missing are ``None``. The cell grows so the grid never carries more than
``max_cells`` cells, which keeps the answer small enough for the browser.
"""

from __future__ import annotations

import math

import numpy as np

from app.modules.surfaces_volumes.tin import Tin

MAX_CELLS = 40_000


def dh_grid(upper: Tin, lower: Tin, max_cells: int = MAX_CELLS) -> tuple[dict | None, np.ndarray | None]:
    """The heat grid as served, and the raw (ny, nx) array for further use; (None, None) without overlap."""
    if not len(upper.tri) or not len(lower.tri):
        return None, None
    ux0, uy0, ux1, uy1 = upper.bbox()
    lx0, ly0, lx1, ly1 = lower.bbox()
    x0, y0, x1, y1 = max(ux0, lx0), max(uy0, ly0), min(ux1, lx1), min(uy1, ly1)
    if x1 <= x0 or y1 <= y0:
        return None, None
    w, h = x1 - x0, y1 - y0
    cell = max(math.sqrt(w * h / max_cells), max(w, h) / 400.0, 0.05)
    nx, ny = max(math.ceil(w / cell), 1), max(math.ceil(h / cell), 1)
    dh = upper.sample_grid(x0, y0, cell, nx, ny) - lower.sample_grid(x0, y0, cell, nx, ny)
    values = [None if not math.isfinite(v) else round(float(v), 3) for v in dh.ravel()]
    return {"origin_e": x0, "origin_n": y0, "cell": cell, "nx": nx, "ny": ny, "dh": values}, dh


__all__ = ["MAX_CELLS", "dh_grid"]
